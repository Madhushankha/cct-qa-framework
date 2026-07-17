# FD Seed Correctness Fixes (2026-07-17)

Four defects found by validating the seeded INT data against the `FD_ALL239_lahiru_set5` dataset
and the UAT gap doc, then confirmed by querying the live INT DDS / trip-tracer. All fixed and
covered by the existing test suite (348 passing). A single-case end-to-end run of `FD_ED_TC_01`
went from FAIL (bot: "couldn't find a booking") to **PASS (decision=ELIGIBLE)** after the fixes.

## 1. MIXED-regime verdict bug — `seed/dds_pin.py`

`canonicalize_verdict` derived eligibility from the systemCode **class letter** (`NE`/`ND`), which for
a MIXED itinerary describes only ONE leg. Cases whose gap-doc scenario is "EU Eligible but APPR Not
Eligible" (FD_TC_150) or "EU Eligible but ASL No Determination" (FD_TC_152) were wrongly seeded as
NOT_ELIGIBLE / 0 — the bot would tell an eligible customer they get nothing.

**Fix:** added a `status` parameter (the case's expected verdict) that overrides the class letter, and
for MIXED/DUP eligible cases the determination now targets the leg matching the compensation currency
(`_CURRENCY_REGIME`: GBP/EUR→EU, ILS→ASL, CAD→APPR) instead of always APPR. FD_TC_150 now seeds
ELIGIBLE / 520 GBP on the EU leg; FD_TC_152 ELIGIBLE / 400 EUR. Genuinely-NE MIXED cases (FD_TC_151,
FD_DUP_*) and all single-regime cases are unchanged.

## 2. EDGE/PAY label pinned as systemCode — `seed/cli.py`, `seed/verify.py`

Edge/Payment cases carry a non-DDS label (`EDGE-ID-01`) in the gap-doc `system_code` but the real FD
code (`FD-APPR-EL-400`) in `seed.system_code`. The seeder pinned the label, so the bot read an
unrecognizable determination (`EDGE-ID-01` / not-eligible) and escalated.

**Fix:** `_pin_system_code` (seed/cli.py) pins the gap-doc code only when it is a valid
`FD-<regime>-<class>` disruption code, else falls back to `seed.system_code`. `verify.py` mirrors this
in `_expected_system_code` so the auditor's `dds_endpoint_systemcode_match` expectation matches what
is actually pinned. FD_ED_TC_01 now pins ELIGIBLE / 400 / FD-APPR-EL-400.

## 3. Duplicate trip rows on re-seed — `seed/identity.py` (new), `seed/cli.py`

**The dominant cause of the autoflow run's escalations.** Re-seeding the same dataset PNR left the
prior run's trip-tracer row behind, so the PNR had TWO `trip` rows (stale `INACTIVE` + new `ACTIVE`).
The chatbot's booking lookup couldn't resolve the ambiguity → "I couldn't find a booking." Confirmed
live: VNNOOV had 2 rows and failed; cleanly-seeded PNRs (Set-5 PFSGCN/QGRHNP) had 1 ACTIVE row and
were found.

**Fix (per user directive):** every seed run mints a **brand-new 6-char PNR + independent fresh
first/last name** per case (`seed/identity.py` `fresh_pnr`/`fresh_name`; `run_seed_all` applies them
via `dataclasses.replace` before rendering). The dataset still supplies the scenario; only the identity
is regenerated. Artifacts link by test-case id, so the ephemeral PNR is fine downstream. See the
`fresh-pnr-per-seed` auto-memory.

## 4. Third-party persona type never read — `catalog/parser.py`, `catalog/fixtures.py`, `seed/render.py`

The FD gap-doc card encodes each case's persona/outcome type in `data-arch` (eligible / ne / nd /
pending / **thirdparty**) and its section in `data-grp` (Main / Payment / Edge). The parser read
neither, so the 18 third-party cases (FD_TC_185–200, FD_ED_TC_09/16) ran with the self-claim persona
instead of "filing on behalf of someone else."

**Fix:** the parser reads `data-arch`/`data-grp`, sets `third_party` from `data-arch="thirdparty"`, and
carries the scenario/group through `join_dataset` → `render_case` meta.json → `usecase_from_meta`, so
`build_persona` selects the third-party branch for those cases.

## Focused re-seed / re-run capability

`run_seed_all` gained an `only=[case_ids]` filter so a single case can be seeded + run in isolation
(`cctqa run … --only <locator>`), used to validate each fix without re-seeding all 239.
