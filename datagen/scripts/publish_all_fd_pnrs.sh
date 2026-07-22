#!/bin/bash
# Publish all 132 FD SIT PNRs to INT environment
# Usage: ./publish_all_fd_pnrs.sh [--dry-run]

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SCENARIOS_DIR="$SCRIPT_DIR/../scenarios/fd-sit"
AURORA_QUERY="$SCRIPT_DIR/../../CCT_Agent_New/cct-cascade/contrail/runner/plugins/aurora_query.py"

# INT Kafka config
INT_BROKERS="b-1.accctmskintcac1.z22bz6.c3.kafka.ca-central-1.amazonaws.com:9092,b-2.accctmskintcac1.z22bz6.c3.kafka.ca-central-1.amazonaws.com:9092,b-3.accctmskintcac1.z22bz6.c3.kafka.ca-central-1.amazonaws.com:9092"
INT_TOPIC="emh-int.ALTEA-PNRDATA-INT"

DRY_RUN=false
if [[ "$1" == "--dry-run" ]]; then
    DRY_RUN=true
    echo "*** DRY RUN MODE - No messages will be published ***"
fi

TEMP_DIR="/tmp/fd-pnrs-all-$$"
mkdir -p "$TEMP_DIR"

echo "========================================"
echo "FD SIT PNR Mass Publishing Script"
echo "========================================"
echo "Scenarios: $SCENARIOS_DIR"
echo "Target: INT ($INT_TOPIC)"
echo "Dry Run: $DRY_RUN"
echo ""

# Count scenarios
SCENARIO_COUNT=$(ls -1 "$SCENARIOS_DIR"/*.json 2>/dev/null | grep -v _SUMMARY | wc -l | tr -d ' ')
echo "Found $SCENARIO_COUNT scenario files"
echo ""

# Step 1: Render all scenarios
echo "Step 1: Rendering scenarios to NDJSON..."
RENDERED=0
for scenario in "$SCENARIOS_DIR"/*.json; do
    [[ "$(basename "$scenario")" == "_"* ]] && continue

    name=$(basename "$scenario" .json)
    pnr_code="${name%%-*}"

    if python3 "$SCRIPT_DIR/scenario_engine.py" render \
        --scenario "$scenario" \
        --out "$TEMP_DIR/${pnr_code}.ndjson" 2>/dev/null; then
        RENDERED=$((RENDERED + 1))
        printf "\r  Rendered: %d/%d" "$RENDERED" "$SCENARIO_COUNT"
    else
        echo "  WARN: Failed to render $pnr_code"
    fi
done
echo ""
echo "  Rendered $RENDERED scenarios"
echo ""

# Step 2: Publish to Kafka
if [[ "$DRY_RUN" == "false" ]]; then
    echo "Step 2: Publishing to INT Kafka..."
    PUBLISHED=0
    for ndjson in "$TEMP_DIR"/*.ndjson; do
        pnr_code=$(basename "$ndjson" .ndjson)

        if python3 "$SCRIPT_DIR/publish_raw.py" \
            --ndjson "$ndjson" \
            --brokers "$INT_BROKERS" \
            --topic "$INT_TOPIC" \
            --live 2>&1 | grep -q "produced\|done"; then
            PUBLISHED=$((PUBLISHED + 1))
            printf "\r  Published: %d/%d" "$PUBLISHED" "$RENDERED"
        fi
    done
    echo ""
    echo "  Published $PUBLISHED PNRs to Kafka"
    echo ""

    # Step 3: Wait for cascade
    echo "Step 3: Waiting 30 seconds for cascade..."
    sleep 30
    echo ""

    # Step 4: Insert tickets
    echo "Step 4: Inserting ticket records..."
    TICKETS=0
    for scenario in "$SCENARIOS_DIR"/*.json; do
        [[ "$(basename "$scenario")" == "_"* ]] && continue

        # Extract PNR info from scenario
        pnr_code=$(python3 -c "import json; d=json.load(open('$scenario')); print(d['identity']['pnr'])")
        booking_date=$(python3 -c "import json; d=json.load(open('$scenario')); print(d['identity']['booking_date'])")
        pax_count=$(python3 -c "import json; d=json.load(open('$scenario')); print(len(d['passengers']))")
        tickets=$(python3 -c "import json; d=json.load(open('$scenario')); print(','.join(d['ticketing']['ticket_numbers']))")
        issuance_date=$(python3 -c "import json; d=json.load(open('$scenario')); print(d['ticketing']['issuance_local_date'])")

        pnr_id="${pnr_code}-${booking_date}"

        # Insert ticket for each passenger
        IFS=',' read -ra TICKET_ARRAY <<< "$tickets"
        for i in "${!TICKET_ARRAY[@]}"; do
            ticket_num="${TICKET_ARRAY[$i]}"
            pax_num=$((i + 1))
            passenger_id="${pnr_id}-PT-${pax_num}"
            ticket_id="${ticket_num}-${issuance_date}"

            python3 "$AURORA_QUERY" --env int exec \
                "INSERT INTO ticket (primary_document_number, pnr_id, passenger_id, ticket_id, document_numbers, issuance_local_date, document_type) VALUES (%(ticket_num)s, %(pnr_id)s, %(passenger_id)s, %(ticket_id)s, ARRAY[%(ticket_num)s], %(date)s, 'T') ON CONFLICT DO NOTHING" \
                --param ticket_num="${ticket_num}" \
                --param pnr_id="${pnr_id}" \
                --param passenger_id="${passenger_id}" \
                --param ticket_id="${ticket_id}" \
                --param date="${issuance_date}" \
                --confirm 2>/dev/null && TICKETS=$((TICKETS + 1))
        done

        printf "\r  Tickets inserted: %d" "$TICKETS"
    done
    echo ""
    echo "  Inserted $TICKETS ticket records"
else
    echo "Step 2-4: SKIPPED (dry run)"
fi

# Cleanup
rm -rf "$TEMP_DIR"

echo ""
echo "========================================"
echo "Summary"
echo "========================================"
echo "Scenarios rendered: $RENDERED"
if [[ "$DRY_RUN" == "false" ]]; then
    echo "PNRs published: $PUBLISHED"
    echo "Tickets inserted: $TICKETS"
fi
echo ""
echo "OTP Email: chathuranga.viraj.qa@gmail.com"
echo ""
echo "Done!"
