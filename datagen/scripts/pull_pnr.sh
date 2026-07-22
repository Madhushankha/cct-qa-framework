#!/usr/bin/env bash
# Pull the last N messages from DERIVED-PNR-EVENTS-CRT via kcat (through WARP).
#
# Usage:
#   ./pull_pnr.sh               # defaults: N=100000, auto-timestamped output
#   ./pull_pnr.sh 10000
#   ./pull_pnr.sh 100000 pnr.ndjson
#   TOPIC=TRANSFORMED-PNR-EVENTS-CRT ./pull_pnr.sh 5000
#
# Requirements: WARP connected, kcat installed (brew install kcat).

set -euo pipefail

N="${1:-100000}"
OUT="${2:-pnr-$(date +%Y%m%d-%H%M%S)-n${N}.ndjson}"
TOPIC="${TOPIC:-DERIVED-PNR-EVENTS-CRT}"
BROKERS="${BROKERS:-b-1.accctmskcrtcac1.05hf7o.c4.kafka.ca-central-1.amazonaws.com:9092,b-2.accctmskcrtcac1.05hf7o.c4.kafka.ca-central-1.amazonaws.com:9092,b-3.accctmskcrtcac1.05hf7o.c4.kafka.ca-central-1.amazonaws.com:9092}"

bail() { echo "ERROR: $*" >&2; exit 1; }

command -v kcat >/dev/null 2>&1 || bail "kcat not installed. Run: brew install kcat"

# broker reachability (any one succeeding is enough)
reachable=0
for b in b-1 b-2 b-3; do
  if nc -z -w 3 "${b}.accctmskcrtcac1.05hf7o.c4.kafka.ca-central-1.amazonaws.com" 9092 >/dev/null 2>&1; then
    reachable=1; break
  fi
done
[ "$reachable" -eq 1 ] || bail "cannot reach any MSK broker on port 9092. Is Cloudflare WARP connected?"

echo "[pull_pnr] topic=$TOPIC  n=$N  out=$OUT"
echo "[pull_pnr] starting kcat..."
start_ts=$(date +%s)

# -o -N -c N -e: start N messages before the end, consume exactly N, then exit
# -f: format one ndjson record per Kafka message, wrapping raw payload in envelope
# stderr → .err file so it doesn't pollute ndjson
kcat \
  -b "$BROKERS" \
  -C \
  -t "$TOPIC" \
  -o -"$N" \
  -c "$N" \
  -e \
  -f '{"__meta":{"offset":%o,"partition":%p,"ts_ms":%T,"key":"%k"},"payload":%s}\n' \
  > "$OUT" 2> "${OUT}.err"

elapsed=$(( $(date +%s) - start_ts ))
lines=$(wc -l < "$OUT" | tr -d ' ')
size=$(ls -lh "$OUT" | awk '{print $5}')

echo "[pull_pnr] done in ${elapsed}s: ${lines} records (non-null), ${size}"
echo "[pull_pnr] stderr log: ${OUT}.err"
echo ""
echo "Next:  ./analyze_pnr.py $OUT"
