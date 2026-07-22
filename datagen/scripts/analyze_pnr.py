#!/usr/bin/env python3
"""
Group and analyze events pulled by pull_pnr.sh.

The DERIVED-PNR-EVENTS-CRT topic carries TWO entity types:

  (1) PNR events      — sourceFeed="PNR", payload at top level, identified by
                        data.pnr. Dominant volume, subject of scenario analysis.
  (2) Flight-ops events — sourceFeed="SNOWFLAKE", payload wrapped in .value,
                        identified by data.iataCarrierCode + flightNumber + dep
                        airport. Event types include OAG_STATUS, gate/time
                        updates, etc. Reported separately.

For PNR events, each business transaction is emitted AT-LEAST-ONCE: the same
(version, eventName) tuple routinely appears 2x within a millisecond. The
classifier dedupes on (version, eventName) before thresholding so duplicate
emission does not skew scenario buckets.

Outputs (all prefixed by the input stem so multiple runs coexist):

  .scenario_summary.csv       per-scenario counts + examples (PNR entities)
  .pnr_timelines.csv          per-PNR: scenario, signature, origin, span
  .llm_ready_samples.jsonl    PII-scrubbed sample PNRs for LLM narration
  .flight_ops_summary.csv     non-PNR events grouped by flight/event type

Usage:
  ./analyze_pnr.py pnr-20260421.ndjson
  ./analyze_pnr.py pnr-20260421.ndjson --no-require-creation
  ./analyze_pnr.py pnr-20260421.ndjson --output-dir reports/ --samples 5
"""

import argparse
import csv
import json
import os
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone


# -----------------------------------------------------------------------------
# scenario classifier
# -----------------------------------------------------------------------------

def _logical_counts(events):
    """Collapse at-least-once duplicates: count unique (version, eventName)."""
    logical = Counter()
    seen = set()
    for e in events:
        key = (e.get("version"), e.get("event"))
        if key in seen:
            continue
        seen.add(key)
        logical[e.get("event")] += 1
    return logical


def _facets(events):
    """Summarize an event list into the facet dict the classifier rules use."""
    c = _logical_counts(events)
    return {
        "total": sum(c.values()),
        "unique_versions": len({e["version"] for e in events if e.get("version")}),
        "has_create": c.get("PNR_CREATION", 0) > 0,
        "seg_removed": c.get("SEGMENT_REMOVED", 0),
        "seg_added": c.get("SEGMENT_ADDED", 0),
        "ssr_added": c.get("SPECIAL_SERVICE_REQUEST_ADDED", 0),
        "ssr_updated": c.get("SPECIAL_SERVICE_REQUEST_UPDATED", 0),
        "seat_ops": c.get("SEATING_ADDED", 0) + c.get("SEATING_UPDATED", 0),
        "codeshare": c.get("CODESHARE_OTHER_AIRLINE_ASSOCIATION", 0),
        "contact_changes": c.get("CONTACT_ADDED", 0) + c.get("CONTACT_REMOVED", 0),
        "keyword_ops": (
            c.get("SPECIAL_KEYWORD_ADDED", 0)
            + c.get("SPECIAL_KEYWORD_UPDATED", 0)
            + c.get("SPECIAL_KEYWORD_REMOVED", 0)
        ),
        "remark_ops": c.get("REMARK_ADDED", 0) + c.get("REMARK_REMOVED", 0),
        "flight_ops": (
            c.get("FLIGHT_TIME_UPDATE", 0)
            + c.get("FLIGHT_NUMBER_UPDATE", 0)
            + c.get("SEGMENT_STATUS_UPDATE", 0)
        ),
        "name_changes": c.get("PASSENGER_NAME_CHANGE", 0),
        "split_group": c.get("SPLIT_PNR_ASSOCIATION", 0) + c.get("GROUP_PNR", 0),
    }


