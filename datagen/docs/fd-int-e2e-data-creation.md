# Flight-Disruption (FD) Test Data — End-to-End Creation (INT)

> **VALIDATED 2026-06-26** — recipe confirmed working end-to-end in the Ask AC bot (user-verified).
> Tooling: `scripts/generate_fd_tc_data.py` (FD_TC_001–005) and `scripts/generate_fd_tc30.py`
> (FD_TC_001–030, parametrized: derives tier/amount/systemCode from delay minutes). 30-case index +
> per-PNR S3 keys in `scenarios/fd-sit/_FD_TC30_index.json`; shareable report `~/Downloads/FD_TC_PNRs_INT.html`.
> Critical correctness items that gate the bot: full **`socFlightEligibility`** block (16 fields, not a stub);
> clean **single inject** (re-publishing pollutes EDS with CONTACT_DETAIL changes).
>
> Source: `FD_E2E_DataCreation_Guide.html` (last updated 2026-06-26). Captured into KB 2026-06-26.
> Environment: **INT** · AWS account `982081066747` · region `ca-central-1`.
> Auth: AWS SSO — local profile **`ARC75-Temp-INT`** (role `Arc75-temp`). `aws sso login --profile ARC75-Temp-INT`.
> Network: **WARP/Cloudflare must be connected** (broker + internal endpoint DNS resolve to private addresses).

## What this builds

A complete FD test booking that the **Ask AC chatbot** resolves to a flight-disruption claim
(e.g. **CAD 400**). The bot reads **two independent sources — you must seed both**:

| Source the bot reads | Where it lives | How you seed it |
|---|---|---|
| **BOOKING** (passenger, itinerary, flight) | Trip-Tracer Aurora (Postgres) | Inject PNR + Ticket (+ FDM) to **Kafka** → Trip-Tracer consumes |
| **DISRUPTION / DDS** (eligibility + amount) | **S3** object, indexed by a row in the `execution_traces` reference table | Write `response.json` to S3 + **INSERT** one `execution_traces` row |

The bot's DDS provider is `DDS_PROVIDER=s3`: it calls `GET /rule-engine/dds/output/{pnrId}`,
which looks up the latest `execution_traces` row for that PNR, reads its `response_s3_key`,
and returns that S3 object.

> ⚠️ **The Trip-Tracer Postgres table `dds_pnr_output` is a DECOY — NOT read by the bot.**
> This supersedes the older CRT approach (which seeded `dds_pnr_output`). On INT, seed **S3 + `execution_traces`** only.

## Pipeline at a glance

```
  ┌─────────── BOOKING side (Kafka → Trip-Tracer) ───────────┐
  PNR  ──emh-int.ALTEA-PNRDATA-INT─┐
  TKT  ──emh-int.ALTEA-TKT-INT─────┤→ Trip-Tracer Aurora ── trip / passenger / flight_segment / ticket
  FDM  ──emh-int.EAI-FDM-INT───────┘     (EDS computes) ── eds_flight_output / eds_pnr_output

  ┌─────────── DISRUPTION side (you pin it) ─────────────────┐
  response.json ── PUT ─→ s3://ac-cct-rule-engine-store-int/traces/DDS/<date>/<uuid>/response.json
        ▲                                              │
        └──── execution_traces row (entity_id=pnrId, response_s3_key=↑) ─┘   ← the "reference table"

  BOT (case-intake) ── GET /rule-engine/dds/output/{pnrId}  (x-api-key)
        → execution_traces: latest row WHERE service_type='DDS' AND entity_id=pnrId ORDER BY processed_at DESC
        → download response_s3_key from S3 → returns the determination → shows CAD 400
```

## Reference — endpoints, topics, stores

