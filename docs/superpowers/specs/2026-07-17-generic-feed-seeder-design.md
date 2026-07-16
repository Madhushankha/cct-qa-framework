# Generic per-feed seeder — scenario-driven, manifest-based, all feeds

**Date:** 2026-07-17
**Status:** Design for review
**Supersedes:** the FD-only cloner/render path (kept working; folded into this engine as feed `fd`).

## Principle (confirmed with the user)

The **UAT gap doc defines scenarios, which are common to every environment.** A scenario is the
env-agnostic "what to test": temporal intent, delay/controllability, pax shape, expected verdict,
checkpoints. The **environment (INT/CRT/BAT) is a parameter**; the concrete **PNR and absolute
flight date are generated per-env at seed time**, never baked into the scenario. Only `{email,
phone}` is a runtime input.

So seeding = read the common scenario from the gap doc → generate an env-specific PNR + a
**today-relative** date from the scenario's temporal intent → inject `{email, phone}` → publish →
(pin DDS if the feed uses it) → verify checkpoints.

## What this fixes / adds vs today

- **Dates are correct by construction, today-relative, per scenario intent** (not one fixed date,
  not derived from amount): `Travel Completed → today-7d`, `Pending/72h → today-1d (≤72h)`,
  `Pre-Travel → today+Nd (future)`, `No Travel → today-7d + segment status UN`.
- **Per-case identity** from the gap doc: unique passenger name, route, delay minutes, delay code,
  controllability — all env-common scenario attributes, not from the CRT dataset.
- **UPDATE scenarios** (name change, seat change, booking change) work: they need a CREATE-prelude
  (a bare UPDATE on a fresh locator has no parent row for the change detector to FK to).
- **One engine for all feeds** (fd, soc, nc, anc, baggage, seatchange, bookingchange, nonmvp),
  replacing FD-specific cloning.

## Architecture (mirrors the proven contrail engine, framework-owned)

```
gap doc (scenarios, env-common) ─┐
                                 ├─▶ scenario model (per case: intent, delay, verdict, pax, ...)
env descriptor (INT/CRT/BAT) ────┘
                                 ▼
            ┌───────────────── generic seed engine ─────────────────┐
            │ 1 evaluate identity (fresh PNR, today-relative dates)  │
            │ 2 pick base template + variation (per feed manifest)   │
            │ 3 rekey the id-family (pnr_id/PT-n/ST-n/docnum)        │
            │ 4 apply manifest mutations (dot-path JSON / xpath XML) │
            │ 5 gate (test-safe locator/flight ranges)              │
            │ 6 run prelude (CREATE-prelude for UPDATE feeds)        │
            │ 7 publish (one burst) + settle                        │
            │ 8 pin DDS (feeds that use it) — verdict from scenario  │
            │ 9 verify checkpoints (per-feed auditor)               │
            └───────────────────────────────────────────────────────┘
```

### Feed registry
Each feed is declared, not coded:
```
FeedConfig:
  name: fd | soc | nc | anc | baggage | seatchange | bookingchange | nonmvp
  message_kind: create | create+update      # update feeds carry a change event
  templates_dir: data/seed-templates/<feed>/  # base.{json,xml} + variations/ + manifest.yaml
  id_kind: pnr_locator | flight_number | document_number
  rekey: id_family_prefix | literal_substring | none
  dds: none | compensation | soc | seat_refund | bag_refund   # which DDS array the verdict fills
  prelude: none | create_prelude(revert_fields=[...], wait_for={table,column})
  checkpoints: <per-feed auditor id>
```

### Manifest (per feed template dir), with today-relative date FORMULAS
```yaml
identity:
  $pnr:        "{{ fresh_pnr() }}"           # env-specific, test-safe range
  $flightDate: "{{ scenario_date() }}"        # resolves per scenario intent (see below)
  $first:      "{{ scenario.first }}"
  $last:       "{{ scenario.last }}"
mutable:
  - { path: "processedPnr.travelers[0].names[0].firstName", formula: "{{ $first }}" }
  - { path: "...departureAirport", formula: "{{ scenario.origin }}" }
  # UPDATE feeds add the change event (name/seat) here
```
`scenario_date()` maps the gap-doc temporal intent to a today-relative date:
`completed→today-7d · pending→today-1d · pre_travel→today+3d · no_travel→today-7d(status UN)`.

### Scenario model (parsed from the gap doc, env-common)
Per case: `{ id, feed, systemCode, verdict, regime, temporal_intent, delay_minutes, delay_code,
controllability, pax[], route, change:{kind, from, to} | null }`. `change` is populated only for
UPDATE scenarios (name/seat/booking) and drives the CREATE-prelude + the UPDATE event.

### CREATE-prelude (UPDATE feeds: nc, seatchange, bookingchange)
A bare UPDATE on a fresh locator produces no Aurora write (the change detector FKs to a parent that
doesn't exist, and PNR-creation detectors short-circuit). So for `change`-bearing scenarios the
engine first sends a CREATE built from the same body with the changed field **reverted to its
`from` value**, waits for the parent row (`passenger`/`journey`), then sends the real UPDATE with
the `to` value. Ported from contrail `pnr_lifecycle.py`.

### Per-feed shape (from the reference)
| feed | kind | files/messages | DDS |
|---|---|---|---|
| fd | create | pnr, tkt, fdm skd+delay | compensation |
| soc | create | pnr, tkt, fdm | soc (`socFlightEligibility`) |
| bookingchange | create | pnr, tkt, fdm (INVOL) | compensation (rebooking-offered) |
| anc | create | pnr, tkt, emd (+corr) | seat/bag refund (refund variants only) |
| nc | create+update | pnr, tkt; UPDATE name event | none |
| seatchange | create+update | pnr, tkt; UPDATE seating event | none |
| baggage | (special) | SmartSuite bag events → baggage-rules API | none (own engine) |
| nonmvp | none | reuses an existing PNR; chat routing only | none |

## Build order
1. **FD on the new engine** — scenario model + manifest + today-relative dates + DDS verdict
   (proves the engine, fixes the date/pending/pre-travel correctness for all 239).
2. **soc + bookingchange** — same CREATE+FDM+DDS shape, new manifests + verdict arrays.
3. **nc + seatchange** — the CREATE-prelude path (UPDATE feeds).
4. **anc** — EMD + refund DDS.
5. **baggage** (own bag-event/rules path), **nonmvp** (no seed) — last, different mechanisms.

## Testing (offline)
- Scenario parser: gap-doc case → scenario model (temporal intent, delay, change) per feed.
- `scenario_date()`: intent → today-relative date (completed/pending/pre_travel/no_travel), asserted
  against a fixed injected `now`.
- Manifest engine: identity eval, dot-path/xpath mutation, id-family rekey (golden per feed).
- CREATE-prelude: a `change` scenario emits CREATE(from-value) then UPDATE(to-value); wait-for shape.
- Per-feed golden: one rendered message per feed validates against its schema.

## Out of scope
- Live per-feed checkpoint auditors beyond FD (rebuild per feed as each is onboarded).
- baggage/nonmvp live flows (documented; built last).
