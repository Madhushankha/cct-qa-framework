#!/usr/bin/env python3
"""Publish scenario-engine output (raw-event ndjson) to a Kafka topic.

Defaults to dry-run — prints every record that WOULD be published, does not
touch Kafka. Pass `--live` to actually produce. WARP must be connected so the
broker DNS resolves to private 10.111.x addresses.

Each record in the input ndjson has shape:

  {"__meta": {"topic": ..., "ts_ms": ..., "key": "", ...},
   "payload": { meta, events, previousRecord, processedPnr }}

Only `payload` is sent to Kafka. `__meta.topic` picks the destination unless
`--topic` overrides it. Kafka message keys default to empty string (matching
the observed upstream emh-dev feed); override with `--key`. By default all
records for one publish run go to partition 0 so version ordering is
preserved — override with `--partition N` or `--auto-partition` (hash of
pnr_id into the topic's partition count).

Example:
    ./scripts/publish_raw.py --ndjson /tmp/zztest.ndjson --live
    ./scripts/publish_raw.py --ndjson /tmp/zztest.ndjson \\
        --topic emh-dev.ALTEA-PNRDATA-UAT --partition 0 --live
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
import zlib
from pathlib import Path

DEFAULT_BROKERS = (
    "b-1.accctmskcrtcac1.05hf7o.c4.kafka.ca-central-1.amazonaws.com:9092,"
    "b-2.accctmskcrtcac1.05hf7o.c4.kafka.ca-central-1.amazonaws.com:9092,"
    "b-3.accctmskcrtcac1.05hf7o.c4.kafka.ca-central-1.amazonaws.com:9092"
)


def load_ndjson(path: Path) -> list[dict]:
    records = []
    with open(path) as f:
        for i, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError as e:
                print(f"[publish_raw] line {i} invalid JSON: {e}", file=sys.stderr)
                sys.exit(2)
    return records


def extract_identity(rec: dict) -> tuple[str | None, str | None]:
    pp = rec.get("payload", {}).get("processedPnr", {})
    return pp.get("id"), pp.get("version")


def preflight_brokers(brokers: str) -> None:
    """Smoke-test reachability of at least one broker on 9092 via nc."""
    first = brokers.split(",")[0].split(":")[0]
    try:
        subprocess.run(["nc", "-z", "-w", "3", first, "9092"],
                       check=True, capture_output=True)
    except subprocess.CalledProcessError:
        print(f"[publish_raw] ERR: cannot reach {first}:9092 — is WARP connected?",
              file=sys.stderr)
        sys.exit(3)


def get_partition_count(brokers: str, topic: str) -> int:
    """Return the partition count for the topic via `kcat -L`."""
    out = subprocess.run(
        ["kcat", "-b", brokers, "-L", "-t", topic],
        capture_output=True, text=True, check=True,
    ).stdout
    # "topic "<name>" with <N> partitions"
    import re
    m = re.search(rf'topic "{re.escape(topic)}" with (\d+) partitions', out)
    if not m:
        raise RuntimeError(f"couldn't parse partition count for {topic} from kcat -L output")
    return int(m.group(1))


def choose_partition(
    rec: dict,
    explicit: int | None,
    auto: bool,
    brokers: str,
    topic: str,
) -> int | None:
    if explicit is not None:
        return explicit
    if not auto:
        return 0  # default: all messages for one run → partition 0 for ordering
    pnr_id, _ = extract_identity(rec)
    if not pnr_id:
        return 0
    n = get_partition_count(brokers, topic)
    return zlib.crc32(pnr_id.encode()) % n


def produce_one(
    brokers: str, topic: str, partition: int | None, key: str, payload_json: str,
) -> None:
    cmd = ["kcat", "-P", "-b", brokers, "-t", topic]
    if partition is not None:
        cmd += ["-p", str(partition)]
    # Explicit empty key: we echo `KEY\t<payload>` and tell kcat to split on tab.
    # Matches the observed upstream emh-dev behaviour (empty-string keys).
    cmd += ["-K", "\t"]
    input_bytes = (key + "\t" + payload_json + "\n").encode()
    subprocess.run(cmd, input=input_bytes, check=True, capture_output=True)


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--ndjson", required=True, help="raw-event ndjson from scenario_engine.py")
    ap.add_argument("--topic", help="override __meta.topic (e.g. emh-dev.ALTEA-PNRDATA-UAT)")
    ap.add_argument("--brokers", default=DEFAULT_BROKERS)
    ap.add_argument("--key", default="",
                    help="Kafka message key (default: empty string, matching upstream emh-dev)")
    ap.add_argument("--partition", type=int,
                    help="explicit partition for every message (default: 0)")
    ap.add_argument("--auto-partition", action="store_true",
                    help="partition = crc32(pnr_id) mod partition_count (stable per-PNR spread)")
    ap.add_argument("--pace", type=float, default=0.0,
                    help="seconds to sleep between messages (default: 0 — as fast as possible)")
    ap.add_argument("--live", action="store_true",
                    help="actually produce. Without this, dry-run only.")
    args = ap.parse_args()

    records = load_ndjson(Path(args.ndjson))
    if not records:
        print(f"[publish_raw] {args.ndjson}: empty — nothing to do")
        return 0

    topics = {args.topic or r.get("__meta", {}).get("topic") for r in records}
    if None in topics or not topics:
        print("[publish_raw] ERR: some records have no __meta.topic and no --topic override",
              file=sys.stderr)
        return 2
    topic = args.topic or records[0]["__meta"]["topic"]

    # Summary
    print(f"[publish_raw] source: {args.ndjson}")
    print(f"[publish_raw] target: {topic}  (key='{args.key}', partition={args.partition if args.partition is not None else ('auto' if args.auto_partition else 0)})")
    print(f"[publish_raw] records: {len(records)}")
    for i, r in enumerate(records):
        pnr_id, version = extract_identity(r)
        events_count = len(r.get("payload", {}).get("events", {}).get("events", []))
        prev_ops = len(r.get("payload", {}).get("previousRecord", []))
        size = len(json.dumps(r["payload"], separators=(",", ":")))
        print(f"    [{i}] pnr_id={pnr_id}  version={version}  events={events_count}  previousRecord_ops={prev_ops}  size={size}B")

    if not args.live:
        print("[publish_raw] DRY RUN — add --live to actually produce")
        return 0

    # Safety preflight
    preflight_brokers(args.brokers)

    # Produce
    print(f"[publish_raw] publishing {len(records)} records...")
    t0 = time.monotonic()
    for i, r in enumerate(records):
        target_topic = args.topic or r["__meta"]["topic"]
        partition = choose_partition(r, args.partition, args.auto_partition, args.brokers, target_topic)
        payload_json = json.dumps(r["payload"], separators=(",", ":"))
        pnr_id, version = extract_identity(r)
        try:
            produce_one(args.brokers, target_topic, partition, args.key, payload_json)
            print(f"    [{i}] produced pnr_id={pnr_id} v={version} → {target_topic} p={partition} ({len(payload_json)}B)")
        except subprocess.CalledProcessError as e:
            print(f"    [{i}] FAILED pnr_id={pnr_id} v={version}: {e.stderr.decode() if e.stderr else e}",
                  file=sys.stderr)
            return 4
        if args.pace and i < len(records) - 1:
            time.sleep(args.pace)
    elapsed = time.monotonic() - t0
    print(f"[publish_raw] done: {len(records)} records in {elapsed:.2f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
