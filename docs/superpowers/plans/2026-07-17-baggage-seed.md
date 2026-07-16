# BAGGAGE (Mid-Journey) Seed Plan

**Date:** 2026-07-17
**Status:** Grounded plan (registry landed; mechanism documented — separate lane)
**Feed registry:** `core/registry/feeds/baggage.yaml`
**Gap doc:** `data/gap-docs/baggage/Baggage_Miro_Gap_Analysis.html`

## What BAGGAGE is (and is NOT)

Baggage is the most divergent feed. It is **NOT a PNR create/update** and it does **NOT use the FD
Kafka/DDS path**. There is:

- **no FDM message** (no `pnr + ticket + fdm` trio),
- **no DDS pin** (`dds: none` in the seeder design doc's per-feed table),
- **no Aurora change-detector row** to seed.

Instead, baggage is a **live eligibility decision** made by a **baggage-rules API** that reads
**SmartSuite bag events**. The chat answers "where is my bag / am I owed anything" by querying the
current bag state, not by reading a pre-published claim record.

Case count (`catalog.parser.load_catalog`): **39 cases**, all `seed_pending`, all titled
(e.g. `UAT_TC001` = *delayed bag within 21 days, Air Canada last carrier, delayed bag report found*).

## Seed mechanism — SmartSuite bag events + baggage-rules API

The "seed" for a baggage case is a **stream of bag events** in SmartSuite, not a Kafka PNR message.
The event lifecycle (from the reference gap analysis):

- `BagReadyForLoading`
- `BagLoaded`
- `BagSeen`
- `BagMishandled` (delayed / lost / misrouted)

The **baggage-rules API** then evaluates eligibility live over those events plus contextual facts:

- days since the bag was mishandled (e.g. the **21-day** window in `UAT_TC001`),
- whether **Air Canada is the last carrier** (AC-vs-OAL responsibility),
- whether a **delayed-bag report** exists,
- delivery status.

Sub-flows in the gap doc's spine confirm this is routing over live state, not claim reading:
`BAG-01a/b` (claim category menu), `BAG-07 · ADD-108` (Live Baggage Tracking), `BAG-04 · ADD-104`
(delivery status, descoped), and `GLOB-20a · AD101` (pilfered/damaged bag → **Non-MVP** flow).

## Why it needs its own lane

The generic seed engine (design doc §Architecture) is built around: template → rekey PNR family →
publish to Kafka → (pin DDS) → verify Aurora checkpoints. **None of steps 3–8 apply to baggage.**
The design doc explicitly marks baggage as `(special) … none (own engine)` and schedules it last
("baggage (own bag-event/rules path)").

What a generic seeder needs to support baggage — a **separate lane**:

1. **A bag-event emitter** targeting SmartSuite (not the Kafka PNR topics) that can post an ordered
   `BagReadyForLoading → BagLoaded → BagSeen → BagMishandled` sequence for a test bag tag.
2. **Today-relative timestamps on the events** so the age-based rules fire correctly — the same
   `scenario_date()` idea, but applied to the **mishandle timestamp** (e.g. "within 21 days" =
   `today - N` with `N < 21`; "outside window" = `today - N` with `N > 21`). This is the baggage
   analogue of FD's temporal-intent → flight-date mapping.
3. **Contextual flags** per case: last-carrier = AC vs OAL, delayed-bag-report present/absent,
   delivery status. These come from the scenario, not from a PNR dataset.
4. **A settle-and-query step against the baggage-rules API** instead of a DDS pin — the verdict is
   read back live, not written.
5. **A `baggage` auditor** asserting: bag events ingested, baggage-rules eligibility matches the
   expected verdict, live-tracking status, and correct **Non-MVP handoff** for pilfered/damaged bags.

The `baggage.yaml` `verdict_enum` is therefore routing/tracking outcomes
(`TRACKED / DELIVERED / MISHANDLED / HANDOFF / …`), not compensation determinations, and
`checkpoints.areas` name the bag-event/rules/handoff assertions rather than PNR/DDS ones.

## Build steps (separate lane)

- [ ] SmartSuite bag-event emitter (offline stub first: render the event sequence + assert order).
- [ ] Mishandle-timestamp mapper: scenario window (e.g. `<21d` / `>21d`) → today-relative timestamp.
- [ ] Per-case context flags (last-carrier, report-present, delivery-status) from the scenario.
- [ ] baggage-rules API query client (LIVE; stubbed offline for golden tests).
- [ ] `baggage` auditor checkpoints (LIVE).

## Grounding notes

- No FD-style templates, no Kafka publish, no DDS — do **not** try to force baggage through the FD
  manifest path. The registry `columns` (`Bag tag`, `Bag event`, `Bag status`, …) are placeholders to
  satisfy the schema; the real inputs are the bag-event stream + context flags.
- All 39 cases are `seed_pending`; `system_code` = `—`, `verdict` empty (doc authored with
  `data-flow`, not `data-out`). Not a parse failure — the bag lifecycle lives in the case titles.
