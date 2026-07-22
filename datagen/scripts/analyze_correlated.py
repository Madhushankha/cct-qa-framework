#!/usr/bin/env python3
"""
Cross-feed correlation analysis for the CRT PNR pipeline.

The CRT architecture splits a single business event (a passenger action on a
reservation) across multiple Kafka topics, each looking at a different facet:

  DERIVED-PNR-EVENTS-CRT           raw PNR lifecycle events (create, segment
                                   changes, SSR, contacts, …) keyed by `pnr`.
  TRANSFORMED-PNR-EVENTS-CRT       same events as DB upsert queries against
                                   `journey_updates`; `pnr`/`pnr_id` inside
                                   queries[].values.
  EVENT-DETECTION-PNR-CRT          higher-level trip model upserts (`trip`,
                                   `trip_details`, `bound`, …); `pnr` inside
                                   queries[].values; id like `<PNR>-<DATE>`.
  RESULT-EVENT-DETECTION-CRT       regime-classifier outcome: bounds with
                                   origin→destination + regimes (APPR etc.).
  DERIVED-BAGGAGE-SMARTSUITE-EVENTS-CRT
                                   physical baggage events (BAG_CREATED,
                                   BAG_ACCEPTED, …) keyed by `bagTag` but joined
                                   to PNR via `data.pnr`.

This script:
  1. Loads any subset of the above topics (ndjson dumps from pull_topic.sh).
  2. Extracts PNR and a one-line event summary from each record.
  3. Computes cross-topic coverage (how many PNRs appear in N feeds).
  4. Writes three reports:
       .coverage.csv       per-topic stats + per-PNR topic coverage
       .journeys.csv       one row per PNR: topic counts + first/last ts + join keys
       .trace_<PNR>.txt    time-ordered trace of a single PNR across all feeds
                           (one file per --trace PNR supplied; or --trace-top N
                           auto-picks the top-N PNRs by cross-feed coverage)

Usage:
  ./analyze_correlated.py corr/            # reads *.ndjson in dir, plus ../pnr-*.ndjson
  ./analyze_correlated.py corr/ --trace AWSY3I --trace AWAAGR
  ./analyze_correlated.py corr/ --trace-top 5
  ./analyze_correlated.py corr/ --output-dir reports/
"""

import argparse
import csv
import glob
import json
import os
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone


# Which filename prefixes map to which topic role. Used only for file discovery
# & pretty labels; the loader is schema-aware regardless of filename.
TOPIC_ROLES = {
    "DERIVED-PNR-EVENTS-CRT":             "DERIVED-PNR",
    "TRANSFORMED-PNR-EVENTS-CRT":         "TRANSFORMED-PNR",
    "EVENT-DETECTION-PNR-CRT":            "EVENT-DETECTION",
    "RESULT-EVENT-DETECTION-CRT":         "RESULT-EVENT",
    "DERIVED-BAGGAGE-SMARTSUITE-EVENTS-CRT": "DERIVED-BAGGAGE",
    "pnr-":                               "DERIVED-PNR",   # historic prefix
}


# -----------------------------------------------------------------------------
# per-topic extraction: (pnr, event_label, one_line_summary)
# -----------------------------------------------------------------------------

def _unwrap(payload):
    """Some producers wrap the real payload in `.value`."""
    if isinstance(payload, dict) and isinstance(payload.get("value"), dict):
        return payload["value"]
    return payload or {}


def extract_derived_pnr(p):
    p = _unwrap(p)
    d = p.get("data") or {}
    pnr = d.get("pnr")
    if not pnr:
        return None
    office = (((d.get("lastModification") or {}).get("pointOfSale") or {}).get("office") or {}).get("id")
    ev = p.get("eventName")
    return pnr, ev, f"v{d.get('version')} {ev}" + (f" @ {office}" if office else "")


def extract_transformed_pnr(p):
    p = _unwrap(p)
    for q in p.get("queries") or []:
        v = q.get("values") or {}
        if v.get("pnr"):
            return (
                v["pnr"],
                p.get("eventName"),
                f"v{v.get('entity_version')} {p.get('eventName')} → {q.get('command')} {q.get('targetTable')}",
            )
    return None


def extract_event_detection(p):
    p = _unwrap(p)
    for q in p.get("queries") or []:
        v = q.get("values") or {}
        if v.get("pnr"):
            summary = f"{q.get('command')} {q.get('targetTable')}"
            if q.get("targetTable") == "trip":
                summary += f" status={v.get('status')}"
            elif "bound" in (q.get("targetTable") or "").lower():
                summary += f" bound={v.get('boundRph')}"
            return v["pnr"], "DETECT", summary
    eid = p.get("id")
    if isinstance(eid, str) and "-" in eid and len(eid) >= 8:
        return eid.split("-")[0], "DETECT", f"id={eid}"
    return None


