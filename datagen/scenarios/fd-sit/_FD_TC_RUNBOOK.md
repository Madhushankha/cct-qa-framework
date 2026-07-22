# FD_UAT (Tiroshan) — FD_TC_001..005 test-data runbook (INT)

Artifacts + runbook to seed the first 5 FD_UAT test cases in **INT** so the Ask AC bot
quotes the compensation. Recipe: [docs/fd-int-e2e-data-creation.md](../../docs/fd-int-e2e-data-creation.md).

All 5 are **APPR · ELIGIBLE · CAD 400 · Tier 1 (3–<6 h)**; they differ by passenger,
rebooking shape and MSL delay code.

> **STATUS: created live in INT 2026-06-26 and verified end-to-end.** All 5 PNRs are ACTIVE in
> trip-tracer (trip+passenger+segment+ticket) and the DDS endpoint returns FD-APPR-EL-400 / 400 CAD
> for each. **Teardown:** the DDS pins are `execution_traces.correlation_id = 'qa-pin-ZZTC0X'`
> (processed_at 2027) — delete those rows (via ECS Exec) to unpin. S3 objects can stay or be removed.

## Mapping

| TC | PNR / pnrId | Passenger | Itinerary (current) | Rebooking | MSL code | Promise | Net delay | Amount |
|----|-------------|-----------|---------------------|-----------|----------|---------|-----------|--------|
| FD_TC_001 | ZZTC01-2026-06-15 | Catherine Bouchard | AC301 YUL→YYZ | none | 64 | 14:00 (sched) | 4 h | CAD 400 cash |
| FD_TC_002 | ZZTC02-2026-06-15 | Marie-Claire Dubois (Aeroplan 9876543210) | AC302 YUL→YYZ | none | 64 | 14:00 (sched) | 4 h | CAD 400 → **AC Wallet $480** at payment |
| FD_TC_003 | ZZTC03-2026-06-15 | Hugo Villeneuve | AC8101 YUL→YOW + AC8201 YOW→YYZ | VOL→INVOL **ONE_TO_MANY** | 67 | **13:00 (last VOL)** | 4 h | CAD 400 |
| FD_TC_004 | ZZTC04-2026-06-15 | Camille Brosseau | AC427 YUL→YYZ | INVOL→VOL(+ve) **MANY_TO_ONE** | 63 | 10:00 (14-day) | 4 h (6 h − 2 h **deducted**) | CAD 400 |
| FD_TC_005 | ZZTC05-2026-06-15 | Valérie Dupont | AC8302 YUL→YKF + AC8402 YKF→YYZ | INVOL→VOL(−ve) **MANY_TO_MANY** | 62 | 10:00 (14-day) | 5 h (−2 h **NOT** deducted) | CAD 400 |

Auth mailbox (OTP): `Chathuranga.VirajThennakoon@aircanada.ca` (same on all 5 PNR contacts). Locators are 6-char ZZ-prefix
(real-style, not `UA####`). Flight date `2026-06-15` → it is the pnrId suffix.

## Files (per TC, two sources the bot reads)

- Booking → `scenarios/fd-sit/ZZTC0X-2026-06-15.json` (scenario_engine v2; current/flown itinerary)
- DDS     → `scenarios/fd-sit/_dds-templates/ZZTC0X-2026-06-15.dds.json` (response.json for S3 + execution_traces)

Regenerate both with: `python3 scripts/generate_fd_tc_data.py`

## Run (prereqs are yours to do)

1. `aws sso login --profile ARC75-Temp-INT`  (INT account 982081066747)
2. **Connect WARP/Cloudflare** (private broker + rule-engine DNS)
3. Dry-run to review: `./scripts/publish_fd_tc.sh --dry-run`
4. Live: `./scripts/publish_fd_tc.sh --live`
   - renders + publishes each PNR to `emh-int.ALTEA-PNRDATA-INT`
   - PUTs each `response.json` to `s3://ac-cct-rule-engine-store-int/traces/DDS/<today>/<uuid>/response.json`
   - prints the 5 `execution_traces` INSERTs and the ECS Exec command to run them
5. **Tickets** (stage 4): after ~30 s cascade, insert ticket rows (trip-tracer) per
   `publish_all_fd_pnrs.sh` pattern using `aurora_query.py --env int`.
6. **Pin DDS** (stage 6): ECS Exec into the rule-engine task and run the 5 INSERTs
   (printed by the script). `processed_at` is set to 2027 so the row always wins.
7. **Verify** each (from inside the VPC / via the container):
   ```
   curl -H "x-api-key: $DDS_API_KEY" \
     https://rule-engine-platform-service.ac-cct-int.cloud.aircanada.com/rule-engine/dds/output/ZZTC01-2026-06-15
   ```
   Expect HTTP 200 · APPR · ELIGIBLE · FD-APPR-EL-400 · amount 400 CAD · DELAY_3_TO_LT_6_HOURS.

## Known limitations / open items

- **Rebooking history (TC003–005)** is encoded in the **DDS** `promisedItinerary` vs `actualItinerary`
  (which drives the bot's eligibility/amount). The **booking-side** scenario models only the *current*
  flown itinerary — full VOL/INVOL change history in Trip-Tracer would need AACC (`emh-int.ALTEA-AACC-INT`)
  rebooking messages, which `scenario_engine.py` does not yet emit. If Trip-Tracer UI must show the
  change history/rebooking pattern, that is a follow-up.
- **FDM/EDS** (Trip-Tracer delay UI) is not seeded by this runbook. The amount the bot quotes comes from
  the DDS S3 file, so it is optional; seed via `fdm_event_generator.py` if the EDS values must look real.
- **TC002 AC Wallet $480**: the DDS determination amount is the CAD 400 base; the +20% top-up is a
  payment-side calc. DDS file intentionally says 400.
- **`aurora_query.py --env int`** ticket insert: verify the plugin path/creds resolve for trip-tracer INT
  (path moved to `cct-cascade/contrail/_legacy/runner/plugins/aurora_query.py`).
