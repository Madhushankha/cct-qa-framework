#!/usr/bin/env bash
# Pull the last N messages from any CRT Kafka topic via kcat (through WARP).
#
# Usage:
#   ./pull_topic.sh <TOPIC> [N] [OUTPUT_FILE]
#
# Examples:
#   ./pull_topic.sh DERIVED-TKT-EVENTS-CRT 10000
#   ./pull_topic.sh EVENT-DETECTION-PNR-CRT 5000 out/pnr-detection.ndjson
#   ./pull_topic.sh RESULT-EVENT-DETECTION-CRT
#
# Defaults: N=100000, auto-timestamped output file.
# Requirements: Cloudflare WARP connected, kcat installed (brew install kcat).

set -euo pipefail

TOPIC="${1:-}"
N="${2:-100000}"

if [ -z "$TOPIC" ]; then
  echo "usage: $0 <TOPIC> [N] [OUTPUT_FILE]" >&2
  exit 2
fi

# sanitize topic for filename
SAFE_TOPIC=$(echo "$TOPIC" | tr '/' '_')
OUT="${3:-${SAFE_TOPIC}-$(date +%Y%m%d-%H%M%S)-n${N}.ndjson}"
BROKERS="${BROKERS:-b-1.accctmskcrtcac1.05hf7o.c4.kafka.ca-central-1.amazonaws.com:9092,b-2.accctmskcrtcac1.05hf7o.c4.kafka.ca-central-1.amazonaws.com:9092,b-3.accctmskcrtcac1.05hf7o.c4.kafka.ca-central-1.amazonaws.com:9092}"

bail() { echo "ERROR: $*" >&2; exit 1; }

command -v kcat >/dev/null 2>&1 || bail "kcat not installed. Run: brew install kcat"

reachable=0
for b in b-1 b-2 b-3; do
  if nc -z -w 3 "${b}.accctmskcrtcac1.05hf7o.c4.kafka.ca-central-1.amazonaws.com" 9092 >/dev/null 2>&1; then
    reachable=1; break
  fi
done
[ "$reachable" -eq 1 ] || bail "cannot reach any MSK broker on 9092. Is WARP connected?"

echo "[pull_topic] topic=$TOPIC  n=$N  out=$OUT"
start_ts=$(date +%s)

FMT='{"__meta":{"topic":"%t","offset":%o,"partition":%p,"ts_ms":%T,"key":"%k"},"payload":%s}\n'

# Try "last N" first (fastest for high-volume topics). Fall back to "beginning"
# if kcat returns 0 rows — low-volume topics whose log-start-offset is higher
# than (HWM - N) silently produce nothing on the -o -N path.
kcat -b "$BROKERS" -C -t "$TOPIC" -o -"$N" -c "$N" -e -f "$FMT" \
  > "$OUT" 2> "${OUT}.err" || true

lines=$(wc -l < "$OUT" | tr -d ' ')
if [ "$lines" -eq 0 ]; then
  echo "[pull_topic] -o -$N returned 0; retrying -o beginning -c $N"
  kcat -b "$BROKERS" -C -t "$TOPIC" -o beginning -c "$N" -e -f "$FMT" \
    > "$OUT" 2>> "${OUT}.err" || true
  lines=$(wc -l < "$OUT" | tr -d ' ')
fi

elapsed=$(( $(date +%s) - start_ts ))
size=$(ls -lh "$OUT" | awk '{print $5}')
echo "[pull_topic] done in ${elapsed}s: ${lines} records, ${size}"
echo "[pull_topic] stderr log: ${OUT}.err"
