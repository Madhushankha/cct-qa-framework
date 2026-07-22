#!/bin/bash
# Flight Disruption PNR Creation Script
# Creates synthetic FD PNRs for SIT testing in CRT environment
# Usage: ./create_fd_pnrs.sh [--crt|--int|--both]

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SCENARIOS_DIR="$SCRIPT_DIR/../scenarios"
AURORA_QUERY="$SCRIPT_DIR/../../CCT_Agent_New/cct-cascade/contrail/runner/plugins/aurora_query.py"

# Broker configs
CRT_BROKERS="b-1.accctmskcrtcac1.05hf7o.c4.kafka.ca-central-1.amazonaws.com:9092,b-2.accctmskcrtcac1.05hf7o.c4.kafka.ca-central-1.amazonaws.com:9092,b-3.accctmskcrtcac1.05hf7o.c4.kafka.ca-central-1.amazonaws.com:9092"
INT_BROKERS="b-1.accctmskintcac1.z22bz6.c3.kafka.ca-central-1.amazonaws.com:9092,b-2.accctmskintcac1.z22bz6.c3.kafka.ca-central-1.amazonaws.com:9092,b-3.accctmskintcac1.z22bz6.c3.kafka.ca-central-1.amazonaws.com:9092"

CRT_TOPIC="emh-dev.ALTEA-PNRDATA-UAT"
INT_TOPIC="emh-int.ALTEA-PNRDATA-INT"

# FD PNR scenarios
FD_PNRS=(
  "ZZFI01-2026-06-10-appr-tier1.json"
  "ZZFI02-2026-06-10-appr-tier2.json"
  "ZZFI03-2026-06-10-appr-tier3.json"
  "ZZFI04-2026-06-10-eu261-uk.json"
  "ZZFI05-2026-06-10-eu261-eur.json"
  "ZZFI06-2026-06-10-asl-israel.json"
  "ZZFI07-2026-06-10-multipax.json"
  "ZZFI08-2026-07-15-no-travel.json"
  "ZZFI09-2026-06-10-mixed-regime.json"
  "ZZFI10-2026-06-10-not-eligible.json"
)

TARGET=${1:-"--crt"}
TEMP_DIR="/tmp/fd-pnrs-$$"
mkdir -p "$TEMP_DIR"

echo "========================================"
echo "Flight Disruption PNR Creation Script"
echo "========================================"
echo "Target: $TARGET"
echo ""

# Step 1: Render scenarios to ndjson
echo "Step 1: Rendering scenarios..."
for scenario in "${FD_PNRS[@]}"; do
  name="${scenario%.json}"
  pnr_code="${name%%-*}"
  echo "  Rendering $pnr_code..."
  python3 "$SCRIPT_DIR/scenario_engine.py" render \
    --scenario "$SCENARIOS_DIR/$scenario" \
    --out "$TEMP_DIR/${pnr_code}.ndjson" 2>/dev/null
done
echo ""

# Step 2: Publish to Kafka
echo "Step 2: Publishing to Kafka..."
if [[ "$TARGET" == "--crt" || "$TARGET" == "--both" ]]; then
  echo "  Publishing to CRT..."
  for scenario in "${FD_PNRS[@]}"; do
    pnr_code="${scenario%%-*}"
    python3 "$SCRIPT_DIR/publish_raw.py" \
      --ndjson "$TEMP_DIR/${pnr_code}.ndjson" \
      --brokers "$CRT_BROKERS" \
      --live 2>&1 | grep -E "done:|produced" | head -1
  done
fi

if [[ "$TARGET" == "--int" || "$TARGET" == "--both" ]]; then
  echo "  Publishing to INT..."
  for scenario in "${FD_PNRS[@]}"; do
    pnr_code="${scenario%%-*}"
    python3 "$SCRIPT_DIR/publish_raw.py" \
      --ndjson "$TEMP_DIR/${pnr_code}.ndjson" \
      --brokers "$INT_BROKERS" \
      --topic "$INT_TOPIC" \
      --live 2>&1 | grep -E "done:|produced" | head -1
  done
fi
echo ""

# Step 3: Wait for cascade
echo "Step 3: Waiting 25 seconds for cascade processing..."
sleep 25
echo ""