| Thing | Value |
|---|---|
| MSK (Kafka) secret | `AmazonMSK_ac-cct-msk-int-cac1` (SASL_SSL / SCRAM-SHA-512; `sourceBootstrapServers`) |
| MSK plaintext brokers (used by repo scripts, port 9092) | `b-1.accctmskintcac1.z22bz6.c3.kafka.ca-central-1.amazonaws.com:9092,b-2…,b-3…` |
| PNR topic | `emh-int.ALTEA-PNRDATA-INT` |
| Ticket topic | `emh-int.ALTEA-TKT-INT` |
| FDM (flight movement) topic | `emh-int.EAI-FDM-INT` |
| AACC (rebooking) topic | `emh-int.ALTEA-AACC-INT` |
| Trip-Tracer DB | host `ac-cct-trip-tracer-rds-cluster-int-cac1-instance1.czy2ye8u22qy.ca-central-1.rds.amazonaws.com` · db `trip-tracer` · secret `/int-cac1/ac-cct-trip-tracer-rds-cluster-int-cac1/db-credentials-c9LZOU` (reachable directly) |
| DDS S3 bucket | `ac-cct-rule-engine-store-int` · key prefix `traces/DDS/<yyyy-mm-dd>/<uuid>/response.json` |
| Reference table | `execution_traces` on rule-engine Aurora `ac-cct-rule-engine-int-cac1-rds-cluster` (db `postgres`) |
| DDS read endpoint | `GET https://rule-engine-platform-service.ac-cct-int.cloud.aircanada.com/rule-engine/dds/output/{pnrId}` |
| API key (header `x-api-key`) | `$DDS_API_KEY (export it; not stored in the repo)` (secret `cct-case-intake-int/app-secrets:DDS_API_KEY`) |

## STEP 1 — Inject the booking (Kafka → Trip-Tracer)

Produce three message types. Order matters; allow a few seconds between them so Trip-Tracer
ingests in sequence. PNR + Ticket give the booking; the FDM lifecycle gives the delay/EDS.

**Repo tooling for PNR + Ticket:** `scripts/scenario_engine.py render` → `scripts/publish_raw.py --live`
(see `publish_all_fd_pnrs.sh`). Scenario JSON (`$schema_version: 2`) → NDJSON → Kafka.

**FDM delay lifecycle (240-min controllable arrival delay)** — send four FDM states so EDS records
a real arrival delay with the actual landing:

```
SKD   scheduled                state=SKD
ETD   estimatedTimeArrival=sched+240, <delay><delayCode>64</delayCode><delayTime>240   state=ETD
ON    offblockTime / airborneTime / landingTime=sched+240 (+ same delay code)          state=ON
ARR   arrived                                                                          state=ARR
```

> **Identity conventions.** `pnrId = <LOCATOR>-<flight-date>` (e.g. `TJQMRV-2026-06-21`).
> Use a **real 6-char record locator** (e.g. `TJQMRV`) — **not** `UA####` (parsed as a flight number).
> flight leg id = `AC#<flightNo>#<origin>#<date>`. Phone/email go on the PNR contact.

Result in Trip-Tracer: `trip` (ACTIVE), `passenger`, `flight_segment`, `ticket`, and after FDM,
`eds_flight_output` (`FLIGHT_ARRIVAL_DELAY isDisruption=true delayMinutes=240`) + `eds_pnr_output`.

> **Reconciliation note (raw vs derived FDM).** The guide's raw FDM topic is `emh-int.EAI-FDM-INT`
> (XML `flightDetail` with `<delay>`). The repo's `scripts/fdm_event_generator.py` instead publishes
> **derived** JSON events to `DERIVED-FDM-EVENTS-INT`. For the bot's DDS determination the FDM/EDS
> side is **not** what drives the dollar amount — the S3 `response.json` (Step 2–3) does. FDM mainly
> populates Trip-Tracer UI (`flight_leg_updates`, EDS outputs). If the EDS values must look real in
> Trip-Tracer, seed FDM too; if you only need the bot to quote the amount, Steps 2–3 are sufficient.

## STEP 2 — Build the DDS `response.json`

This is the determination the bot displays. The bot reads the cash amount **only** from
`passengerEligibility[].compensationDetails.amount`. Set `bound`/`boundRph` = **1**; the eligible
`systemCode` encodes the amount (`FD-APPR-EL-400`). Canonical example (APPR eligible, CAD 400) is
checked into the repo as `scenarios/fd-sit/_dds-templates/` (see Step 6 below) — shape:

- `eventMetadata`, `pnrIdentifier{pnrId,pnr}`
- `itineraryDetails[]` — `bound:1, boundRph:1`, `promisedItinerary` + `actualItinerary` with segments
- `compensationEligibility[]` — one object **per regime** (APPR / EU / ASL):
  - eligible regime: `eligibilityStatus:"ELIGIBLE"`, `systemCode:"FD-APPR-EL-400"`, `delayMinutes`,
    `delayType:"CONTROLLABLE"`, `delayCode`, `compensationDetails{amount,currency,delayBand,expiryDate}`
  - non-applicable regimes: `eligibilityStatus:"NOT_ELIGIBLE"`, `systemCode:"FD-<reg>-NA-01"`,
    `compensationDetails{amount:0,currency,delayBand:"NOT_APPLICABLE"}`