def extract_result_event(p):
    p = _unwrap(p)
    pnr = p.get("pnr")
    if not pnr:
        return None
    bounds = p.get("bounds") or []
    if not bounds:
        return pnr, "RESULT", "(no bounds)"
    desc = [f"{b.get('origin')}→{b.get('destination')} regimes={b.get('regimes')}" for b in bounds]
    return pnr, "RESULT", " | ".join(desc)


def extract_derived_baggage(p):
    p = _unwrap(p)
    d = p.get("data") or {}
    pnr = d.get("pnr")
    if not pnr:
        return None
    ev = p.get("eventName")
    return pnr, ev, f"bag={d.get('bagTag')} {ev} @ {d.get('stationCode') or '?'}"


EXTRACTORS = {
    "DERIVED-PNR":      extract_derived_pnr,
    "TRANSFORMED-PNR":  extract_transformed_pnr,
    "EVENT-DETECTION":  extract_event_detection,
    "RESULT-EVENT":     extract_result_event,
    "DERIVED-BAGGAGE":  extract_derived_baggage,
}


# -----------------------------------------------------------------------------
# file discovery + loading
# -----------------------------------------------------------------------------

def _role_for_file(path):
    base = os.path.basename(path)
    for prefix, role in TOPIC_ROLES.items():
        if base.startswith(prefix):
            return role
    return None


def discover_files(input_dir):
    """Return {role: path} from *.ndjson in the given dir (plus one level up)."""
    candidates = glob.glob(os.path.join(input_dir, "*.ndjson")) + \
                 glob.glob(os.path.join(input_dir, "..", "*.ndjson"))
    result = {}
    for p in candidates:
        r = _role_for_file(p)
        if r is None or os.path.getsize(p) == 0:
            continue
        # prefer the largest file for each role (latest big pull)
        if r not in result or os.path.getsize(p) > os.path.getsize(result[r]):
            result[r] = os.path.abspath(p)
    return result


def load_topic(role, path):
    """Yield (pnr, event_label, summary, meta_dict) for every parseable row."""
    extractor = EXTRACTORS[role]
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            p = row.get("payload")
            if not isinstance(p, dict):
                continue
            res = extractor(p)
            if res is None:
                continue
            pnr, ev, summary = res
            yield pnr, ev, summary, row.get("__meta", {})


# -----------------------------------------------------------------------------
# reports
# -----------------------------------------------------------------------------

def build_index(files):
    """Build {role: {pnr: [event-dict...]}} across all supplied files."""
    by_topic = {role: defaultdict(list) for role in files}
    stats = {}
    for role, path in files.items():
        total = 0
        with_pnr = 0
        for pnr, ev, summary, meta in load_topic(role, path):
            total += 1
            with_pnr += 1
            by_topic[role][pnr].append({
                "ts_ms": meta.get("ts_ms"),
                "offset": meta.get("offset"),
                "ev": ev,
                "summary": summary,
            })
        # sort each PNR's events chronologically
        for pnr in by_topic[role]:
            by_topic[role][pnr].sort(key=lambda e: (e["ts_ms"] or 0, e["offset"] or 0))
        stats[role] = {
            "file": path,
            "with_pnr_records": with_pnr,
            "unique_pnrs": len(by_topic[role]),
        }
    return by_topic, stats


def compute_coverage(by_topic):
    pnr_topics = defaultdict(set)
    for role, idx in by_topic.items():
        for pnr in idx:
            pnr_topics[pnr].add(role)
    return pnr_topics


def write_coverage_report(out_path, stats, pnr_topics):
    coverage_counts = Counter(len(ts) for ts in pnr_topics.values())
    with open(out_path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["section", "key", "value"])
        for role, s in sorted(stats.items()):
            w.writerow(["topic_stats", role, s["file"]])
            w.writerow(["topic_stats", role + "__with_pnr", s["with_pnr_records"]])
            w.writerow(["topic_stats", role + "__unique_pnrs", s["unique_pnrs"]])
        w.writerow([])
        w.writerow(["coverage_hist", "pnrs_in_N_topics", "count"])
        for n in sorted(coverage_counts, reverse=True):
            w.writerow(["coverage_hist", n, coverage_counts[n]])


