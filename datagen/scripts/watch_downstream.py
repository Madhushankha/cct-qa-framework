#!/usr/bin/env python3
"""Watch the 4 downstream topics (DERIVED-PNR, TRANSFORMED-PNR, EVENT-DETECTION-PNR,
RESULT-EVENT-DETECTION) plus Aurora for a given pnr_id after injection. Optionally
diff the observed cascade against a scenario's `expected_cascade` block.

Typical use (right before or just after publishing):
    ./scripts/watch_downstream.py --scenario scenarios/ZZTEST-2099-12-31-domestic-create-only.json --wait 120

Or manually by pnr_id only:
    ./scripts/watch_downstream.py --pnr-id ZZTEST-2099-12-31 --wait 90

Exit codes:
    0 — all expectations met (or no expectations given)
    1 — mismatches against expected_cascade
    2 — usage error / infra failure (WARP not connected, DB auth, etc.)
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_BROKERS = (
    "b-1.accctmskcrtcac1.05hf7o.c4.kafka.ca-central-1.amazonaws.com:9092,"
    "b-2.accctmskcrtcac1.05hf7o.c4.kafka.ca-central-1.amazonaws.com:9092,"
    "b-3.accctmskcrtcac1.05hf7o.c4.kafka.ca-central-1.amazonaws.com:9092"
)
DOWNSTREAM_TOPICS = [
    "DERIVED-PNR-EVENTS-CRT",
    "TRANSFORMED-PNR-EVENTS-CRT",
    "EVENT-DETECTION-PNR-CRT",
    "RESULT-EVENT-DETECTION-CRT",
]
KCAT_FMT = '{"__meta":{"topic":"%t","offset":%o,"partition":%p,"ts_ms":%T,"key":"%k"},"payload":%s}\n'
DB_HOST = "ac-cct-trip-tracer-rds-cluster-crt-cac1.cluster-cxqe2wacy866.ca-central-1.rds.amazonaws.com"
DB_NAME = "trip-tracer"
DB_USER = "dbadmin"

DB_QUERIES: dict[str, tuple[str, str]] = {
    "trip": ("pnr_id", "SELECT pnr_id, pnr, status, archive_date, created_at FROM trip WHERE pnr_id=%s"),
    "trip_details": ("pnr_id", "SELECT pnr_id, source, travel_type, office_id, iata_number, last_pnr_version, last_modified_event_log_id, last_modified FROM trip_details WHERE pnr_id=%s"),
    "passenger": ("pnr_id", "SELECT passenger_id, first_name, last_name, passenger_type, date_of_birth FROM passenger WHERE pnr_id=%s"),
    "passenger_updates": ("pnr_id_join", "SELECT pu.attribute_type, pu.attribute_action, p.first_name, p.last_name, pu.last_modified FROM passenger_updates pu JOIN passenger p ON pu.passenger_id=p.passenger_id WHERE p.pnr_id=%s ORDER BY pu.last_modified"),
    "flight_segment": ("pnr_id", "SELECT segment_id, marketing_carrier_code, marketing_flight_number, departure_airport, arrival_airport, departure_datetime, segment_status, cabin_code FROM flight_segment WHERE pnr_id=%s"),
    "journey_updates": ("pnr_id", "SELECT entity_version, entity, event_type, event_action, last_modified FROM journey_updates WHERE pnr_id=%s ORDER BY last_modified, entity_version"),
    "eds_pnr_output": ("pnr_id", "SELECT bounds::text, last_modified FROM eds_pnr_output WHERE pnr_id=%s ORDER BY last_modified"),
    "dds_pnr_output": ("pnr_id", "SELECT bounds::text, last_modified FROM dds_pnr_output WHERE pnr_id=%s ORDER BY last_modified"),
    "ticket_updates": ("pnr_id", "SELECT primary_document_number, event_type, last_modified FROM ticket_updates WHERE pnr_id=%s ORDER BY last_modified"),
    "baggage_updates": ("pnr_id", "SELECT bag_tag_number, event_type, event_time FROM baggage_updates WHERE pnr_id=%s ORDER BY event_time"),
}


def load_scenario_if_given(path_str: str | None) -> dict | None:
    if not path_str:
        return None
    return json.loads(Path(path_str).read_text())


def pnr_id_from_scenario(scenario: dict) -> str:
    ident = scenario["identity"]
    return f"{ident['pnr'].upper()}-{ident['booking_date']}"


def preflight_brokers(brokers: str) -> None:
    first = brokers.split(",")[0].split(":")[0]
    try:
        subprocess.run(["nc", "-z", "-w", "3", first, "9092"],
                       check=True, capture_output=True)
    except subprocess.CalledProcessError:
        print(f"[watch_downstream] ERR: broker {first}:9092 unreachable — is WARP connected?",
              file=sys.stderr)
        sys.exit(2)


def start_consumers(brokers: str, wait_seconds: int) -> list[tuple[str, subprocess.Popen]]:
    """Start one kcat consumer per downstream topic, each time-bounded by the system
    `timeout` command. Consumers start at 'end' so they only see messages produced
    AFTER the consumer was launched.
    """
    procs: list[tuple[str, subprocess.Popen]] = []
    for topic in DOWNSTREAM_TOPICS:
        p = subprocess.Popen(
            ["timeout", f"{wait_seconds}s",
             "kcat", "-b", brokers, "-C", "-t", topic,
             "-o", "end", "-f", KCAT_FMT],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
        )
        procs.append((topic, p))
    return procs


def collect_filtered(procs: list[tuple[str, subprocess.Popen]], pnr_id: str) -> dict[str, list[dict]]:
    """Block until all consumers exit (timeout), then filter matching lines per topic."""
    results: dict[str, list[dict]] = {t: [] for t, _ in procs}
    for topic, p in procs:
        out, _ = p.communicate()
        for line in (out or "").splitlines():
            if pnr_id in line:
                try:
                    results[topic].append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    return results


def db_password() -> str:
    env_path = REPO_ROOT / ".env"
    if not env_path.exists():
        raise RuntimeError(".env not found — cannot get RDS_PGSQL_PASSWORD")
    for line in env_path.read_text().splitlines():
        if line.strip().startswith("RDS_PGSQL_PASSWORD"):
            return line.split(":", 1)[1].strip()
    raise RuntimeError("RDS_PGSQL_PASSWORD not in .env")


def query_db(pnr_id: str) -> dict[str, list[dict]]:
    env = os.environ.copy()
    env["PGPASSWORD"] = db_password()
    state: dict[str, list[dict]] = {}
    for table, (_, sql) in DB_QUERIES.items():
        cmd = ["psql", "-h", DB_HOST, "-U", DB_USER, "-d", DB_NAME,
               "-t", "-A", "-F", "\x1f", "-c", sql.replace("%s", f"'{pnr_id}'")]
        try:
            r = subprocess.run(cmd, env=env, capture_output=True, text=True, check=True)
        except subprocess.CalledProcessError as e:
            state[table] = [{"_error": (e.stderr or "").strip()[:200]}]
            continue
        rows = []
        for line in (r.stdout or "").splitlines():
            line = line.strip()
            if not line:
                continue
            rows.append(line.split("\x1f"))
        state[table] = rows
    return state


def extract_derived_event_names(records: list[dict]) -> list[str]:
    out = []
    for r in records:
        ev = r.get("payload", {}).get("eventName")
        if ev:
            out.append(ev)
    return out


def extract_transformed_queries(records: list[dict]) -> list[dict]:
    out = []
    for r in records:
        for q in r.get("payload", {}).get("queries") or []:
            out.append({"command": q.get("command"), "targetTable": q.get("targetTable")})
    return out


def extract_event_detection_queries(records: list[dict]) -> list[dict]:
    return extract_transformed_queries(records)


def extract_eds_summary(records: list[dict]) -> dict:
    if not records:
        return {"count": 0, "bounds_counts": [], "regimes_observed": []}
    bcs: list[int] = []
    regimes: set[str] = set()
    for r in records:
        bounds = r.get("payload", {}).get("bounds") or []
        bcs.append(len(bounds))
        for b in bounds:
            for rg in b.get("regimes") or []:
                regimes.add(rg)
    return {"count": len(records), "bounds_counts": bcs, "regimes_observed": sorted(regimes)}


def compare(observed: dict, expected: dict, db_state: dict[str, list[dict]]) -> list[str]:
    issues: list[str] = []

    exp_derived = [e["eventName"] for e in expected.get("derived_pnr_events") or []]
    obs_derived = extract_derived_event_names(observed["DERIVED-PNR-EVENTS-CRT"])
    for e in exp_derived:
        if e not in obs_derived:
            issues.append(f"DERIVED-PNR: expected eventName {e!r} not observed (observed={obs_derived})")

    exp_tx_tables = {(q["targetTable"], q.get("command", "INSERT"))
                     for q in expected.get("transformed_pnr_queries") or []}
    obs_tx = {(q["targetTable"], q["command"])
              for q in extract_transformed_queries(observed["TRANSFORMED-PNR-EVENTS-CRT"])}
    for t, cmd in exp_tx_tables:
        if (t, cmd) not in obs_tx:
            issues.append(f"TRANSFORMED-PNR: expected query {cmd} {t} not observed")

    exp_ed_tables = {q["targetTable"] for q in expected.get("event_detection_pnr_queries") or []}
    obs_ed = {q["targetTable"]
              for q in extract_event_detection_queries(observed["EVENT-DETECTION-PNR-CRT"])}
    for t in exp_ed_tables:
        if t not in obs_ed:
            issues.append(f"EVENT-DETECTION-PNR: expected table {t} not observed")

    eds = expected.get("eds_result") or {}
    eds_summary = extract_eds_summary(observed["RESULT-EVENT-DETECTION-CRT"])
    if "bounds_count" in eds and eds_summary["bounds_counts"]:
        if eds["bounds_count"] not in eds_summary["bounds_counts"]:
            issues.append(f"RESULT-EVENT-DETECTION: expected bounds_count={eds['bounds_count']}, observed={eds_summary['bounds_counts']}")
    rp = eds.get("regimes_possible")
    if rp is not None:
        extra = set(eds_summary["regimes_observed"]) - set(rp) if rp else set()
        if extra and rp == []:
            issues.append(f"RESULT-EVENT-DETECTION: expected no regimes, observed {sorted(extra)}")

    for tbl, expectation in (expected.get("db_end_state") or {}).items():
        rows = db_state.get(tbl, [])
        n = len(rows)
        exp_rows = expectation.get("rows") if isinstance(expectation, dict) else None
        if exp_rows is None:
            continue
        if isinstance(exp_rows, int):
            if n != exp_rows:
                issues.append(f"DB {tbl}: expected rows={exp_rows}, observed={n}")
        elif isinstance(exp_rows, str) and exp_rows.endswith("+"):
            try:
                lo = int(exp_rows.rstrip("+"))
                if n < lo:
                    issues.append(f"DB {tbl}: expected rows>={lo}, observed={n}")
            except ValueError:
                pass

    return issues


def print_report(pnr_id: str, observed: dict, db_state: dict[str, list[dict]],
                 expected: dict | None, issues: list[str]) -> None:
    print(f"\n========= cascade report for {pnr_id} =========\n")

    print("-- Kafka downstream --")
    for t in DOWNSTREAM_TOPICS:
        recs = observed.get(t, [])
        print(f"  {t}: {len(recs)} matching record(s)")
        if t == "DERIVED-PNR-EVENTS-CRT":
            names = extract_derived_event_names(recs)
            if names:
                print(f"     eventNames: {names}")
        elif t in ("TRANSFORMED-PNR-EVENTS-CRT", "EVENT-DETECTION-PNR-CRT"):
            tables = sorted({q["targetTable"] for q in extract_transformed_queries(recs)})
            if tables:
                print(f"     tables touched: {tables}")
        elif t == "RESULT-EVENT-DETECTION-CRT":
            summary = extract_eds_summary(recs)
            print(f"     EDS: {summary}")
        for r in recs[:5]:
            m = r.get("__meta", {})
            print(f"     offset={m.get('offset')} p={m.get('partition')} ts_ms={m.get('ts_ms')}")

    print("\n-- DB end-state --")
    for tbl, rows in db_state.items():
        print(f"  {tbl}: {len(rows)} row(s)")
        for row in rows[:3]:
            if isinstance(row, list):
                print(f"     {row}")
            elif isinstance(row, dict) and "_error" in row:
                print(f"     ERR: {row['_error']}")

    if expected is not None:
        print("\n-- expected_cascade diff --")
        if not issues:
            print("  ✓ all expectations met")
        else:
            for i in issues:
                print(f"  ✗ {i}")


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--scenario", help="path to scenario.json — provides pnr_id + expected_cascade")
    ap.add_argument("--pnr-id", help="explicit pnr_id (overrides scenario)")
    ap.add_argument("--brokers", default=DEFAULT_BROKERS)
    ap.add_argument("--wait", type=int, default=120, help="seconds to tail downstream topics (default 120)")
    ap.add_argument("--save", help="write observed cascade + db state as JSON to this path")
    args = ap.parse_args()

    scenario = load_scenario_if_given(args.scenario)
    pnr_id = args.pnr_id or (pnr_id_from_scenario(scenario) if scenario else None)
    if not pnr_id:
        print("[watch_downstream] ERR: need --scenario or --pnr-id", file=sys.stderr)
        return 2

    expected = (scenario or {}).get("expected_cascade")

    preflight_brokers(args.brokers)

    print(f"[watch_downstream] pnr_id={pnr_id}  wait={args.wait}s  topics={len(DOWNSTREAM_TOPICS)}")
    print(f"[watch_downstream] starting consumers @ end-of-topic on each of: {', '.join(DOWNSTREAM_TOPICS)}")
    procs = start_consumers(args.brokers, args.wait)
    print(f"[watch_downstream] waiting {args.wait}s for cascade...")
    t0 = time.monotonic()
    observed = collect_filtered(procs, pnr_id)
    kafka_elapsed = time.monotonic() - t0
    print(f"[watch_downstream] Kafka window closed after {kafka_elapsed:.1f}s; querying DB...")

    try:
        db_state = query_db(pnr_id)
    except RuntimeError as e:
        print(f"[watch_downstream] DB query failed: {e}", file=sys.stderr)
        db_state = {}

    issues = compare(observed, expected, db_state) if expected else []
    print_report(pnr_id, observed, db_state, expected, issues)

    if args.save:
        Path(args.save).write_text(json.dumps({
            "pnr_id": pnr_id,
            "wait_seconds": args.wait,
            "observed": observed,
            "db_state": db_state,
            "expected": expected,
            "issues": issues,
        }, indent=2, default=str))
        print(f"\n[watch_downstream] observation saved to {args.save}")

    return 1 if issues else 0


if __name__ == "__main__":
    sys.exit(main())
