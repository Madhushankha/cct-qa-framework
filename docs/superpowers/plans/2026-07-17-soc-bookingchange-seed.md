# soc + bookingchange on the generic seed engine — Implementation Plan

**Date:** 2026-07-17
**Status:** Plan for review
**Builds on:** `docs/superpowers/specs/2026-07-17-generic-feed-seeder-design.md` (principle + architecture),
`docs/superpowers/plans/2026-07-17-generic-seeder-phase1.md` (Phase 1: scenario model + manifest
engine + FD, already implemented — `seed/scenario.py`, `seed/engine.py`,
`data/seed-templates/fd/manifest.yaml`).

**Scope of THIS pass (already landed, see "Done in this pass" below):** registry entries for `soc`
(confirmed) and `bookingchange` (new, two-doc), the parser's multi-doc merge, soc's delay-vocabulary
extension in `seed/scenario.py`, and manifest scaffolds. **Not in this pass** (documented here as the
next tasks): the DDS canonicalizer for `socFlightEligibility`, a `fresh_pnr()` identity helper, and
either feed's live checkpoint auditor — same "out of scope, build per feed as onboarded" boundary the
design doc draws for every feed after FD.

---

## 1. Registry

### soc — already registered, confirmed as the model
`core/registry/feeds/soc.yaml`: single `gap_doc` (`data/gap-docs/soc/SOC_Miro_Gap_Analysis.html`),
no `dataset` (every one of its 81 cases is `seed_pending=True` — the gap doc embeds no per-case
`<div class="datagrid">`, unlike FD's, which supplies ~201). `columns` map the SEEDSPEC_REQUIRED
fields to header names a future dataset table would use; they don't resolve anything today since
there's no dataset to join. `checkpoints.auditor: soc`, `areas: [trip_active, eds_pnr_output,
eds_contact_email, dds_endpoint_systemcode_match]` — a proper subset of FD's areas (no `dds_amount_match`
since soc's compensable unit is a bounded expense claim, not a fixed compensation amount; no
`pending_flight_le_72h` yet).

```
python -c "from catalog.parser import load_catalog; from core.registry import load_feed; print(len(load_catalog(load_feed('soc')).cases))"
# -> 81
```

### bookingchange — new, two gap docs merged into one feed
Booking Change is analyzed as two separate Miro flows in two separate gap docs:
`data/gap-docs/bookingchange/Booking_Change_INVOL_Miro_Gap_Analysis.html` (58 cases, airline-initiated
disruption -> rebook) and `Booking_Change_VOL_Miro_Gap_Analysis.html` (51 cases, customer-initiated
fare/route/date change). **Decision:** one feed, both docs parsed and merged — not two feeds
(`bookingchange_vol`/`bookingchange_invol`) — because they share one Miro eligibility gate (BC-02),
one persona, one checkpoint auditor, and the design doc's per-feed table already lists `bookingchange`
singular with `(INVOL)` as an example, not an exhaustive split. The merge is env-common (both docs'
IDs already avoid collision by convention: `InVOL_TC###` vs `VOL_TC###`), so nothing env-specific is
lost by combining them.

**Parser tweak (minimal, generalized — not bookingchange-specific code):**
- `core/descriptors.Feed` gained `gap_docs: tuple[str, ...] = ()`, a sibling to the existing `gap_doc: str`.
  `""`/`()` (the default) means "single doc" — every existing feed (fd, soc) is unaffected.
- `core/registry.load_feed` reads the new optional `gap_docs:` YAML key.
- `core/validate.validate_feed`/`validate_all` accept `gap_doc` OR `gap_docs` (checks each doc's
  parent dir exists).
