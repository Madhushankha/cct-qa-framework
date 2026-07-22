# CCT scenarios

Declarative scenarios for driving synthetic PNR payloads through the full
CCT pipeline end-to-end (EMH → MirrorMaker2 → CCT MSK → Flink → DERIVED-PNR
→ TRANSFORMED-PNR → EVENT-DETECTION → EDS → RESULT-EVENT-DETECTION → Aurora).

Each scenario is a single JSON document that:
- **documents** the PNR lifecycle in human-readable form (identity, POS,
  passengers, segments, timeline of versions, expected downstream cascade);
- **drives** the rendering engine (`scripts/scenario_engine.py`) which
  produces the raw Kafka records ready to inject on
  `emh-dev.ALTEA-PNRDATA-UAT`.

The scenario file IS the source of truth. Any behaviour the engine can't
derive from it (e.g. detailed Amadeus internals like `automatedProcesses`,
`financialValues`, `fareElements`) is inherited from a **canvas** — a real
`processedPnr` captured from live data — so we don't have to model every
Amadeus field.

## Layout

```
scenarios/
├── README.md                                      ← this file
├── _canvas/                                       ← reusable processedPnr bases
│   └── pnr_creation_domestic_ac.json              captured from B45OZB v1
├── ZZTEST-2099-12-31-domestic-create-only.json    sentinel smoke-test scenario
├── B45OZB-2026-04-22.json                         v1-schema reference (pre-rewrite)
├── B45OZB-2026-04-22.raw-source.ndjson            the 34 raw records captured for B45OZB
└── B45OZB-2026-04-22.downstream-observed.ndjson   the 6 derived events that cascaded
```

Future scenarios follow the pattern `<PNR>-<booking_date>-<short-name>.json`
or, for captured-from-live references, `<PNR>-<booking_date>/` directories.

## Pipeline of operations

```
scenario.json ──┐
                │   scripts/scenario_engine.py render
                ▼
          raw events ndjson ──┐
                              │   (Phase 2 — not built yet)
                              ▼   scripts/publish_raw.py
                   kcat -P emh-dev.ALTEA-PNRDATA-UAT
                              │
                              ▼
              Flink / DERIVED-PNR / TRANSFORMED-PNR /
              EVENT-DETECTION / EDS / RESULT-EVENT-DETECTION
                              │
                              ▼   (Phase 2)
                   scripts/watch_downstream.py
                              │
                              ▼
              observed cascade vs expected_cascade
                   (assertions + coverage report)
```

## Scenario schema (v2)

All fields unless marked optional.