- `socFlightEligibility[]` — Standards of Care (meals/hotel). **Must be FULLY shaped**, not a stub:
  include `segmentId, segmentStatus, carrierCode, flightNumber (int), departureAirport, arrivalAirport,
  disruptionType, delayType, delayCode, disruptionReason, customerFriendlyDisruptionReason, delayMinutes,
  delayCategory` and `passengerEligibility[]` with `bookingClass, cabinClass, eligibilityStatus, systemCode,
  reason, expiryDate, expenseCategories`. A stub SoC block (only regime/boundRph/passengerEligibility)
  makes the bot **fail to process the claim** even though `/dds/output` still returns 200 + the amount.
- `seatFeeRefundEligibility: []`

> Pick regime to match residence: **APPR**=Canada, **EU/EU-UK**=Europe, **ASL**=Israel.
> A response without `compensationDetails.amount` shows "eligible, $0".

## STEP 3 — Pin the DDS (write S3 + insert the reference row)

**3a. Write the object to S3:**
```
aws s3 cp response.json \
  s3://ac-cct-rule-engine-store-int/traces/DDS/2026-06-26/<random-uuid>/response.json \
  --content-type application/json --region ca-central-1 --profile ARC75-Temp-INT
```

**3b. Insert the reference row into `execution_traces`.** The rule-engine Aurora is **not** directly
network-reachable. Run psql from **inside** the rule-engine container via ECS Exec (it has the DB
creds in env `CCT_TRACING_DB_*`):
```
aws ecs execute-command --cluster ac-cct-rule-engine-platform-cluster-int \
  --task <taskId> --container App --interactive \
  --command 'bash -c "echo <base64-script> | base64 -d | bash"'

# inside the container:
export PGPASSWORD="$CCT_TRACING_DB_PASSWORD"
psql -h "$CCT_TRACING_DB_HOST" -p 5432 -d "$CCT_TRACING_DB_NAME" -U "$CCT_TRACING_DB_USER" -c "
  INSERT INTO execution_traces
    (id, service_type, correlation_id, entity_id, processed_at, request_s3_key, response_s3_key)
  VALUES (gen_random_uuid(), 'DDS', 'qa-pin-<pnr>', '<LOCATOR>-<date>',
          '2027-06-26 00:00:00+00', NULL,
          'traces/DDS/2026-06-26/<uuid>/response.json');"
```

> **Why a future `processed_at`?** The bot's lookup is `ORDER BY processed_at DESC LIMIT 1`.
> A future timestamp (e.g. 2027) guarantees your row always wins so a later real/scheduled
> determination can't override your test data.

`execution_traces` schema: `id` (uuid), `service_type` (`'DDS'`), `entity_id` (**the pnrId**),
`processed_at` (timestamptz, latest wins), `response_s3_key` (S3 key the bot downloads),
`correlation_id`/`request_s3_key` (free-text/optional).

## STEP 4 — Verify (call the live DDS endpoint)

```
curl -H "x-api-key: $DDS_API_KEY (export it; not stored in the repo)" \
  "https://rule-engine-platform-service.ac-cct-int.cloud.aircanada.com/rule-engine/dds/output/<LOCATOR>-<date>"
```
Expected: `HTTP 200 application/json` with `compensationEligibility[0]` = APPR · `ELIGIBLE` ·
`FD-APPR-EL-400` · `amount 400 CAD` · `DELAY_3_TO_LT_6_HOURS`. Call from inside the VPC (or via the
container) — the endpoint is internal. A 3-byte `"ok"` means wrong path/route, not the DDS service.

## Eligibility & codes

**APPR (Canada) compensation tiers** — drive amount + systemCode:

| Arrival delay | delayBand | amount | systemCode |
|---|---|---|---|
| 180–<360 min (3–<6 h) | `DELAY_3_TO_LT_6_HOURS` | CAD 400 | `FD-APPR-EL-400` |
| 360–<540 min (6–<9 h) | `DELAY_6_TO_LT_9_HOURS` | CAD 700 | `FD-APPR-EL-700` |
| ≥540 min (9 h+) | `DELAY_9_HOURS_OR_MORE` | CAD 1000 | `FD-APPR-EL-1000` |