- `catalog/parser.load_catalog`: when `feed.gap_docs` is set, parses **every** doc with the existing
  single-doc `parse_gap_doc`, then merges: cases concatenate (order-preserving), `uncovered`
  concatenates, `checkpoints` **dedupe by id** (both docs assert a shared canonical flow — GLOB-01,
  BC-02, ... — so the spine wouldn't otherwise double-count). Each case is stamped
  `seed.extras["source_doc"]` = the doc's filename stem, so a case stays traceable to which analysis
  it came from even though the id prefix already tells you. `feed.dataset` (a future tabular join)
  still applies once, after the merge, across both docs' cases.
- `bookingchange.yaml` sets `gap_doc: ""` and `gap_docs: [INVOL path, VOL path]`.

```
python -c "from catalog.parser import load_catalog; from core.registry import load_feed; print(len(load_catalog(load_feed('bookingchange')).cases))"
# -> 109  (58 INVOL + 51 VOL)
```

**Known data-fidelity caveats for bookingchange (found while parsing, not fixed — need real data, not
parser logic):**
1. **No `data-out` attribute on any card in either doc** (unlike fd/soc, which set
   `data-out="Not Eligible"` etc.) -> `UseCase.verdict` is `""` for all 109 cases today. The
   Eligible/Ineligible/System-Edge/Other bucket instead lives in `data-feat`, which the parser lands
   in `UseCase.regime` (INVOL: 19 Eligible/22 Ineligible/13 System-Edge/4 Other; VOL: 25/22/2/2).
   Until the docs are re-exported with a real `data-out`, any judge/verdict matching for this feed
   should read `regime` as the expected-outcome signal, not `verdict`. Documented in `bookingchange.yaml`'s
   `judge` block.
2. **The `<span class="badge req">` badge holds the test-case PRIORITY (`P1`/`P2`), not a system
   code** — fd/soc badge that span with a real `FD-...`/`SoC-...` code; bookingchange's cards don't
   carry one at all. `UseCase.system_code` will read `"P1"`/`"P2"` for every case — don't rely on it;
   it's a byproduct of the parser being feed-agnostic (it reads whatever's in that badge slot), not a
   bug to special-case in `parser.py`.
3. **Neither doc has a `<div class="datagrid">`** on any card (`grep -c datagrid` = 0 in both), so
   every case is `seed_pending=True`, same as soc — see §2 below, this is the real blocker for
   `seed --all`, not a parser gap.