# Step 4: Insert ticket records (CRT only for now)
if [[ "$TARGET" == "--crt" || "$TARGET" == "--both" ]]; then
  echo "Step 4: Inserting ticket records..."

  # Single-pax PNRs
  for i in 01 02 03 04 05 06 09 10; do
    pnr_id="ZZFI${i}-2026-06-10"
    [[ "$i" == "08" ]] && pnr_id="ZZFI08-2026-06-20"

    ticket_num="01424000010${i}"
    date="${pnr_id##*-}"

    python3 "$AURORA_QUERY" --env crt exec \
      "INSERT INTO ticket (primary_document_number, pnr_id, passenger_id, ticket_id, document_numbers, issuance_local_date, document_type) VALUES (%(ticket_num)s, %(pnr_id)s, %(passenger_id)s, %(ticket_id)s, ARRAY[%(ticket_num)s], %(date)s, 'T') ON CONFLICT DO NOTHING" \
      --param ticket_num="${ticket_num}" \
      --param pnr_id="${pnr_id}" \
      --param passenger_id="${pnr_id}-PT-1" \
      --param ticket_id="${ticket_num}-${date}" \
      --param date="${date}" \
      --confirm 2>/dev/null
    echo "  Ticket inserted for ZZFI${i}"
  done

  # ZZFI08 special case
  pnr_id="ZZFI08-2026-06-20"
  python3 "$AURORA_QUERY" --env crt exec \
    "INSERT INTO ticket (primary_document_number, pnr_id, passenger_id, ticket_id, document_numbers, issuance_local_date, document_type) VALUES (%(ticket_num)s, %(pnr_id)s, %(passenger_id)s, %(ticket_id)s, ARRAY[%(ticket_num)s], %(date)s, 'T') ON CONFLICT DO NOTHING" \
    --param ticket_num="0142400001008" \
    --param pnr_id="${pnr_id}" \
    --param passenger_id="${pnr_id}-PT-1" \
    --param ticket_id="0142400001008-2026-06-20" \
    --param date="2026-06-20" \
    --confirm 2>/dev/null
  echo "  Ticket inserted for ZZFI08"

  # ZZFI07 multi-pax
  for pt in 1 2 3; do
    pnr_id="ZZFI07-2026-06-10"
    ticket_num="014240000107${pt}"
    [[ "$pt" == "1" ]] && ticket_num="0142400001007"

    python3 "$AURORA_QUERY" --env crt exec \
      "INSERT INTO ticket (primary_document_number, pnr_id, passenger_id, ticket_id, document_numbers, issuance_local_date, document_type) VALUES (%(ticket_num)s, %(pnr_id)s, %(passenger_id)s, %(ticket_id)s, ARRAY[%(ticket_num)s], %(date)s, 'T') ON CONFLICT DO NOTHING" \
      --param ticket_num="${ticket_num}" \
      --param pnr_id="${pnr_id}" \
      --param passenger_id="${pnr_id}-PT-${pt}" \
      --param ticket_id="${ticket_num}-2026-06-10" \
      --param date="2026-06-10" \
      --confirm 2>/dev/null
  done
  echo "  Tickets inserted for ZZFI07 (3 passengers)"
fi
echo ""

# Cleanup
rm -rf "$TEMP_DIR"

# Summary
echo "========================================"
echo "Flight Disruption PNRs Created:"
echo "========================================"
echo "| PNR    | SIT ID     | Scenario                    | Route       |"
echo "|--------|------------|-----------------------------||-------------|"
echo "| ZZFI01 | FD-SIT-001 | APPR Tier 1 (3-6hr, CAD400) | YUL→YYZ     |"
echo "| ZZFI02 | FD-SIT-003 | APPR Tier 2 (6-9hr, CAD700) | YYZ→YVR     |"
echo "| ZZFI03 | FD-SIT-005 | APPR Tier 3 (9hr+, CAD1000) | YVR→YUL     |"
echo "| ZZFI04 | FD-SIT-008 | EU/UK 261 UK (GBP 260)      | LHR→YYZ     |"
echo "| ZZFI05 | FD-SIT-010 | EU 261 Europe (EUR 300)     | CDG→YUL     |"
echo "| ZZFI06 | FD-SIT-014 | ASL Israel (ILS 3580)       | TLV→YYZ     |"
echo "| ZZFI07 | FD-SIT-015 | Multi-pax aggregated        | YYZ→YVR     |"
echo "| ZZFI08 | FD-SIT-017 | No-travel controllable      | YUL→YYC     |"
echo "| ZZFI09 | FD-SIT-020 | Mixed APPR+EU regime        | LHR→YUL     |"
echo "| ZZFI10 | FD-SIT-024 | Not eligible (<3hr)         | YYZ→YUL     |"
echo ""
echo "OTP Email: chathuranga.viraj.qa@gmail.com"
echo ""
echo "Done!"
