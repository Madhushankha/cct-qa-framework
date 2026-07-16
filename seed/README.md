# P2 — seed + verify (only email + phone)

**The novel piece.** From the parsed catalog, seed both data sources for each use-case — injecting the
user's `{email, phone}` as the OTP-gating contact — then run a per-domain **checkpoint auditor** that
proves each checkpoint is `PASS ✅` before the bot is ever run.

## Why (req #1)
A bot failure is only meaningful if the data was correct. We hit exactly this: the BOUCHARD name bug,
the corporate-email OTP blocker, and the third-party cases that weren't actually seeded as
parent+minor. Verifying by **systemCode-match against both sources first** isolates real bot defects
from data defects. See [`../docs/context.md`](../docs/context.md) §2.

## The two-source model
1. **Booking → trip-tracer Aurora**: publish a PNR to **Kafka** (`emh-*.ALTEA-PNRDATA-*`); cascade
   (~30s) into `trip / trip_details / passenger / flight_segment / eds_pnr_output`.
2. **DDS verdict → S3 + `execution_traces` pin** (served by `/rule-engine/dds/output/<pnrId>`).
   ⚠️ `dds_pnr_output` in trip-tracer is a **decoy** — do not verify against it.

## The "only email + phone" contract
The user supplies `{email, phone}` (a real reachable inbox + SMS). The framework injects it as the
`eds_pnr_output` contact on **every** seeded PNR so OTP is receivable; **all other fields derive from
the catalog `SeedSpec`**. (Fixed DOB `1986-04-23`.) Email change after cascade needs a **version-bump
republish** or the deduped cascade won't update the contact.

## Phase pipeline (idempotent)
`index → clone → publish → checkcascade → finalize → verify` — re-runnable; safe to resume.
UPDATE cases (name/seat/segment change) send a **CREATE prelude** first (change detectors FK to a
parent a bare UPDATE lacks).

## Checkpoint auditors
Per-feed verifier (`fd`, `soc`, `nc`, `anc`, `bag`, `sc`, `bc`, `nmvp`) whose checks are exactly the
use-case's checkpoint vector. FD areas (representative):
`trip ACTIVE · trip_details · passenger · DOB · ticket · eds_pnr_output · eds contact email · GROUP
context · DDS endpoint (systemCode match) · DDS amount match · NE/ND reason text · AC-Wallet loyalty ·
passenger count · PENDING flight ≤72h · name uniqueness`.
Verification is **systemCode-match**, so NOT_ELIGIBLE / NO_DETERMINATION / PENDING are validated too.
Output: per-checkpoint `PASS ✅ / FAIL` → a seed-readiness gate before running (P3).

## Inputs / outputs
- **In:** `Catalog` (P1), `Env` seed targets (P0), `{email, phone}`.
- **Out:** seeded bookings + DDS pins; a **seed-verification report** per use-case (the checkpoint
  vector with actual PASS/FAIL); a go/no-go signal for the runner.

## Harvest from
`CCT_Agent_New 2/CCT_Agent_New/HOWTO_CREATE_PNR_DATA.md` (recipe), `.../cct-cascade/contrail`
(`feeds/pnr_lifecycle.py` CREATE-prelude, `injection/`, `catalog/scenario_recipes.py`). Rebuild the
`*_checkpoints.py` auditors from the checkpoint-area lists (not present in the workspace).

## Status
Design. Build after P0+P1.
