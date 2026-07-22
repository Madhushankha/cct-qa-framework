#!/bin/zsh
# Resolve the vendored root from this script's own location (override: CCTQA_DATAGEN_ROOT).
# zsh param expansion: :a = absolutise, :h = dirname; applied twice -> the datagen root.
KB="${CCTQA_DATAGEN_ROOT:-${0:a:h:h}}"
# Build SOC UAT CRT clone sets end-to-end with checkpoints.
# Usage: run_socuat_crt_sets.sh <LOGFILE> <TAG> [<TAG>...]
set -u
LOG=$1; shift
cd "$KB/scripts"
: > "$LOG"
for TAG in "$@"; do
  echo "===== CRT SET $TAG : gen (unique names) =====" >> "$LOG"
  CRT_UNIQ_NAMES=1 python3 soc_uat_crt_build.py gen --tag $TAG >> "$LOG" 2>&1 || { echo "GEN FAIL $TAG" >> "$LOG"; continue }
  echo "===== CRT SET $TAG : publish =====" >> "$LOG"
  python3 soc_uat_crt_build.py publish --tag $TAG --start 0  --end 42 >> "$LOG" 2>&1
  python3 soc_uat_crt_build.py publish --tag $TAG --start 42 --end 84 >> "$LOG" 2>&1
  sleep 60
  echo "===== CRT SET $TAG : cascade =====" >> "$LOG"
  python3 soc_uat_crt_build.py checkcascade --tag $TAG >> "$LOG" 2>&1
  echo "===== CRT SET $TAG : finalize =====" >> "$LOG"
  python3 soc_uat_crt_build.py finalize --tag $TAG >> "$LOG" 2>&1
  python3 soc_uat_crt_build.py edsinject --tag $TAG >> "$LOG" 2>&1
  echo "===== CRT SET $TAG : verify =====" >> "$LOG"
  python3 soc_uat_crt_build.py verify --tag $TAG >> "$LOG" 2>&1
  echo "===== CRT SET $TAG : checkpoints =====" >> "$LOG"
  AWS_PROFILE=ac-cct-crt python3 fd_checkpoints.py \
    "$KB/scenarios/fd-sit/_FD_SOCUAT84_crt${TAG}_index.json" --env crt >> "$LOG" 2>&1
done
echo "===== ALL REQUESTED SETS DONE =====" >> "$LOG"
