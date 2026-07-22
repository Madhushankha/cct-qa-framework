# PNR Test-Data Checkpoints — the canonical list

**Every data-creation pipeline MUST pass `universal_checkpoints.py <index> --env <int|crt|bat>`
before a set is declared done.** All check logic lives in `pnr_common_checks.py` (one place);
`fd_checkpoints.py` and the six domain scripts (`anc/bag/bc/nc/nmvp/sc_checkpoints.py`) run the
same areas plus their domain-specific ones. Do not re-implement any of these checks inline —
import `pnr_common_checks` instead.

Each area exists because it caught (or would have caught) a real defect. Date = incident.

## Booking-side areas (`collect_full`)

| # | Area | What it catches | Incident |
|---|------|-----------------|----------|
| 1 | trip ACTIVE | publish/cascade lost or partial | — |
| 2 | trip_details | cascade landed trip but not details | 2026-07-02 |
| 3 | passenger | pax rows missing | — |
| 4 | DOB set | **re-publish NULLs DOB** (inject doesn't map it) — re-run the DOB UPDATE after every republish | 2026-06-26 |
| 5 | ticket | no ticket row (silently no-ops on duplicate `primary_document_number` — always mint FRESH ticket numbers) | 2026-06-26 |
| 6 | ticket == pax | multi-pax PNR shipped with a single ticket | 2026-07-13 |
| 7 | ticket linkage | ticket present but wired to another PNR's passenger_id, or type != 'T' — count checks are blind to this | 2026-07-13 |
| 8 | eds_pnr_output | EDS consumer stalled/backlogged; a set can be green everywhere else with ZERO eds rows | 2026-07-02 (lahiru2/gap69) |
| 9 | eds contact email | contact drift — eds email is what the bot masks/offers for OTP; changed only via republish or direct jsonb edit | 2026-07-13 (set D switched) |
| 9b | eds contact phone | eds apn.phone stays the DONOR's number — the eds-inject regex only swaps EMAIL. Wrong on every set whose phone != donor's | 2026-07-14 (gimhan/doha carried donor +94712534323) |
| 10 | eds auth == pax | **donor-drift**: eds cloned from a donor that later gained/lost pax ships a phantom auth entry | 2026-07-13 (MHYLXV→KNVKKZ) |
| 11 | GROUP context | group rows need booking_context bookingSubtype=GROUP (cascade never sets it) | fd-group-booking-context |
| 12 | name uniqueness | names must be unique in-set AND absent from the rest of the passenger table. ENFORCED when index rows carry `uniq_names` (use `crt_uniqnames.assign_names` at build time); info-only otherwise | 2026-07-11 |

## Endpoint-side areas (`dds_checks`, rows with `pin`)

| # | Area | What it catches | Incident |
|---|------|-----------------|----------|
| 13 | DDS endpoint | pinned verdict not served / wrong systemCode (stale pin, S3 mismatch, execution_traces race) | 2026-06-26 |
| 14 | DDS amount match | ELIGIBLE seeded with amount 0 / wrong tier (61 under-compensated PNRs found) | 2026-06-29 |
| 15 | NE/ND reason text | non-eligible verdicts must carry the LIVE lookup reason (drives the chatbot's not-eligible boxes); comp details must be ABSENT on non-ELIGIBLE | 2026-07-04/05 remediation |
| 16 | passenger count | DDS passengerEligibility must cover every booking pax (npax / group rules) | multipax sets |
| 17 | PENDING ≤72h | PE verdicts only hold within ±72h of the flight — **PE PNRs age out every ~3 days; re-mint with flight=today-1 before executing** | 2026-07-10 |

## Scenario-side area (`segments_vs_scenario`)

| # | Area | What it catches |
|---|------|-----------------|
| 18 | segments==scenario | trip-tracer booking diverges from the scenario JSON: locator, pax names, per-segment airports / flight number / MARKETING carrier / departure date / bound_rph |

Domain extras (kept in their own scripts): CP loyalty for AC-Wallet sets (fd, int/bat),
seat/bag `seatFeeRefundEligibility` (anc), `baggage_updates` events (bag), VBC endpoint (bc), etc.

## Builder-side rules (follow at CREATION time — the checks above only catch violations)

1. **Booking segments are always AC-OPERATED**; real Star/OAL carrier goes in MARKETING carrier
   + the DDS (operating≠AC blocks the trip-tracer cascade; marketing≠AC is fine, probe 2026-07-03).
2. **Never `ZZ`-prefixed locators** (eds/Flink drops them) and never reuse a locator across sets —
   seed `gen_locators` with every existing index's locators.
3. **Fresh unique ticket numbers per set** (`primary_document_number` is globally unique; INSERT
   silently no-ops on conflict). One ticket PER PASSENGER, linked to that passenger's `-PT-n`.
4. Build eds auth-passenger arrays from the REAL pax count — never copy a donor's verbatim.
4b. Set eds `apn.phone` to the TARGET phone during inject — the regex only swaps email, so the
    phone otherwise stays the donor's (`eds contact phone` area catches it).
5. Unique names: `CRT_UNIQ_NAMES=1` / `crt_uniqnames.assign_names` (DB-filtered surnames); build
   sets SEQUENTIALLY so later sets filter against earlier ones; flag index rows `uniq_names`.
6. PENDING cases: flight date computed at BUILD time (`date.today()-1d`), never a constant.
7. Non-ELIGIBLE DDS pe: lookup `reason`, NO `compensationDetails`, `failureReasons: null`;
   Star → isStarSegment=true only; OAL → isOalSegment=true only. Source of truth:
   `GET /rule-engine/reference/tables` (cached at `scripts/_live_tables_cache.json`).
8. After any repo-wide DDS template remediation, RE-UPLOAD pinned sets' S3 objects (same keys).
9. Republish = DOB nulled + eds contact recomputed — re-apply DOB and re-verify email.
10. Kafka publish can fail mid-chunk (and can false-OK): always `checkcascade` before finalize;
    finalize before cascade completes throws FK errors (ticket→passenger, eds→trip_details).
11. AWS SSO (INT `ARC75-Temp-INT`, CRT `ac-cct-crt`) expires ~daily: publish (Kafka) and CRT DB
    (direct creds) keep working, S3/secretsmanager die — login, then resume from finalize.
12. One transient endpoint connection-reset ≠ data failure — re-run the checkpoint before diagnosing.
