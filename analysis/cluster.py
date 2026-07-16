"""Cheap, deterministic clustering over a list of graded results (docs/context.md §4.6).

reason_clusters(): Counter over a one-line "reason" per result, top-N with sample
scenario_ids — surfaces the handful of failure shapes behind a pile of individually-unique
transcripts.

finding_counts(): Counter of finding codes across a batch — reveals systemic issues
(e.g. "18 cases: eligible determination in DDS but bot escalated").
"""
from __future__ import annotations

from collections import Counter

_MAX_SAMPLES = 5


def reason_clusters(items: list[dict], top_n: int = 10) -> list[dict]:
    """items: graded items, each with {"scenario_id", "reason"}.

    Returns up to top_n clusters, sorted by count desc then reason asc (deterministic):
    [{"reason": str, "count": int, "sample_scenario_ids": [str, ...]}, ...]
    """
    counter: Counter = Counter()
    samples: dict[str, list[str]] = {}

    for i in items:
        reason = i.get("reason", "")
        counter[reason] += 1
        bucket = samples.setdefault(reason, [])
        if len(bucket) < _MAX_SAMPLES:
            bucket.append(i["scenario_id"])

    ranked = sorted(counter.items(), key=lambda kv: (-kv[1], kv[0]))[:top_n]
    return [
        {"reason": reason, "count": count, "sample_scenario_ids": samples[reason]}
        for reason, count in ranked
    ]


def finding_counts(items: list[dict]) -> dict:
    """items: graded items, each with {"findings": [{"code": str, ...}, ...]}.

    Returns a dict of code -> count, sorted by count desc then code asc.
    """
    counter: Counter = Counter()
    for i in items:
        for f in i.get("findings") or []:
            counter[f["code"]] += 1
    return dict(sorted(counter.items(), key=lambda kv: (-kv[1], kv[0])))