**Delay-code controllability** (drives ELIGIBLE vs NOT_ELIGIBLE):
- **Controllable** (eligible): `0,5,6,9,11,13,14,15,17,18,19,25,31,32,35,36,37,42,56,61,62,63,64,65,66,67,96,99` — canonical **64**
- **Uncontrollable** (not eligible): `1,2,4,51,58,71,72,73,75,76,77,81–89,93,97,98` (weather etc.)
- **Safety** (not eligible): `3,41,43,44,45,46,47,52,69` — note **41/43/45 are SAFETY, not controllable**

**Eligibility status values** (per regime, per passenger):
- `ELIGIBLE` — pays; needs `compensationDetails.amount > 0`
- `NOT_ELIGIBLE` — `FD-<reg>-NE-xx` (uncontrollable, <3h) or `FD-<reg>-NA-01` (regime not applicable)
- `NO_DETERMINATION` — `FD-<reg>-ND-04` (missing disruption code; engine 14-day-retries)
- `PENDING` — within the 72-hour disruption window

## Gotchas

- **Two sinks, one is a decoy.** Trip-Tracer `dds_pnr_output` is **NOT** read by the bot. Seed S3 + `execution_traces`.
- **Use record-style locators** (6 alphanumeric), never `UA####` (parsed as a flight number).
- **Amount comes from `compensationDetails.amount` only.** No separate amount field.
- **`bound`/`boundRph` = 1** on every section (itinerary, compensation, SoC) to match real data.
- **Bot path config:** the bot must use `DDS_BY_PNR_PATH=/rule-engine/dds/output`. `/rule-engine/api/v1/dds/by-pnr` resolves to an "ok" stub.
- **Residence must match regime** — Canada→APPR, Europe→EU/EU-UK, Israel→ASL.
- **Multi-leg / MSL fidelity.** When the spec enumerates legs (e.g. "Leg 1 AC871 CDG→YYZ; Leg 2 AC121 YYZ→YVR"), model **both** segments in the booking AND in the DDS `promisedItinerary`/`actualItinerary`, and set `mslFlight` to the **correct leg**: Leg 2 for cancelled / OAL / connection-disruption cases (set `operatingCarrierCode`/`isOalSegment`/`isStarSegment` for WS/LH/BA/PAL legs), Leg 1 for "delayed-leg-recovers, final-destination delay below threshold" cases (e.g. NE-26). The DDS verdict (status/code/amount) is independent of this, but the **MSL and final destination are part of the test**, so a single-leg shortcut is a real gap. Multi-leg fixer: `scripts/fix_multileg.py`.

## Updating contact (email/phone) or cloning a PNR
- **Contact isn't a trip-tracer column** — it lives in `eds_pnr_output.bounds[0].authenticationContactDetails…apn.{email,phone}` (computed from the raw PNR contact during cascade). To change email/phone: edit `passengers[].email/phone` in the scenario JSON, **re-render + re-publish**, wait ~30s. **Re-publishing NULLs the DOB** (the inject doesn't carry it) → re-run `UPDATE passenger SET date_of_birth=…`. DDS pins/tickets are untouched.
- **Clone to a fresh PNR for an existing TC:** mint a new 6-char locator, write the DDS via `json.dumps(dds).replace(old_pnrId,new_pnrId).replace('"pnr": "<oldloc>"','"pnr": "<newloc>"')`, copy the scenario (new `identity.pnr`/`scenario_id`, a **unique** ticket number, optional new email), then publish→ticket→DOB→S3→pin→verify. Preserves the verdict exactly. (`primary_document_number` must be globally unique or the ticket INSERT no-ops.)

## Worked example PNRs already live in INT (all APPR ELIGIBLE / CAD 400)
- `TJQMRV-2026-06-21` (MARC LEBLANC)
- `KPTMQR-2026-06-21` (CLAIRE BERGERON)
- `RXPQMT-2026-06-21` (DANIEL ROUSSEAU)

Verify any with the Step 4 curl.

---
See also: `docs/architecture.md`, `docs/pnr-cascade.md`, `scenarios/fd-sit/FD_SIT_PNR_MAPPING.md`,
and the older CRT recipe in memory `fd-crt-test-data-creation` (CRT seeded `dds_pnr_output` directly —
on INT that table is a decoy; use the S3 + `execution_traces` path here instead).
