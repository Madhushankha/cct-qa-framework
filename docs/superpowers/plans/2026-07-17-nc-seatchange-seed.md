# NC + SeatChange (UPDATE feeds — CREATE-prelude) Seed Plan

**Date:** 2026-07-17
**Status:** Grounded plan (registry landed; scenario `change()` stub landed; seed path documented)
**Feed registries:** `core/registry/feeds/nc.yaml`, `core/registry/feeds/seatchange.yaml`
**Gap docs:** `data/gap-docs/nc/Name_Correction_Miro_Gap_Analysis.html`,
`data/gap-docs/seatchange/Seat_Change_Miro_Gap_Analysis.html`
**Reference (cct-qa-1):** findings summarized below (booking-only/eligible-booking CREATE + live
UPDATE, RPH/channel routing for NC, bookingSource/window/eligible for SeatChange).
**Reference (contrail, the proven CREATE-prelude implementation this plan ports):**
`../cct-cascade/contrail/src/contrail/feeds/pnr_lifecycle.py`

## What NC and SeatChange are

Both are **UPDATE** feeds (`message_kind: create+update`, per the generic-feed-seeder design doc's
"Per-feed shape" table). Unlike FD/SOC/ANC (pure CREATE), the thing under test is a **change to an
existing booking**, not the booking itself:

- **NC (Name Correction):** a booking-only CREATE (pnr + ticket — no FDM, no DDS) establishes the
  passenger, then a live name-change UPDATE event carries the old→new name, an RPH, and
  channel/op_carrier routing (ACV, OAL/Star Alliance, employee-travel OID prefixes, Non-1A GDS —
  several NC cases exist purely to test this routing, e.g. `NameCorrection_TC029`..`TC054`).
- **SeatChange:** an eligible-booking CREATE (pnr + ticket — no FDM, no DDS) establishes the
  journey, then a live seating UPDATE event carries `bookingSource`, the window (`NON_VOID`), and
  an `eligible` flag.