```jsonc
{
  "$schema_version": 2,
  "scenario_id":      "<unique-id>",         // stable key for this scenario
  "title":            "<one-line summary>",
  "description":      "<paragraph>",         // optional
  "canvas":           "_canvas/<file>.json", // relative to scenarios/ or the scenario file
  "contains_pii":     false,                 // flag for export/share tooling

  "identity": {
    "pnr":          "ZZTEST",                // 6 alphanumerics
    "booking_date": "2099-12-31",            // YYYY-MM-DD
    "type":         "PNR"                    // optional; default "PNR"
  },

  "point_of_sale": {
    "office_id":          "YYZAC02XY",
    "iata_number":        "00000001",
    "system_code":        "AC",
    "agent_type":         "AIRLINE",
    "agent_numeric_sign": "0001",
    "agent_initials":     "SC",
    "duty_code":          "RC",              // optional
    "agent_country":      "CA",
    "agent_city":         "YYZ"
  },

  "passengers": [
    {
      "type":          "ADT",                // ADT / CHD / INF
      "first_name":    "SIMULATED",
      "last_name":     "SENTINEL",
      "gender":        "UNKNOWN",            // UNKNOWN / MALE / FEMALE / U
      "date_of_birth": "1990-01-01",
      "email":         "sim@zztest.invalid", // optional
      "phone":         "16045550001",        // optional
      "passport": {                          // optional
        "number":           "SIM00001",
        "expiry":           "2040-01-01",
        "nationality":      "CAN",
        "issuance_country": "CAN",
        "gender":           "MALE"
      }
    }
  ],

  "segments": [
    {
      "carrier":                 "AC",
      "operating_carrier":       "AC",
      "flight_number":           "101",
      "operating_flight_number": "101",
      "origin":                  "YYZ",
      "destination":             "YVR",
      "dep_local":               "2100-01-15T10:00:00",
      "arr_local":               "2100-01-15T12:45:00",
      "dep_utc":                 "2100-01-15T15:00:00Z",
      "arr_utc":                 "2100-01-15T20:45:00Z",
      "booking_datetime":        "2099-12-30T14:30:00Z",
      "aircraft":                "789",
      "cabin":                   "Y",
      "status":                  "HK",
      "arrival_terminal":        "1"         // optional
    }
  ],

  "ticketing": {                             // optional; used by ticketing_added
    "issuance_local_date": "2099-12-30",
    "fare":  {"amount": "0.00", "currency": "CAD"},
    "ticket_numbers": ["0000000000001"]      // one per passenger; generated if missing
  },

  "timeline": [
    {
      "version":     0,                      // int; becomes processedPnr.version
      "at":          "2099-12-30T14:30:00Z", // ISO UTC; becomes lastModification.dateTime
      "action":      "bootstrap",            // see Actions below
      "description": "<human note>"          // optional
    },
    {
      "version":     1,
      "at":          "2099-12-30T14:30:01Z",
      "action":      "ticketing_added",
      "description": "Ticketing attached — this triggers PNR_CREATION downstream"
    }
  ],

  "expected_cascade": {                      // assertions for the watcher (Phase 2)
    "derived_pnr_events":         [{"eventName": "PNR_CREATION", "triggered_by_version": 1}],
    "transformed_pnr_queries":    [{"targetTable": "trip", "command": "INSERT"}, ...],
    "event_detection_pnr_queries":[{"targetTable": "trip"}, ...],
    "eds_result":  {"bounds_count": 1, "regimes_possible": []},
    "db_end_state": {"trip": {"rows": 1, "status": "ACTIVE"}, ...},
    "total_cascade_budget_ms": 30000
  },

  "classification":    {"primary_code": "S0", "primary_name": "Creation-only"},
  "tags":              ["synthetic", "sentinel", "smoke-test", "AC-native"],
  "comparison_keys":   {"shape_signature": "...", "carriers": [...], ...},
  "dimensions":        {"passenger_count": 1, "segment_count": 1, ...},
  "provenance":        {"canvas_derived_from": "...", "rendered_by": "..."}
}
```

### Timeline actions

| Action | Effect on processedPnr |
|---|---|
| `bootstrap` | Removes `ticketingReferences` — the pre-ticketing stub state (matches real-world v0 pattern observed for B45OZB). |
| `ticketing_added` | Builds a fresh `ticketingReferences` list — one entry per passenger, linked to each segment. Uses `scenario.ticketing.*` fields if provided, else placeholders. |
| `cancel_pnr` | Sets every segment's `airSegment.status` to `XX` (or `step.cancelled_status`). |
| `custom` | Only applies `step.overrides` (JSON-Pointer → value map; `__DELETE__` removes the pointer target). |

Extend by adding clauses in `apply_timeline_step()` in `scripts/scenario_engine.py`.

### Per-step `overrides` (all actions)

Escape hatch for anything the actions don't model. Map of JSON Pointers → values.
Special value `"__DELETE__"` removes the pointer target.

```jsonc
"overrides": {
  "/products/0/airSegment/status": "UN",                  // unconfirmed
  "/remarks": {"type": "collection", "collection": [...]},// add PNR-level remarks
  "/automatedProcesses/0/note": "__DELETE__"
}
```

## Running the engine

```bash
./scripts/scenario_engine.py validate \
    --scenario scenarios/ZZTEST-2099-12-31-domestic-create-only.json

./scripts/scenario_engine.py render \
    --scenario scenarios/ZZTEST-2099-12-31-domestic-create-only.json \
    --out /tmp/zztest.ndjson
# → produces one raw Kafka record per timeline step, same shape as
#   what kcat -C -t emh-dev.ALTEA-PNRDATA-UAT would pull
```

Between consecutive versions the engine auto-generates:
- `previousRecord` — RFC 6902 JSON-Patch from current state back to previous;
- `events.events[]` — COMPARISON events (CREATED/UPDATED/DELETED) derived from
  the forward JSON-Patch paths;
