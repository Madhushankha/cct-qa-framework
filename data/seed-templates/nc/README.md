# NC (Name Correction) seed template

**Mechanism: an UPDATE feed — CREATE-prelude, then the real name-change UPDATE.**

Unlike FD/SoC/ANC/BookingChange (all pure CREATE, `message_kind: create`), NC's registry
(`core/registry/feeds/nc.yaml`) declares `message_kind: create+update`. The thing under test is a
**change to an existing booking** — a passenger's name corrected — not the booking itself. See
`docs/superpowers/plans/2026-07-17-nc-seatchange-seed.md` for the full design.

## Why a CREATE-prelude

A bare name-change UPDATE on a fresh (never-seen) locator produces **no Aurora write**:
`PassengerNameChangeDetector` emits its derived event, but the downstream `passenger_updates` INSERT
is FK-blocked — there is no parent `passenger` row yet. Worse, a single PNR message can either
**create** the PNR or fire a per-element **change** detector, never both (`PNRCreationDetector`/
`GroupPNRDetector` short-circuit the detector chain the moment either fires). So the seed path needs
**two Kafka messages**, not one:

1. a synthetic **CREATE** — the SAME booking body, but with `names[0]` reverted to a clearly
   different pre-change name (JOAO/MAIA, per contrail's proven default) — so `PNRCreationDetector`
   ingests the PNR and the `passenger` row materializes;
2. the real **name-change UPDATE** — the case's actual to-name, an RPH, and the channel/op_carrier
   routing fields several NC cases specifically test (ACV, OAL/Star Alliance, employee-travel OID
   prefixes, Non-1A GDS — `NameCorrection_TC029`..`TC054`).

This two-message mechanism is `seed/feeds/prelude.py` — this framework's port of contrail's
proven `pnr_lifecycle.py` (`needs_create_prelude`, `build_create_payload`, `wait_for`). See that
module's docstring for the CRT-verified evidence and the exact detector path
(`^/travelers/(\d+)/names/(\d+)/(firstName|middleName|lastName)$`).

## What this base template carries

`base/` is the **pnr + ticket** family only — NOT the FD pnr + ticket + **FDM** trio (no disruption)
and NOT ANC's pnr + ticket + **EMD** family (no purchased ancillary). This is the simplest base shape
of every feed onboarded so far:

| file | role |
|------|------|
| `01_pnr.json` | the booking (copied from `data/fd-templates/base_appr` — the PNR skeleton is feed-agnostic, same as anc's) |
| `02_ticket.json` | the fare ticket (copied from `base_appr`) |
| `meta.json` | identity + the CREATE-prelude's `prelude` block (detector path, `revert_fields`, `wait_for` table) |

No FDM XML (no disruption leg), no EMD, no DDS pin — `nc.yaml` sets `dds: none`; there is no
compensation/refund verdict to pin, only whether the correction flow completed (see
`seed/feeds/nc_outcome.py`).

### The `prelude` block in `meta.json`

```json
"prelude": {
  "detector_path": "^/travelers/(\\d+)/names/(\\d+)/(firstName|middleName|lastName)$",
  "revert_fields": {
    "processedPnr.travelers[0].names[0].firstName": "JOAO",
    "processedPnr.travelers[0].names[0].lastName": "MAIA"
  },
  "wait_for": {"table": "passenger", "column": "pnr_id"}
}
```

`revert_fields` is written in the same dotted/`[n]` path syntax `seed.engine.set_dotpath` already
uses for manifest mutations, and is consumed verbatim by
`seed.feeds.prelude.build_create_payload(payload, revert_fields)`. The base template's own
`names[0]` (MARA/OKONKWO) is the CREATE-prelude's OWN placeholder identity, not the pre-change
value — a per-case render (see "Status: scaffold" below) would first rewrite MARA/OKONKWO to the
case's real target name (the UPDATE's to-name), THEN `build_create_payload` reverts `names[0]` to
JOAO/MAIA for the synthetic CREATE burst only, so the later real UPDATE is a genuine transition.

## Outcome / verdict

NC has no systemCode and no `data-out` in the gap doc, so `catalog/parser.py` leaves every NC
`UseCase.verdict` as `""`. `seed/feeds/nc_outcome.py` reads the REAL outcome
(`CORRECTED`/`DOCS_REQUIRED`/`NOT_ELIGIBLE`/`LIVE_AGENT`/`NO_DETERMINATION`/`UNKNOWN`, matching
`nc.yaml`'s `judge.verdict_enum`) directly off each card's title + Gherkin "Then" checklist in the
raw gap-doc HTML — see that module's docstring for the method and its confidence caveats. This is a
best-effort heuristic over free-text prose, not a validated ground truth.

## Status: scaffold

`seed/render.py`'s `render_case` copies `01_pnr.json`/`02_ticket*.json`/`*.xml` and does the
identity/name/route/flight/delay text-replace — it does **not** yet orchestrate the two-Kafka-burst
CREATE-prelude sequence (render with the to-name → `build_create_payload` → publish CREATE → `wait_for`
→ publish the real UPDATE). Wiring NC through the generic engine needs that renderer/orchestrator
extension. `seed/feeds/prelude.py` (the prelude mechanism) and `seed/feeds/nc_outcome.py` (the outcome
reader) are both fully offline-testable and ready ahead of that wiring — see
`docs/superpowers/plans/2026-07-17-nc-seatchange-seed.md`.
