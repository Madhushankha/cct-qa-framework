#!/bin/zsh
# Resolve the vendored root from this script's own location (override: CCTQA_DATAGEN_ROOT).
# zsh param expansion: :a = absolutise, :h = dirname; applied twice -> the datagen root.
KB="${CCTQA_DATAGEN_ROOT:-${0:a:h:h}}"
# Domain × environment verification sweep with universal_checkpoints.
# Usage: run_universal_sweep.sh <LOGFILE>
set -u
LOG=$1
cd "$KB/scripts"
FD="$KB/scenarios/fd-sit"
RE="$KB/scenarios/recon-indexes"
: > "$LOG"
run () {  # label env index extra-args
  echo "@@@@@ $1 | env=$2 | $(basename $3)" >> "$LOG"
  AWS_PROFILE=$4 python3 universal_checkpoints.py "$3" --env $2 ${=5:-} >> "$LOG" 2>&1
  echo "" >> "$LOG"
}
# ---- FD (full suite incl. DDS + scenario) ----
run "FD-INT (239 latest)"  int "$FD/_FD_ALL239_set3_index.json"   ARC75-Temp-INT
run "FD-CRT (239 v12)"     crt "$FD/_FD_ALL239_crt12_index.json"  ac-cct-crt
run "FD-BAT (239 latest I)" bat "$FD/_FD_ALL239I_bat_index.json"  CCE-Developer-BAT
# ---- SOC (full suite) ----
run "SOC-INT (84)"         int "$FD/_FD_SOCUAT84_int_index.json"  ARC75-Temp-INT
run "SOC-INT extras (2)"   int "$FD/_FD_SOCUAT_EXTRA_index.json"  ARC75-Temp-INT
run "SOC-CRT (v2 set G)"   crt "$FD/_FD_SOCUAT84_crtG_index.json" ac-cct-crt
# ---- six CRT domains (booking-side; domain-specific areas need their own rich indexes) ----
for D in ANC BAG BC NC NMVP SC; do
  [ -f "$RE/_${D}_recon_index.json" ] && \
    run "${D}-CRT (recon)" crt "$RE/_${D}_recon_index.json" ac-cct-crt "--no-dds --no-scenario"
done
echo "@@@@@ SWEEP DONE" >> "$LOG"