- a fresh `meta.triggerEventLog.id` per version (format: `hex32-hex16`).

## Authoring a new scenario

1. Pick a distinctive `identity.pnr` + `booking_date` so the pnr_id cannot collide
   with anything real. The sentinel prefix `ZZ*` is reserved for synthetic scenarios.
2. Choose a canvas under `_canvas/` that shares the structural shape you want
   (e.g. domestic single-pax vs international multi-pax). Add new canvases by
   capturing a real `processedPnr` with `kcat` and stripping the outer envelope.
3. Fill in `point_of_sale`, `passengers`, `segments`.
4. Design the `timeline`: start with `bootstrap` at v0, then the substantive
   versions with `ticketing_added` / `cancel_pnr` / `custom` steps as needed.
5. Declare `expected_cascade` — this is what the downstream watcher will assert.
6. Fill in the descriptive metadata (`classification`, `tags`, `comparison_keys`,
   `dimensions`) so the scenario is queryable alongside thousands of peers.
7. `./scripts/scenario_engine.py validate --scenario <file>` — confirm schema.
8. `./scripts/scenario_engine.py render --out /tmp/out.ndjson` — inspect
   generated records. Sanity-check: no canvas identifiers should leak
   (`grep -c B45OZB /tmp/out.ndjson` must be 0 if your canvas came from B45OZB).
9. Submit for review; once approved, publish (Phase 2).

## Raw-topic catalog

The scenario engine writes to `emh-dev.ALTEA-PNRDATA-UAT`. The other raw feeds
live in the same family — each mirrored from the EIP-side `emh-dev` cluster
via MirrorMaker 2 (`cct-shared-infra-crt-*FeedMskConnect-*` connectors). All
topics have `-UAT` and `-INT` tiers in CCT MSK; the CRT environment consumes
the `-UAT` tier.

| Domain | Raw topic (CRT-consumed) | Notes |
|---|---|---|
| PNR data | `emh-dev.ALTEA-PNRDATA-UAT` (25 partitions) | covered here |
| PNR correlation | `emh-dev.ALTEA-PNRCORR-UAT` (3p) | part of PNR pipeline |
| Tickets | `emh-dev.ALTEA-TKT-UAT` (21p) | **empty upstream** |
| Ticket correlation | `emh-dev.ALTEA-TKTCORR-UAT` (3p) | |
| Case mgmt | `emh-dev.ALTEA-CM-UAT` (2p) | |
| AACC | `emh-dev.ALTEA-AACC-UAT` (1p) | |
| FDM / flight ops | `emh-dev.EAI-FDM-UAT` (1p) | |
| Baggage | `emh-dev.BROCK-BAGGAGE-UAT` (1p) | SmartSuite |
| iCoupon | `emh-dev.DBASS-ICOUPON-UAT` (1p) | |
| StormX | `emh-dev.STORMX-HOTEL-COMPENSATION-UAT` (1p) | |
| Loyalty | `emh-dev.MULE-LOYALTY-GIGYA-CUSTPROFILE-UAT` (1p) | |
| iFly / balances | `emh-dev.IFLY-*-UAT`, `emh-dev.MULE-*BALANCEUPDATES-UAT` | |

All raw topics use **empty Kafka keys** (round-robin partition routing).
At-least-once emission is built into the EMH producer — every logical change
appears on 2+ partitions.

## Open work — Phase 2

- `scripts/publish_raw.py` — publish rendered ndjson to Kafka via kcat -P.
  Needs `--dry-run` as default, explicit `--live` to actually produce.
- `scripts/watch_downstream.py` — tail DERIVED-PNR / TRANSFORMED-PNR /
  EVENT-DETECTION / RESULT-EVENT-DETECTION and poll Aurora for N seconds after
  publish; compare observed cascade against `expected_cascade`; emit pass/fail
  + coverage report.
- Canvas library — add more canvases (international, multi-segment, codeshare,
  SSR-rich, group PNR, etc.) so scenarios have appropriate Amadeus bases.
- More timeline actions — `segment_added`, `segment_removed`, `passenger_added`,
  `passenger_name_change`, `ssr_added`, `contact_changed`, `flight_time_update`,
  etc.

Until Phase 2 lands, render-only is the supported workflow; nothing writes
to Kafka.