def write_journeys_report(out_path, by_topic, pnr_topics):
    roles = sorted(by_topic.keys())
    with open(out_path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(
            ["pnr", "n_topics"]
            + [f"{r}__count" for r in roles]
            + ["first_ts_utc", "last_ts_utc", "span_min"]
        )
        for pnr in sorted(pnr_topics, key=lambda p: -len(pnr_topics[p])):
            counts = [len(by_topic[r].get(pnr) or []) for r in roles]
            all_ts = [
                e["ts_ms"]
                for r in roles
                for e in by_topic[r].get(pnr, [])
                if e.get("ts_ms")
            ]
            if not all_ts:
                continue
            first_ts, last_ts = min(all_ts), max(all_ts)
            w.writerow(
                [pnr, len(pnr_topics[pnr])]
                + counts
                + [
                    datetime.fromtimestamp(first_ts / 1000, tz=timezone.utc).isoformat(),
                    datetime.fromtimestamp(last_ts / 1000, tz=timezone.utc).isoformat(),
                    round((last_ts - first_ts) / 60000, 2),
                ]
            )


def write_trace(out_path, pnr, by_topic):
    """Produce a time-ordered cross-feed trace for a single PNR."""
    all_events = []
    for role, idx in by_topic.items():
        for e in idx.get(pnr, []):
            all_events.append({**e, "topic": role})
    all_events.sort(key=lambda e: (e["ts_ms"] or 0, e["offset"] or 0))
    if not all_events:
        return False
    with open(out_path, "w") as f:
        f.write(f"# Cross-feed trace for PNR {pnr}\n")
        f.write(f"# {len(all_events)} events across {len({e['topic'] for e in all_events})} topics\n\n")
        f.write(f"{'TIME (UTC)':<26}{'TOPIC':<18}{'EVENT':<26}SUMMARY\n")
        f.write("-" * 140 + "\n")
        for e in all_events:
            ts = (
                datetime.fromtimestamp((e["ts_ms"] or 0) / 1000, tz=timezone.utc)
                .strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
            )
            ev = (e["ev"] or "?")[:25]
            summary = (e["summary"] or "")[:80]
            f.write(f"{ts:<26}{e['topic']:<18}{ev:<26}{summary}\n")
    return True


# -----------------------------------------------------------------------------
# main
# -----------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument(
        "input_dir",
        help="directory containing *.ndjson dumps from pull_topic.sh",
    )
    ap.add_argument(
        "--output-dir",
        default=None,
        help="write reports here (default: input_dir)",
    )
    ap.add_argument(
        "--trace",
        action="append",
        default=[],
        help="write a time-ordered trace for this PNR (repeatable)",
    )
    ap.add_argument(
        "--trace-top",
        type=int,
        default=0,
        help="auto-trace the top N PNRs by cross-feed coverage",
    )
    ap.add_argument(
        "--prefix",
        default="correlated",
        help="output file prefix (default: 'correlated')",
    )
    args = ap.parse_args()

    if not os.path.isdir(args.input_dir):
        sys.exit(f"not a directory: {args.input_dir}")

    files = discover_files(args.input_dir)
    if not files:
        sys.exit(f"no recognizable ndjson files found in {args.input_dir}")
    print(f"[corr] discovered {len(files)} topic files:")
    for r, p in sorted(files.items()):
        print(f"  {r:<18} {p}  ({os.path.getsize(p):,} bytes)")

    by_topic, stats = build_index(files)
    pnr_topics = compute_coverage(by_topic)

    out_dir = args.output_dir or args.input_dir
    os.makedirs(out_dir, exist_ok=True)
    prefix = os.path.join(out_dir, args.prefix)

    coverage_path = f"{prefix}.coverage.csv"
    journeys_path = f"{prefix}.journeys.csv"
    write_coverage_report(coverage_path, stats, pnr_topics)
    write_journeys_report(journeys_path, by_topic, pnr_topics)

    # console summary
    print()
    print(f"[corr] per-topic: {{role: (with_pnr_records, unique_pnrs)}}")
    for r, s in sorted(stats.items()):
        print(f"  {r:<18} with_pnr={s['with_pnr_records']:>6}  unique_pnrs={s['unique_pnrs']:>6}")
    coverage_counts = Counter(len(ts) for ts in pnr_topics.values())
    print()
    print("[corr] cross-topic coverage:")
    for n in sorted(coverage_counts, reverse=True):
        print(f"  PNRs in {n} topic(s): {coverage_counts[n]}")
    print()

    # traces
    trace_pnrs = list(args.trace)
    if args.trace_top > 0:
        ranked = sorted(pnr_topics.items(), key=lambda x: (-len(x[1]),
            -sum(len(by_topic[r].get(x[0]) or []) for r in by_topic)))
        for pnr, _ in ranked[: args.trace_top]:
            if pnr not in trace_pnrs:
                trace_pnrs.append(pnr)

    for pnr in trace_pnrs:
        trace_path = f"{prefix}.trace_{pnr}.txt"
        if write_trace(trace_path, pnr, by_topic):
            print(f"[corr] wrote trace: {trace_path}")
        else:
            print(f"[corr] no events for PNR {pnr} — skipped")

    print()
    print(f"[corr] wrote {coverage_path}")
    print(f"[corr] wrote {journeys_path}")


if __name__ == "__main__":
    main()