# Rules evaluated top-to-bottom; first match wins. Keep most-specific first.
_RULES = [
    ("S14_split_or_group_pnr",    lambda f: f["split_group"] > 0),
    ("S13_passenger_name_change", lambda f: f["name_changes"] > 0),
    ("S12_flight_ops_update",     lambda f: f["flight_ops"] > 0 and f["seg_removed"] == 0 and f["seg_added"] == 0),
    ("S0_creation_only",          lambda f: f["has_create"] and f["total"] == 1),
    ("S8a_new_with_tagging",      lambda f: f["has_create"]
                                              and (f["keyword_ops"] + f["remark_ops"]) > 0
                                              and f["seg_removed"] == 0 and f["seg_added"] == 0
                                              and f["contact_changes"] == 0 and f["ssr_added"] == 0
                                              and f["seat_ops"] == 0 and f["codeshare"] == 0),
    ("S5_new_with_ssr",           lambda f: f["has_create"] and f["ssr_added"] > 0 and f["seg_removed"] == 0),
    ("S4_new_with_codeshare",     lambda f: f["has_create"] and f["codeshare"] > 0),
    ("S1_new_simple",             lambda f: f["has_create"] and f["seg_added"] > 0 and f["seg_removed"] == 0 and f["total"] <= 5),
    ("S2_rebooking",              lambda f: f["seg_removed"] > 0 and f["seg_added"] > 0),
    ("S3_cancellation",           lambda f: f["seg_removed"] > 0 and f["seg_added"] == 0),
    ("S6_seat_change",            lambda f: f["seat_ops"] > 0 and f["seg_removed"] == 0 and f["seg_added"] == 0),
    ("S7_contact_update",         lambda f: f["contact_changes"] > 0 and f["seg_removed"] == 0 and f["seg_added"] == 0 and f["ssr_added"] == 0),
    ("S5b_ssr_update",            lambda f: f["ssr_updated"] > 0 and f["seg_removed"] == 0 and f["seg_added"] == 0),
    ("S8_tagging_only",           lambda f: (f["keyword_ops"] + f["remark_ops"]) > 0 and f["total"] <= 5),
    ("S11_high_churn",            lambda f: f["unique_versions"] >= 4),
]


def classify(events):
    """Return a short scenario code for a PNR given its ordered event list."""
    f = _facets(events)
    for label, rule in _RULES:
        if rule(f):
            return label
    return "S10_other"


# -----------------------------------------------------------------------------
# loader
# -----------------------------------------------------------------------------

def _extract_pnr_event(row):
    p = row.get("payload")
    if not isinstance(p, dict):
        return None
    d = p.get("data") or {}
    pnr = d.get("pnr")
    if not pnr:
        return None
    last_mod = d.get("lastModification") or {}
    pos = last_mod.get("pointOfSale") or {}
    office = pos.get("office") or {}
    login = pos.get("login") or {}
    return (
        pnr,
        {
            "offset": row["__meta"]["offset"],
            "ts_ms": row["__meta"]["ts_ms"],
            "event": p.get("eventName"),
            "type": p.get("eventType"),
            "version": d.get("version"),
            "pos_office": office.get("id"),
            "pos_city": login.get("cityCode"),
            "pos_country": login.get("countryCode"),
            "pos_system": office.get("systemCode"),
            "traveler_count": d.get("travelerCount"),
            "segment_count": len(d.get("segments") or []),
            "ssr_count": len(d.get("specialRequests") or []),
            "remark_count": len(d.get("remarks") or []),
        },
    )


def _extract_flight_event(row):
    """Extract OAG_STATUS / flight-ops events, which use a .value wrapper."""
    p = row.get("payload")
    if not isinstance(p, dict):
        return None
    # Top-level shape — already a PNR-style envelope — skip (caller handles PNR)
    if (p.get("data") or {}).get("pnr"):
        return None
    # Nested in .value
    inner = p.get("value") if isinstance(p.get("value"), dict) else p
    d = inner.get("data") or {}
    carrier = d.get("iataCarrierCode")
    flight_no = d.get("flightNumber")
    dep = d.get("departureIataAirportCode")
    if not (carrier and flight_no):
        return None
    flight_id = f"{carrier}{flight_no}{('#' + dep) if dep else ''}"
    return (
        flight_id,
        {
            "offset": row["__meta"]["offset"],
            "ts_ms": row["__meta"]["ts_ms"],
            "event": inner.get("eventName"),
            "type": inner.get("eventType"),
            "source": inner.get("sourceFeed"),
            "flight_state": d.get("flightState"),
            "dep_airport": dep,
            "arr_airport": d.get("arrivalIataAirportCode"),
            "sched_dep_local": d.get("scheduledDepartureTimeLocal"),
            "sched_arr_local": d.get("scheduledArrivalTimeLocal"),
        },
    )


def load_events(path):
    by_pnr = defaultdict(list)
    by_flight = defaultdict(list)
    stats = {
        "lines": 0,
        "unparseable": 0,
        "null_payload": 0,
        "pnr_events": 0,
        "flight_events": 0,
        "other_events": 0,
    }
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            stats["lines"] += 1
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                stats["unparseable"] += 1
                continue
            if not isinstance(row.get("payload"), dict):
                stats["null_payload"] += 1
                continue
            res = _extract_pnr_event(row)
            if res is not None:
                pnr, ev = res
                by_pnr[pnr].append(ev)
                stats["pnr_events"] += 1
                continue
            res = _extract_flight_event(row)
            if res is not None:
                fid, ev = res
                by_flight[fid].append(ev)
                stats["flight_events"] += 1
                continue
            stats["other_events"] += 1

    for pnr in by_pnr:
        by_pnr[pnr].sort(key=lambda e: (e["ts_ms"], e["offset"]))
    for fid in by_flight:
        by_flight[fid].sort(key=lambda e: (e["ts_ms"], e["offset"]))
    return by_pnr, by_flight, stats