Neither feed pins a DDS determination — there is no compensation/refund verdict to fill; the
"verdict" is whether the correction/seat-change flow completed (see each registry's `judge` block).

## Case counts (parsed by `catalog.parser.load_catalog`)

| feed | cases | seed_pending | third_party | spine checkpoints | parser tweak needed |
|---|---|---|---|---|---|
| nc | 67 | 67 | 0 | 20 | none |
| seatchange | 67 | 67 | 0 | 18 | none |

Both gap docs load cleanly through the existing feed-agnostic parser (`catalog/parser.py`) with no
code changes — `load_feed("nc")` / `load_feed("seatchange")` + `validate_feed()` + `load_catalog()`
all succeed today. Both docs carry **zero `<div class="datagrid">` cards** (no embedded tabular PNR
dataset, unlike FD's joined `dataset` reference), so every case parses `seed_pending=True`; the
`columns:` map in each registry file is a placeholder for a future dataset/manifest to fill (same
pattern as `anc.yaml` / `baggage.yaml` / `nonmvp.yaml`). Both docs also carry **zero bot/user
transcript rows** (`_ROW_RE` in `catalog/parser.py` matches nothing) even though the underlying
Gherkin steps (under each card's `<details class="orig">`) do narrate concrete values — see
"scenario.change() gap" below.

One data quirk found while parsing: card `SeatChange_TC049` inside the **nc** gap doc is titled
"Name with slight misspelling passes identification and completes flow" — an NC case mislabeled
with a `SeatChange_` id prefix upstream. `seed.scenario.change()` accounts for this (see below).

## The CREATE-prelude mechanism

Per the design spec (`docs/superpowers/specs/2026-07-17-generic-feed-seeder-design.md`,
"CREATE-prelude" section): a bare UPDATE on a fresh locator produces **no Aurora write** — the
change detector's downstream INSERT is FK-blocked because no parent row exists yet, and
PNR-creation detectors **short-circuit** the detector chain when they fire (so a single message
can either CREATE the PNR *or* fire a per-element change, never both).

This is not new territory — contrail already solved and proved it for the twin FDM/PNR runtime.
`../cct-cascade/contrail/src/contrail/feeds/pnr_lifecycle.py` is the reference implementation this
plan ports:

- **`needs_create_prelude(payload)`** — true if the payload is an UPDATE at a change-detector path
  (name-change `^/travelers/(\d+)/names/(\d+)/(firstName|middleName|lastName)$`, seating
  `^/products/(\d+)/seating$`, segment-status, flight-number, group-size, keyword) **and** carries
  no root `{eventType:CREATED, currentPath:""}` event (a root CREATE would make
  `PNRCreationDetector`/`GroupPNRDetector` ingest the PNR on its own — no prelude needed then).
- **`synthesize_create_payload(payload)`** — derives the CREATE message from the SAME (already
  re-keyed) body: replaces `events.events[]` with a single root `{CREATED, currentPath:""}`, drops
  `previousRecord` (only meaningful on a COMPARISON diff), and **reverts the changed field to a
  pre-change value** (name: `names[0]` → a different first/last name; seating:
  `seating.seats[0].number` → a different seat) so the later UPDATE is a genuine transition, not a
  no-op.
- **`wait_for_passenger_row(env, pnr_id)`** / **`wait_for_trip_details(env, pnr_id)`** — poll Aurora
  (`passenger` / `trip_details`) until the CREATE's child row lands, or timeout.

The exact detector-path evidence (from `pnr_lifecycle.py`'s inline comments, CRT-verified 2026-06):

| change | UPDATE path | pre-change revert |
|---|---|---|
| name (NC) | `^/travelers/(\d+)/names/(\d+)/(firstName\|middleName\|lastName)$` | `names[0]` → a different first/last name (contrail default: `JOAO`/`MAIA`) |
| seating (SeatChange) | `^/products/(\d+)/seating$`, `seating.seats[0].number` | a different pre-change seat number (contrail default: `14C`) |

(The design spec's shorthand — "products/N subType=SEATING" — refers to the same seating change;
the field contrail actually reverts is `seating.seats[0].number` under `products[N].seating`, not a
literal `subType` discriminator. This plan and any manifest built from it should follow the
CRT-verified path above.)

### This framework's equivalent of contrail's `aurora_adapter` / `wait_for_*`

This repo already has the read-only Aurora surface contrail's `wait_for_passenger_row` needs:
`seed/source.py`'s `AuroraSource` (and `TripTracerSource` protocol) query `passenger` (`passengers(pnr)`)
and `trip`/`trip_details`-shaped tables today (used by `seed/verify.py`'s checkpoint auditor). The
CREATE-prelude's `wait_for={table: "passenger", column: "pnr_id"}` step should poll through this
same `AuroraSource`, not a new adapter — e.g. a small `wait_for_row(src, pnr, kind="passenger",
timeout=30, poll=2.0)` helper that retries `src.passengers(pnr)` (or a new `src.trip_details(pnr)`
if the seating prelude needs `trip_details` specifically, per contrail's note that
`journey_updates` FKs to `trip_details` not `passenger`) until non-empty or timeout — mirroring
`pnr_lifecycle.wait_for_passenger_row`/`wait_for_trip_details` exactly, just via this repo's
existing source abstraction instead of contrail's `aurora_adapter.query_dicts`.

## Base template: pnr + ticket only

Per the design doc's per-feed shape table, both feeds need only:

- **PNR** — same base PNR create shape as FD/SOC/ANC (traveler names, journey/segments, contact),
  minus the FDM legs and EMD.
- **Ticket** — the fare ticket (same shape as FD's `02_ticket_issue`).

No FDM (`*.xml` skd/delay legs), no EMD (`03_emd_issue.json`), no DDS pin. This is the simplest base
template shape of the seven feeds onboarded so far — a strict subset of FD's `pnr + tkt + fdm`.

## How it plugs into the generic seed engine

Per the design doc's 9-step engine (§Architecture), NC/SeatChange specialize step 6 (`prelude`) and
add the change event to step 4 (`mutable`); everything else is identical to a pure-CREATE feed:

1. **evaluate identity** — fresh env-specific PNR + today-relative date
   (`seed.scenario.flight_date_for`). NC/SeatChange cases are not disruption-timed, so `completed`
   (today-7d) is a reasonable default identity date unless a case's title implies otherwise (none
   currently do — see the case-count table's title survey).
2. **pick base template + variation** — `data/seed-templates/nc/` / `data/seed-templates/seatchange/`
   with `base.json` (pnr+tkt only, no FDM/EMD) + a `manifest.yaml`.
3. **rekey the id-family** — `pnr_id`/`PT-n`/`ST-n` (no `docnum` beyond the ticket; no EMD doc
   number).
4. **apply manifest mutations** — set traveler name (NC) or seat assignment (SeatChange) to the
   change's `to` value; this is the **real UPDATE's** target state, applied here on the manifest's
   mutable list so the same manifest renders both the CREATE-prelude body (field forced to `from`)
   and the real UPDATE body (field at `to`).
5. **gate** — test-safe locator/flight ranges (same as every other feed).
6. **run prelude — `create_prelude`:**
   - `revert_fields`: NC → `processedPnr.travelers[{n}].names[0].(firstName|lastName)` set to
     `change.from`; SeatChange → `processedPnr.products[{n}].seating.seats[0].number` set to
     `change.from`.
   - build the CREATE payload: single root `{eventType:CREATED, currentPath:""}` event, no
     `previousRecord`, reverted field — i.e. `pnr_lifecycle.synthesize_create_payload`, ported.
   - publish the CREATE (via `seed.kafka_seed`'s existing PNR-topic path — no new topic needed).
   - `wait_for`: NC → `{table: passenger, column: pnr_id}`; SeatChange → `{table: trip_details,
     column: pnr_id}` (seating's `journey_updates` FKs to `trip_details`, per contrail's note that
     the segment-status/seating/flight-number family all attach there, not `passenger`).
   - publish the real UPDATE: same locator/composite ids, the changed field at `to`, plus the
     UPDATE event (`{eventType:UPDATED, currentPath:"/travelers/{n}/names/{m}/firstName"}` or
     `.../seating`) and (for NC) the RPH/channel fields the detector routes on.
7. **publish** — the CREATE burst, settle, then the UPDATE burst, settle (two bursts, not one — this
   is the one place NC/SeatChange's engine plug-in differs procedurally from a pure-CREATE feed's
   single burst).
8. **pin DDS** — **skipped** (`dds: none` for both feeds).
9. **verify checkpoints** — per-feed auditor (`nc` / `seatchange`, not yet built — out of scope per
   the design doc, "Out of scope: Live per-feed checkpoint auditors beyond FD").

## `seed.scenario.change()` — landed, with a documented gap

`seed/scenario.py` now has:

```python
def change(uc, feed: str | None = None) -> dict | None:
    ...
```

- Returns `None` for non-UPDATE-feed cases (e.g. FD/SOC titles).
- Returns `{"kind": "name"|"seat", "from": None, "to": None}` for NC/SeatChange cases. `kind` is
  resolved from the `feed` hint when given (`"nc"` → `"name"`, `"seatchange"` → `"seat"` —
  reliable, since a case belongs to whichever feed's gap doc parsed it), else inferred from the
  case id prefix (`NameCorrection_*` / `SeatChange_*`) — with the caveat that the id prefix is
  wrong for one card (`SeatChange_TC049` in the **nc** doc; pass `feed="nc"` to sidestep it).

**Gap:** `from`/`to` are `None`, not the concrete old/new name or seat. Both gap docs' cards
narrate the concrete values only in the raw Gherkin step text (e.g. NameCorrection_TC001: "the
system should retrieve the booking for 'Sarah Chen'" ... "the user types 'Sara Chen'" ... "Final
Name Confirmation: ... First Name: Sara Last Name: Chen"), which lives under each card's
`<details class="orig"><div class="steps">` block. `catalog/parser.py` does not currently parse
that block into any `UseCase` field — only the `intbub` (`customer_intent`) and `row bot/user`
(`expected_transcript`, empty for both docs) blocks are captured. Filling `from`/`to` needs one of:

1. A parser extension that scrapes `<div class="stp kw-a">`/`<div class="stp kw-w">` step text and
   regex-extracts quoted name/seat pairs (fragile — free-text Gherkin, not structured data), or
2. A tabular dataset (`join_dataset`, FD's mechanism) with explicit `from`/`to` columns, joined the
   same way FD's `dataset:` field works today, or
3. The generic-seeder manifest supplying `from`/`to` as scenario-level constants per case (since the
   design doc's principle is "unique passenger name... per case" — a manifest could assign a
   deterministic name/seat pair per case id rather than parsing it out of prose).

Option 3 is the cheapest given the design doc's existing identity-formula mechanism
(`seed/engine.py`'s `{{ }}` templates) — no parser change required, and it fits the "PNR and
absolute flight date generated per-env at seed time" principle (the *specific* name/seat is already
synthetic per case, not read from the source PNR). This plan defers the choice to whoever builds
`data/seed-templates/nc/manifest.yaml` / `seatchange/manifest.yaml`; `change()`'s stub already
carries `kind` so the CREATE-prelude "does this case need one" gate (step 6 above) works today
regardless of which option fills `from`/`to`.

## Build steps (not yet done — this plan documents the path, does not implement it)

- [ ] Add `data/seed-templates/nc/{base.json (pnr+tkt), variations/, manifest.yaml}`.
- [ ] Add `data/seed-templates/seatchange/{base.json (pnr+tkt), variations/, manifest.yaml}`.
- [ ] Port `pnr_lifecycle.needs_create_prelude` / `synthesize_create_payload` into
      `seed/engine.py` (or a new `seed/prelude.py`) as feed-agnostic helpers keyed off the
      manifest's `prelude: create_prelude` block (`revert_fields` + `wait_for`).
- [ ] Add a `wait_for_row(src, pnr, table, timeout, poll)` helper against `seed/source.py`'s
      `AuroraSource`/`TripTracerSource` (mirrors contrail's `wait_for_passenger_row`/
      `wait_for_trip_details`, via this repo's existing source abstraction).
- [ ] Decide and implement `change()`'s `from`/`to` fill (see the three options above).
- [ ] Extend `seed/kafka_seed.py`'s `build_plan`/`seed` (or a thin NC/SeatChange-specific wrapper)
      to publish the CREATE burst, wait, then the UPDATE burst — two bursts per case instead of one.
- [ ] `nc` / `seatchange` checkpoint auditors (live; built when each feed is onboarded to a live env).

## Open items / grounding notes

- Both registries pass `validate_feed()` and `load_catalog()` today (67/67 cases each, confirmed by
  running `catalog.parser.load_catalog(load_feed("nc"))` / `..."seatchange")`) — no parser change
  was needed for this plan's deliverables.
- `judge.match_on` for both feeds is `[status]` only (no `system_code`/`amount` — there is no DDS
  verdict to match on, unlike FD/SOC/ANC).
- The design doc's shorthand for the seating change path ("products/N subType=SEATING") should be
  read as the CRT-verified `^/products/(\d+)/seating$` / `seating.seats[0].number` path documented
  in `pnr_lifecycle.py`, not a literal `subType` field — noted above so a future manifest author
  doesn't chase a field that doesn't exist in the detector's path guard.