4. **One duplicate id inside VOL itself**: `VOL_TC019` appears on two distinct cards (one
   `data-feat="Eligible"`, one `"Ineligible"` — "Multi-passenger booking..." vs "Customer changes
   arrival airport to sister..."). `Catalog.by_id()` returns the first; both are still present in
   `Catalog.cases` (the merge/count doesn't drop it) but any id-keyed lookup or `seed-mapping.json`
   entry will only ever address the first. Flagged for whoever owns the source Miro export; not
   something to rename or dedupe silently in the parser (would fabricate an id not in the source).

---

## 2. The real blocker for BOTH feeds: no per-case PNR/passenger/route in the gap doc

FD's gap doc embeds a `datagrid` on ~201/239 cards (locator, passenger, route, ticket, ...), and
`fd.yaml`'s `dataset` join fills the rest from a separate CRT dataset table. **Neither soc's nor
bookingchange's gap doc has any of that** — 100% `seed_pending`. This is why `seed --all`
(`run_seed_all` in `seed/cli.py`) can't run for these feeds yet, independent of anything below: its
render loop does `d.render_case(base_dir, clone_dir, c, ..., flight_date=fdate, ...)` and
`render_case` reads `case.seed.pnr` as the new locator — an empty string writes into
`clone_dir/` (no subdirectory), silently corrupting the batch.

The design doc's principle answers this directly: *"the concrete PNR and absolute flight date are
generated per-env at seed time, never baked into the scenario"* — i.e. this was **never** meant to
come from the gap doc. It's supposed to come from a `fresh_pnr()` manifest helper
(`identity: { $pnr: "{{ fresh_pnr() }}" }`, per the design doc's manifest example) that doesn't exist
yet: `seed/engine.py`'s `eval_formula` only registers `today()`/`date(offset)` as helpers. **This is
the #1 task before soc/bookingchange can seed anything**, and it isn't soc/bookingchange-specific —
FD never needed it because its cases already carry a real dataset locator. Concretely:
- Add `fresh_pnr(env, seq)` (or similar) to the `eval_formula` helper set — a test-safe 6-char
  locator generator scoped to the env's PNR range (mirrors FD's cloner, which currently reuses the
  dataset's own locators rather than minting new ones).
- Independent passenger name/route synthesis per case (design doc: *"unique passenger name, route,
  delay minutes, ... — env-common scenario attributes"*) — needs a small deterministic generator
  (seeded off the case id, so re-runs are stable) since neither feed's gap doc supplies one.

Until that lands, soc/bookingchange stay at "registered + parses" (this pass), not "seedable".

---

## 3. Scenario model

`seed/scenario.py` is shared across every feed (not feed-specific code). Checked soc's actual case
titles (81 cases, see `catalog.parser.load_catalog(load_feed("soc"))`) against
`temporal_intent`/`delay_minutes`:

- **`temporal_intent` needed no changes.** soc's "no travel" phrasing (`"No Travel Origin/Return/
  Incomplete – ..."`) already matches the existing generic `"no travel" in t` check; `"APPR – Pending
  – 72 Hours"` matches the generic `"pending" in t` check. soc has **no** `pre_travel` cases at all
  (no case title says "pre-travel") — everything else defaults to `completed`, which is correct for
  soc's "Transit Delay ..." cases (an already-elapsed disruption).
- **`delay_minutes` needed a real extension.** soc uses a flat **2-hour eligibility threshold**
  vocabulary (`"Transit Delay ≥2h"`, `"... Delay Below 2h"`, `"... Delay Below 2 Hours"`), not fd's
  3/6/9-hour compensation bands. Neither existing regex matched it (`_BAND_RE` requires a digit
  immediately after `"delay"`; `≥`/`>` isn't one. `_HR_RE` requires a literal `"hr"` suffix; soc uses
  bare `"h"`/`"Hours"`). Unmatched, every soc case was silently falling through to the fd amount-tier
  default (240 min) — wrong, and quietly wrong (no error, just a bogus 4-hour delay stamped on a
  "no travel"/"≥2h" case). Added two regexes + two branches (before the amount-tier fallback):
  - `_GE_HR_RE` (`[≥>=]{1,2}\s*(\d+)\s*h`) -> `N*60` minutes (e.g. `"≥2h"` -> 120).
  - `_BELOW_HR_RE` (`below\s*(\d+)\s*h(?:our)?s?`) -> `N*60 - 60` minutes, i.e. a representative
    value strictly under the threshold (e.g. `"Below 2 Hours"` -> 60).
  - Verified against the real 81-case catalog: all 27 delay-bearing titles now resolve to 60 or 120
    (except `"Transit Delay 14 days+ Prior"`, a **pre-existing** false-positive already present
    before this change — `_BAND_RE` matches the literal `14` in `"Delay 14 days+"` as an hour-band
    digit and returns 600. Not a soc-specific regression: the same ambiguity exists for any fd title
    with a bare number after "delay" that isn't an hour count. Flagged, not fixed here — fixing needs
    an anchor like requiring an `h`/`hr` suffix on `_BAND_RE` itself, which risks fd's 239-case
    parity and belongs in its own reviewed change.)
  - Tests: `tests/test_scenario_model.py::test_temporal_intent_soc_titles`,
    `::test_delay_minutes_soc_two_hour_threshold`.
- **Open, not addressed:** what SoC-side `delayCategory` enum value corresponds to "≥2h"? The one
  concrete data point in the repo (`data/dds-templates/appr_cad_400.json`'s `socFlightEligibility[*]
  .delayCategory`) only shows `"DELAY_LT_2_HOURS"` (three occurrences, all NOT_ELIGIBLE/ND samples).
  No sample response in this repo shows the "at or above 2h" category's exact string (candidates by
  naming convention: `DELAY_GE_2_HOURS` / `DELAY_2_HOURS_OR_MORE` / `DELAY_GTE_2_HOURS`) — needs a
  real ELIGIBLE-regime SoC determination sample (or a rule-engine docs check) before a
  `canonicalize_soc_verdict` can emit it confidently. Do not guess this into committed code.
- **bookingchange's vocabulary doesn't fit this model at all**, and no change was made for it here.
  Its titles describe UX/flow outcomes (`"User accepts airline-proposed itinerary"`, `"Delay between
  31 and 179 minutes enables flight change"`, `"User selects date outside allowed 7-day window"`),
  not a temporal-intent + delay-band pair. The one genuinely reusable piece is the `72h`-style
  eligibility-window language in the Miro spine (`BC-02 Eligibility Check ...: 72h ...`), which is a
  BC-specific gate, not `pending`/`pre_travel` in FD's sense. **Recommendation: don't force
  bookingchange through `temporal_intent`/`delay_minutes` as-is** — its scenario model needs its own
  small parser (`change_outcome(uc) -> "accept"|"reject"|"reroute"|...` and a `delay_window_minutes`
  parser for the `"Delay between N and M minutes"` phrasing) once seeding actually starts, not
  shoehorned into the fd/soc-shaped helpers now.

---

## 4. Base template needs — what a SOC/bookingchange PNR+FDM+DDS fixture looks like vs FD's

FD's `data/fd-templates/base_appr/` is a plain ALTEA CREATE cascade: `01_pnr.json` (a booking event,
`processedPnr` with contacts/travelers/segments at `status: "HK"`), `02_ticket.json`, and two FDM XML
legs (`03_fdm_skd_leg1.xml` schedule + `04_fdm_delay_leg1.xml` a delay event). **Nothing in these
four files is fd-specific** — no compensation amount, no systemCode, no regime marker. Every
fd-flavored value lives entirely in the DDS side-channel (S3 `response.json` + `execution_traces`
row), pinned separately by `seed/dds_pin.py`. That's *why* the design doc's per-feed table lists soc
and bookingchange as the same `create` message kind with `pnr, tkt, fdm` — structurally they need the
**exact same three ALTEA files**, just a different DDS array filled in afterward.

Given that, `data/seed-templates/soc/manifest.yaml` and `data/seed-templates/bookingchange/manifest.yaml`
(added in this pass) **reuse `base_dir: data/fd-templates/base_appr` verbatim** — same `identity`
block as FD's manifest (`$locator`/`$date`/`$pnrId` from `scenario_pnr`/`scenario_date`). This is
explicitly a placeholder, not a final answer, per feed:

- **soc**: base_appr's delay-leg FDM shape (a schedule + a delay event) is a reasonable match for
  soc's own "Transit Delay ≥2h" cases. Its `"No Travel Origin/Return/Incomplete"` cases need
  `segmentStatus: UN` on the affected segment — `seed.scenario.segment_status(uc)` already computes
  `"UN"` for `no_travel` intent and `render_from_manifest` already writes it to `meta["segment_status"]`,
  **but nothing rewrites the actual `status: "HK"` field inside `01_pnr.json`/the FDM XML** to match
  — `meta.json` is bookkeeping only today. This is a **pre-existing gap that affects FD's own
  no-travel cases too** (not introduced or fixed here); wiring `segment_status` into
  `render_case`'s `_retext` (a `>HK<` -> `>UN<` replace, mirroring the existing route-code replace
  pattern) is a small, shared fix that unblocks no-travel scenarios for every feed at once — good
  first task before soc's no-travel cases (33/81) can seed correctly.
  For OAL-segment cases (`SOC_UAT-005` "OAL segment", `SOC_UAT-016/017` "Disruption on OAL/STAR"),
  base_appr's single-carrier (AC) leg needs an operating-carrier override the current `_retext`
  doesn't support — a manifest `mutable` entry (`operatingCarrierCode`) rather than a new base file.
- **bookingchange**: base_appr is a weaker fit and is flagged as such in the manifest's own comment.
  INVOL scenarios ("flight cancelled/delayed") plausibly want a **cancelled** segment
  (`segmentStatus: "UN"`, no delay leg at all, or a cancellation-flavored FDM event) rather than a
  delay; VOL scenarios (voluntary date/fare/route change) may not want any disruption at all — just
  an eligible, unremarkable booking the customer chooses to change. Building a real
  `data/bookingchange-templates/` base (or two: one disrupted, one clean) is a Build-order item, not
  done in this pass — the manifest's `base_dir` today is there so `render_from_manifest("bookingchange",
  ...)` at least resolves and produces a syntactically valid (if semantically approximate) fixture,
  not a crash.

---

## 5. DDS verdict array per feed

Both feeds' target arrays already exist, side by side, in the one committed DDS template
(`data/dds-templates/appr_cad_400.json`) — no new template file is needed to start:

- **soc -> `socFlightEligibility[]`** (per regime APPR/EU/ASL): `eligibilityStatus`,
  `systemCode` (`SoC-<REGIME>-<CLASS>-<N>`, confirmed shape from the 81 parsed cases:
  `SoC-APPR-NE-01`, `SoC-APPR-ND-03`, `SoC-APPR-EL-07`, `SoC-APPR-PE-01`, plus two `SoC-Override-*`
  cases with no regime prefix at all — `SoC-Override-Pending`/`SoC-Override-Pay`, worth a special
  case if/when a canonicalizer is built), `delayCategory` (see §3's open enum question),
  `expenseCategories[]` (soc-specific — fd has nothing analogous; a real soc canonicalizer needs to
  populate this per case, which today's template leaves `[]`).
- **bookingchange -> `compensationEligibility[]`** (same array FD uses) — per the design doc,
  "compensation (rebooking-offered)". The template's existing APPR entry
  (`systemCode: "FD-APPR-EL-13"`, `disruptionReason: "COMMERCIAL"`, `reason: "No travel Origin -
  Within carrier's control"`) is itself a plausible INVOL "cancelled for commercial reasons, rebook"
  determination shape — reusable as a starting canonicalizer input, though its `FD-` prefixed
  systemCode is presumably wrong for bookingchange (no `BC-`-prefixed code has been observed anywhere
  in this repo or either gap doc — see §1 caveat 2). Confirming the real systemCode family
  bookingchange emits (if any — the flow may not carry a systemCode the way fd does) needs a live
  rule-engine sample, not a guess.
- Neither feed has a canonicalizer function yet (`seed/dds_pin.py` only has `canonicalize_appr`/
  `canonicalize_verdict`, both `compensationEligibility`-only — reusable as-is for bookingchange,
  wrong array for soc). A `canonicalize_soc_verdict(response, *, system_code, delay_category, ...)`
  targeting `socFlightEligibility` is the soc-specific piece of work; bookingchange can most likely
  reuse `canonicalize_verdict` once/if it gets real systemCodes.

---

## 6. Reusing `seed --all` / the engine

`run_seed_all` (`seed/cli.py`) is currently FD-hardcoded in several places that would need
generalizing (not done in this pass — flagged so the next implementer doesn't rediscover it
mid-task):
- `base_dir = "data/fd-templates/base_appr"` is a literal, not resolved from the feed's manifest —
  should read `data/seed-templates/<feed>/manifest.yaml`'s `base_dir` (i.e. actually call
  `render.render_from_manifest(feed, ...)`, which already exists and IS generic, instead of calling
  `render.render_case(base_dir, ...)` directly with FD's constant).
- `templates = set((e.seed_targets.get("dds", {}).get("templates") or {}).keys())` and
  `_seedable_verdict`/`_DISRUPTION_REGIMES`/`_REGIME_CURRENCY` gate on fd's `FD-<REGIME>-<CLASS>-<N>`
  systemCode shape specifically — soc's `SoC-...` codes and bookingchange's (currently absent) codes
  need their own seedability predicate, or a per-feed-registered one (e.g. a `seedable(uc) -> bool`
  hook alongside the feed's `checkpoints`/`dds` registry keys).
  `_audit_checkpoints` hardcodes reading `core/registry/feeds/fd.yaml` for `checkpoints.areas` — must
  read the *running* feed's own yaml (`f"core/registry/feeds/{feed}.yaml"`), a one-line fix but
  currently silently wrong for any non-fd `seed --all` call today.
- `seed/verify.py`'s `_dds_check` for `dds_endpoint_systemcode_match` falls back to
  `sc.startswith("FD-") and "-EL-" in sc"` when the case carries no expected systemCode — another
  small fd-specific assumption (soc would need `"SoC-"`, bookingchange whatever its real prefix
  turns out to be) to generalize once those feeds have real system codes to check.
- `env.seed_targets.dds.templates` (`core/registry/envs/int.yaml`) only registers the `APPR_CAD_*`
  family. Adding a soc/bookingchange determination requires either a new dds-templates file (if their
  itinerary/regime shape diverges enough) or, since `appr_cad_400.json` already carries both arrays,
  simply reusing the same file under new family keys in `seed_targets.dds.templates` (e.g.
  `SOC_APPR_ND_04: data/dds-templates/appr_cad_400.json`).

None of the above blocks THIS pass's deliverable (registry + parsing + scenario model + scaffolded
manifests); it's the concrete task list for the next implementer to make `seed --all` actually run
soc/bookingchange end to end, in the order: (1) `fresh_pnr()` + per-case name/route synthesis (§2 —
blocks everything), (2) generalize `run_seed_all`'s FD-hardcoded paths (this section), (3) soc's
`canonicalize_soc_verdict` + a resolved `delayCategory` enum (§3/§5), (4) a dedicated bookingchange
base template (§4) once its DDS systemCode shape is confirmed, (5) each feed's live checkpoint
auditor (out of scope per the design doc until then).

---

## Done in this pass

- `core/registry/feeds/bookingchange.yaml` — new, two-doc (`gap_docs`), validates via
  `core.validate.validate_feed`.
- `core/descriptors.Feed.gap_docs`, `core/registry.load_feed`, `core/validate.validate_feed`/
  `validate_all` — generalized to accept a multi-doc feed (backward compatible; fd/soc untouched).
- `catalog/parser.load_catalog` — merges multiple gap docs (concat cases/uncovered, dedupe
  checkpoints by id, tag `seed.extras["source_doc"]`); single-doc feeds behave identically to before.
- `seed/scenario.py` — `delay_minutes` now understands soc's `"≥2h"`/`"Below 2h"` vocabulary
  (`_GE_HR_RE`/`_BELOW_HR_RE`); `temporal_intent` needed no change.
- `data/seed-templates/soc/manifest.yaml`, `data/seed-templates/bookingchange/manifest.yaml` —
  scaffolded, both reusing `data/fd-templates/base_appr` as a documented placeholder base.
- Tests: `tests/test_bookingchange_feed.py` (two-doc merge mechanics + the real registry entry +
  a real-doc smoke test asserting 109 cases), additions to `tests/test_scenario_model.py` (soc
  temporal/delay vocabulary).

**Verified counts:** `soc` parses **81** cases (unchanged, already registered); `bookingchange`
parses **109** cases (58 INVOL + 51 VOL). `python -m pytest -q` is green with no regressions.