# -----------------------------------------------------------------------------
# reports
# -----------------------------------------------------------------------------

def _logical_signature(events):
    logical = _logical_counts(events)
    return "|".join(f"{n}x{ev}" for ev, n in logical.most_common())


def write_scenario_summary(out_path, scenarios, by_pnr):
    with open(out_path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(
            [
                "scenario",
                "pnr_count",
                "total_events_raw",
                "median_events_per_pnr",
                "max_events_per_pnr",
                "example_pnrs",
            ]
        )
        for sc in sorted(scenarios):
            pnrs = scenarios[sc]
            counts = sorted(len(by_pnr[p]) for p in pnrs)
            median = counts[len(counts) // 2] if counts else 0
            mx = counts[-1] if counts else 0
            w.writerow([sc, len(pnrs), sum(counts), median, mx, ",".join(pnrs[:5])])


def write_pnr_timelines(out_path, by_pnr, scenarios_by_pnr):
    with open(out_path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(
            [
                "pnr",
                "scenario",
                "n_events_raw",
                "n_events_logical",
                "n_versions",
                "first_version",
                "last_version",
                "first_ts_utc",
                "last_ts_utc",
                "span_min",
                "origin_office",
                "origin_city",
                "origin_country",
                "origin_system",
                "event_signature_logical",
            ]
        )
        for pnr, events in sorted(by_pnr.items()):
            first, last = events[0], events[-1]
            versions = {e["version"] for e in events if e.get("version")}
            span_min = round((last["ts_ms"] - first["ts_ms"]) / 60000, 1)
            logical_total = sum(_logical_counts(events).values())
            w.writerow(
                [
                    pnr,
                    scenarios_by_pnr[pnr],
                    len(events),
                    logical_total,
                    len(versions),
                    first.get("version"),
                    last.get("version"),
                    datetime.fromtimestamp(first["ts_ms"] / 1000, tz=timezone.utc).isoformat(),
                    datetime.fromtimestamp(last["ts_ms"] / 1000, tz=timezone.utc).isoformat(),
                    span_min,
                    first.get("pos_office"),
                    first.get("pos_city"),
                    first.get("pos_country"),
                    first.get("pos_system"),
                    _logical_signature(events),
                ]
            )


def pick_representatives(pnrs, by_pnr, n):
    if not pnrs:
        return []
    sorted_pnrs = sorted(pnrs, key=lambda p: len(by_pnr[p]))
    if len(sorted_pnrs) <= n:
        return sorted_pnrs
    if n == 1:
        return [sorted_pnrs[len(sorted_pnrs) // 2]]
    step = (len(sorted_pnrs) - 1) / (n - 1)
    return [sorted_pnrs[int(round(i * step))] for i in range(n)]


def write_llm_samples(out_path, scenarios, by_pnr, n_per_scenario):
    with open(out_path, "w") as f:
        for sc in sorted(scenarios):
            for pnr in pick_representatives(scenarios[sc], by_pnr, n_per_scenario):
                events = by_pnr[pnr]
                first = events[0]
                rec = {
                    "scenario": sc,
                    "pnr": pnr,
                    "n_events_raw": len(events),
                    "n_events_logical": sum(_logical_counts(events).values()),
                    "n_versions": len({e["version"] for e in events if e.get("version")}),
                    "origin": {
                        "office": first.get("pos_office"),
                        "city": first.get("pos_city"),
                        "country": first.get("pos_country"),
                        "system": first.get("pos_system"),
                    },
                    "events": [
                        {
                            "offset": e["offset"],
                            "ts_ms": e["ts_ms"],
                            "event": e["event"],
                            "type": e["type"],
                            "version": e["version"],
                            "segment_count": e["segment_count"],
                            "ssr_count": e["ssr_count"],
                            "remark_count": e["remark_count"],
                        }
                        for e in events
                    ],
                }
                f.write(json.dumps(rec) + "\n")


def write_flight_ops_summary(out_path, by_flight):
    with open(out_path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(
            [
                "flight_id",
                "n_events",
                "first_ts_utc",
                "last_ts_utc",
                "event_types",
                "states_seen",
                "source",
            ]
        )
        for fid, events in sorted(by_flight.items()):
            first, last = events[0], events[-1]
            types = "|".join(
                f"{n}x{ev}"
                for ev, n in Counter(e["event"] for e in events).most_common()
            )
            states = "|".join(sorted({e["flight_state"] for e in events if e.get("flight_state")}))
            src = next((e["source"] for e in events if e.get("source")), "")
            w.writerow(
                [
                    fid,
                    len(events),
                    datetime.fromtimestamp(first["ts_ms"] / 1000, tz=timezone.utc).isoformat(),
                    datetime.fromtimestamp(last["ts_ms"] / 1000, tz=timezone.utc).isoformat(),
                    types,
                    states,
                    src,
                ]
            )


# -----------------------------------------------------------------------------
# main
# -----------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("input", help="ndjson file produced by pull_pnr.sh")
    ap.add_argument(
        "--require-creation",
        dest="require_creation",
        action="store_true",
        default=True,
        help="keep only PNRs with a PNR_CREATION event in the window (default: true)",
    )
    ap.add_argument(
        "--no-require-creation",
        dest="require_creation",
        action="store_false",
        help="skip the PNR_CREATION filter",
    )
    ap.add_argument(
        "--output-dir",
        default=None,
        help="write reports here (default: next to input)",
    )
    ap.add_argument(
        "--samples",
        type=int,
        default=3,
        help="representative PNRs per scenario in llm_ready_samples.jsonl",
    )
    args = ap.parse_args()

    if not os.path.exists(args.input):
        sys.exit(f"input not found: {args.input}")

    input_dir, input_file = os.path.split(os.path.abspath(args.input))
    input_stem = os.path.splitext(input_file)[0]
    out_dir = args.output_dir or input_dir
    os.makedirs(out_dir, exist_ok=True)
    prefix = os.path.join(out_dir, input_stem)

    print(f"[analyze] loading {args.input}")
    by_pnr, by_flight, stats = load_events(args.input)
    print(
        f"[analyze] lines={stats['lines']}  "
        f"pnr_events={stats['pnr_events']}  "
        f"flight_events={stats['flight_events']}  "
        f"null_payload={stats['null_payload']}  "
        f"unparseable={stats['unparseable']}  "
        f"other={stats['other_events']}"
    )
    print(f"[analyze] unique PNRs: {len(by_pnr)}   unique flights: {len(by_flight)}")

    if args.require_creation:
        before = len(by_pnr)
        by_pnr = {
            p: e for p, e in by_pnr.items() if any(x["event"] == "PNR_CREATION" for x in e)
        }
        print(f"[analyze] filter(PNR_CREATION required): kept {len(by_pnr)}/{before} PNRs")

    scenarios = defaultdict(list)
    scenarios_by_pnr = {}
    for pnr, events in by_pnr.items():
        sc = classify(events)
        scenarios[sc].append(pnr)
        scenarios_by_pnr[pnr] = sc

    summary_path = f"{prefix}.scenario_summary.csv"
    timeline_path = f"{prefix}.pnr_timelines.csv"
    samples_path = f"{prefix}.llm_ready_samples.jsonl"
    flight_path = f"{prefix}.flight_ops_summary.csv"

    write_scenario_summary(summary_path, scenarios, by_pnr)
    write_pnr_timelines(timeline_path, by_pnr, scenarios_by_pnr)
    write_llm_samples(samples_path, scenarios, by_pnr, args.samples)
    if by_flight:
        write_flight_ops_summary(flight_path, by_flight)

    # stdout summary
    print()
    print("=" * 78)
    print(f"{'SCENARIO':<28} {'PNRs':>6} {'RawEv':>8} {'MedEv':>6} {'MaxEv':>6}")
    print("-" * 78)
    total_pnrs = 0
    total_events = 0
    for sc in sorted(scenarios):
        pnrs = scenarios[sc]
        counts = sorted(len(by_pnr[p]) for p in pnrs)
        median = counts[len(counts) // 2] if counts else 0
        mx = counts[-1] if counts else 0
        total_pnrs += len(pnrs)
        total_events += sum(counts)
        print(f"{sc:<28} {len(pnrs):>6} {sum(counts):>8} {median:>6} {mx:>6}")
    print("-" * 78)
    print(f"{'TOTAL':<28} {total_pnrs:>6} {total_events:>8}")
    print("=" * 78)
    print()
    print(f"[analyze] wrote {summary_path}")
    print(f"[analyze] wrote {timeline_path}")
    print(f"[analyze] wrote {samples_path}  ({args.samples} samples/scenario)")
    if by_flight:
        print(f"[analyze] wrote {flight_path}  ({len(by_flight)} flights)")
    print()
    print("To narrate scenarios with an LLM:")
    print(f"  cat {samples_path} | <your-llm> -p \\")
    print("    'Given these grouped PNR event sequences, write a QA test-case narrative")
    print("     per scenario: preconditions, event sequence, expected downstream output,")
    print("     edge cases to cover.'")


if __name__ == "__main__":
    main()
