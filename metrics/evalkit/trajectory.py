"""Deterministic trajectory analysis over chat transcripts.

For each record, detect which canonical business-flow stages the conversation
reached and which anomalies occurred, then score trajectory match as ordered
coverage of the stages the scenario was expected to reach.

Score = LIS(hit stages, in the bot's own designed stage order) / |expected|,
so out-of-order stage hits (e.g. a reset that re-runs identity collection
after the decision) earn no extra credit. 1.0 = the conversation walked the
whole expected flow in order.
"""

import re
from functools import lru_cache

from . import taxonomy


@lru_cache(maxsize=None)
def _compiled(rx):
    # detectors are written as line-anchored patterns over the whole transcript
    return re.compile(rx, re.M)


def _first_match_pos(text, rx):
    m = _compiled(rx).search(text)
    return m.start() if m else None


def _stage_pos(fmt, canonical):
    """The canonical stage's designed position within this bot's flow."""
    keys = [k for k in taxonomy.STAGE_MAP[canonical][fmt] if k != "__intent__"]
    positions = [taxonomy.STAGE_POS[fmt][k] for k in keys if k in taxonomy.STAGE_POS[fmt]]
    return min(positions) if positions else 999


def _lis_length(seq):
    """Longest strictly-increasing subsequence length (n^2 fine at this size)."""
    if not seq:
        return 0
    best = [1] * len(seq)
    for i in range(1, len(seq)):
        for j in range(i):
            if seq[j] < seq[i]:
                best[i] = max(best[i], best[j] + 1)
    return max(best)


def annotate_trajectory(record, fmt):
    """Attach record['trajectory'] = {stages_hit, anomalies, intent_recognized, score}."""
    path = record.get("transcript_path")
    if path:
        with open(path, encoding="utf-8") as f:
            text = f.read()
    elif record.get("transcript_text"):
        # canonical Results carry the transcript inline, already rendered to the detector dialect
        text = record["transcript_text"]
    else:
        record["trajectory"] = None
        return

    # Strip file-header metadata: harness error lines can echo bot text (e.g. the
    # post-chat survey prompt), which would corrupt stage detection and ordering.
    body = re.search(r"^(\*\*🤖 BOT\*\*|\*\*🧑 CUSTOMER\*\*|🤖 \*\*Assistant\*\*|🧑 \*\*Customer\*\*)", text, re.M)
    if body:
        text = text[body.start():]

    # evaluate intent from the first customer turn onward (greeting excluded)
    first_customer = re.search(r"^\*\*🧑 CUSTOMER\*\*|^🧑 \*\*Customer\*\*", text, re.M)
    intent_scope = text[first_customer.start():] if first_customer else text
    intent_recognized = bool(_compiled(taxonomy.INTENT_RX).search(intent_scope))

    stages_hit = {}
    for canonical, srcs in taxonomy.STAGE_MAP.items():
        pos = None
        for key in srcs[fmt]:
            if key == "__intent__":
                if intent_recognized:
                    m = _compiled(taxonomy.INTENT_RX).search(intent_scope)
                    p = (first_customer.start() if first_customer else 0) + m.start()
                    pos = p if pos is None else min(pos, p)
                continue
            rx = taxonomy.STAGE_RX[fmt].get(key)
            if not rx:
                continue
            p = _first_match_pos(text, rx)
            if p is not None:
                pos = p if pos is None else min(pos, p)
        if pos is not None:
            stages_hit[canonical] = pos

    anomalies = []
    for canonical, srcs in taxonomy.ANOMALY_MAP.items():
        for key in srcs[fmt]:
            rx = taxonomy.ANOMALY_RX[fmt].get(key)
            if rx and _compiled(rx).search(text):
                anomalies.append(canonical)
                break

    expected = taxonomy.expected_stages(record)
    # hit expected stages, ordered by this bot's designed flow, scored by
    # where they actually appeared in the conversation
    hit_expected = [(s, stages_hit[s]) for s in expected if s in stages_hit]
    hit_expected.sort(key=lambda sp: _stage_pos(fmt, sp[0]))
    score = _lis_length([p for _, p in hit_expected]) / len(expected) if expected else None

    record["trajectory"] = {
        "stages_hit": sorted(stages_hit, key=stages_hit.get),
        "anomalies": sorted(set(anomalies)),
        "intent_recognized": intent_recognized,
        "score": round(score, 4) if score is not None else None,
    }
