# SeatChange seed template

**Mechanism: an UPDATE feed — CREATE-prelude, then the real seating-change UPDATE.**

Unlike FD/SoC/ANC/BookingChange (all pure CREATE, `message_kind: create`), SeatChange's registry
(`core/registry/feeds/seatchange.yaml`) declares `message_kind: create+update`. The thing under
test is a **change to an existing booking** — a seat assignment changed — not the booking itself.
See `docs/superpowers/plans/2026-07-17-nc-seatchange-seed.md` for the full design.

## Why a CREATE-prelude

A bare seating UPDATE on a fresh (never-seen) locator produces **no Aurora write**: `SeatingDetector`
emits `SEATING_UPDATED`, but the downstream `journey_updates` INSERT is FK-blocked — there is no
parent `trip_details` row yet (unlike the name-change family, seating's `journey_updates` row FKs to
`trip_details`, NOT `passenger`). Worse, a single PNR message can either **create** the PNR or fire a
per-element **change** detector, never both (`PNRCreationDetector` short-circuits `SeatingDetector`
the moment it fires on a root CREATE). So the seed path needs **two Kafka messages**, not one:

1. a synthetic **CREATE** — the SAME booking body, but with `seating.seats[0].number` reverted to a
   clearly different pre-change seat (14C, per contrail's proven SCS-01 baseline) — so
   `PNRCreationDetector` ingests the PNR and the `trip_details` row materializes;
2. the real **seating-change UPDATE** — the case's actual to-seat, `bookingSource`, the window
   (`NON_VOID`), and the `eligible` flag.

This two-message mechanism is `seed/feeds/prelude.py` — this framework's port of contrail's
proven `pnr_lifecycle.py` (`needs_create_prelude`, `build_create_payload`, `wait_for`). See that
module's docstring for the CRT-verified evidence and the exact detector path
(`^/products/(\d+)/seating$`, reverting `seating.seats[0].number` — NOT a `subType` discriminator,
despite the design doc's "products/N subType=SEATING" shorthand).

## What this base template carries

`base/` is the **pnr + ticket** family only — NOT the FD pnr + ticket + **FDM** trio (no disruption)
and NOT ANC's pnr + ticket + **EMD** family (no purchased ancillary). Same simplest-base shape as
NC, with one addition: `products[0]` carries a `seating` block (sibling to `airSegment`) so the base
booking already HAS a pre-existing seat assignment for the prelude to revert:

| file | role |
|------|------|
| `01_pnr.json` | the booking (copied from `data/fd-templates/base_appr`, `products[0]` extended with `seating.seats[0].number = "14C"`) |
| `02_ticket.json` | the fare ticket (copied from `base_appr`) |
| `meta.json` | identity + the CREATE-prelude's `prelude` block (detector path, `revert_fields`, `wait_for` table) |

No FDM XML (no disruption leg), no EMD, no DDS pin — `seatchange.yaml` sets `dds: none`; there is no
compensation/refund verdict to pin, only whether the seat-selection flow completed (see
`seed/feeds/seatchange_outcome.py`).

### The `prelude` block in `meta.json`

```json
"prelude": {
  "detector_path": "^/products/(\\d+)/seating$",
  "revert_fields": {"processedPnr.products[0].seating.seats[0].number": "14C"},
  "wait_for": {"table": "trip_details", "column": "pnr_id"}
}
```

`revert_fields` is written in the same dotted/`[n]` path syntax `seed.engine.set_dotpath` already
uses for manifest mutations, and is consumed verbatim by
`seed.feeds.prelude.build_create_payload(payload, revert_fields)`. This base template's own seat
(14C) already **is** the CREATE-prelude's pre-change default — a per-case render (see "Status:
scaffold" below) would set the manifest's mutable seat to the case's real target (the UPDATE's
to-seat), and `build_create_payload` would revert `products[0].seating.seats[0].number` back to 14C
for the synthetic CREATE burst only, so the later real UPDATE is a genuine 14C→to-seat change.

**CAVEAT (also flagged in `seed/feeds/prelude.py`'s module docstring):** `seed/source.py`'s
`AuroraSource` has no dedicated `trip_details` probe today — only `trip()` (the `trip` table). The
`wait_for` step above proxies `"trip_details"` through `trip()` as the nearest available read; a true
`trip_details` probe needs a new `AuroraSource` method. This is an open item, not resolved here.

## Outcome / verdict

SeatChange has no systemCode and no `data-out` in the gap doc, so `catalog/parser.py` leaves every
SeatChange `UseCase.verdict` as `""`. `seed/feeds/seatchange_outcome.py` reads the REAL outcome
(`SEAT_CHANGED`/`PAYMENT_REQUIRED`/`DECLINED`/`LIVE_AGENT`/`NO_DETERMINATION`/`UNKNOWN`, matching
`seatchange.yaml`'s `judge.verdict_enum`) directly off each card's title + Gherkin "Then" checklist
in the raw gap-doc HTML — see that module's docstring for the method and its confidence caveats
(lowest confidence on Seat Map / conditional "if X else Y" Edge Cases cards). This is a best-effort
heuristic over free-text prose, not a validated ground truth.

## Status: scaffold

`seed/render.py`'s `render_case` copies `01_pnr.json`/`02_ticket*.json`/`*.xml` and does the
identity/name/route/flight/delay text-replace — it does **not** yet rewrite the `seating` block per
case, nor orchestrate the two-Kafka-burst CREATE-prelude sequence (render with the to-seat →
`build_create_payload` → publish CREATE → `wait_for` → publish the real UPDATE). Wiring SeatChange
through the generic engine needs both a renderer extension (seat rewrite) and the orchestrator
extension (two-burst publish). `seed/feeds/prelude.py` (the prelude mechanism) and
`seed/feeds/seatchange_outcome.py` (the outcome reader) are both fully offline-testable and ready
ahead of that wiring — see `docs/superpowers/plans/2026-07-17-nc-seatchange-seed.md`.
