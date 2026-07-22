# Multi-feed Test Case Narrative — CRT PNR Pipeline

**Supersedes** `test_cases_narrative.md`. This version reasons across **five correlated Kafka topics** rather than one, so it covers integration behaviour that single-feed tests miss.

## Sources

Derived from 50k–100k-message samples pulled 2026-04-21:

| Topic | Records | Unique PNRs | Role |
|---|---:|---:|---|
| `DERIVED-PNR-EVENTS-CRT` | 100,000 | 4,485 | raw PNR lifecycle events (upstream of all PNR processing) |
| `TRANSFORMED-PNR-EVENTS-CRT` | 50,000 | 2,219 | same events → `journey_updates` table upserts |
| `EVENT-DETECTION-PNR-CRT` | 50,000* | 5,429 | higher-level trip model upserts (`trip`, `trip_details`, `bound`) |
| `RESULT-EVENT-DETECTION-CRT` | 50,000* | 4,628 | regime-classifier outcome: `bounds` + `regimes` (e.g. `APPR`) |
| `DERIVED-BAGGAGE-SMARTSUITE-EVENTS-CRT` | 50,000* | 133 | physical baggage events joined to PNR via `data.pnr` |

*hit end-of-log before reaching 50k

**Cross-topic coverage:** 14 PNRs appear in all 5 feeds; 1,144 appear in 4 feeds.

---

## Architecture: fan-out, not chain

```
                        ┌── TRANSFORMED-PNR  (→ INSERT journey_updates)
                        │     └── powers the raw change-log UI
DERIVED-PNR (raw) ──────┤
                        ├── EVENT-DETECTION  (→ INSERT trip/trip_details/bound)
                        │     └── owns the "trip" aggregate view
                        │
                        └── RESULT-EVENT     (← reads EVENT-DETECTION output)
                              └── regime classifier: bound.regime = APPR / INFL / etc.

DERIVED-BAGGAGE ───────► joined to trip view by data.pnr
    (SmartSuite)            (parallel physical-world stream)
```

Key property: **the three PNR transforms (TRANSFORMED-PNR, EVENT-DETECTION, RESULT-EVENT) fire in parallel on every upstream change**, not in a chain. A single DERIVED-PNR event produces 3–4 downstream records within ~200ms.

---

## Cross-feed invariants (apply to every multi-feed test)

| ID | Invariant | Evidence |
|---|---|---|
| X1 | **Fan-out fires within 500ms** of upstream event | `AQGXTA`: PNR_CREATION at 15:04:05.9 → TRANSFORMED at 15:04:20.8 (**14.8s**) → EVENT-DETECTION at 15:04:20.9 → RESULT at 15:04:21.05. First hop is slow (14s) — suggests TRANSFORMED-PNR is the bottleneck; DETECT and RESULT are tight. |
| X2 | **EVENT-DETECTION always precedes RESULT-EVENT** | Every pair observed had DETECT 50–150ms before RESULT. RESULT-EVENT is downstream of DETECT, not parallel. |
| X3 | **Baggage events correlate to PNR by `data.pnr`** — no bag-tag needed on the PNR side | Confirmed for all 133 baggage PNRs. |
| X4 | **`RESULT-EVENT` can emit `(no bounds)`** when classifier ran but no bound state changed | Common pattern after re-emissions (e.g., `AQGXTA` got 5× "no bounds" results after the initial MCI→YUL `APPR` bound was set). |
| X5 | **Baggage BAG_ACCEPTED heartbeats every 5-15 min per bag** | `CJ2ASJ` shows 100+ BAG_ITINERARY_CHANGED + BAG_ACCEPTED over 5 hours. This is physical bag scanner polling, not business events. |
| X6 | **Each baggage event triggers a DETECT+RESULT cycle** | Confirmed on `AWSY3I` and `AQGXTA`. Downstream trip state is re-evaluated on every bag scan. |
| X7 | **PNR can exist in EVENT-DETECTION/RESULT without appearing in DERIVED-PNR window** | 5,429 EVENT-DETECTION PNRs vs 4,485 DERIVED-PNR PNRs — the detection service retains state for longer than the raw feed window. |
| X8 | **`(no bounds)` RESULT responses are idempotent** | Same bound state → same null-result → safe to re-emit without customer impact. |

---

## Reference trace: PNR `AQGXTA` (full 5-feed journey)

Clean end-to-end example pulled from real production data. Traveler boarded in Winnipeg (YWG) for YWG→YUL.

```
  15:04:05   DERIVED-PNR       PNR_CREATION at AC Toronto desk (YYZAC002A)
  15:04:20   TRANSFORMED-PNR   INSERT journey_updates           (14s lag)
  15:04:20   EVENT-DETECTION   INSERT trip status=ACTIVE        (100ms after transform)
  15:04:21   RESULT-EVENT      bound YWG→YUL regime=['APPR']    (classifier: approaching)

  15:11:02   DERIVED-BAGGAGE   BAG_CREATED/ACCEPTED bag=…5758 at YWG
  15:11:15   EVENT-DETECTION   DETECT (re-eval on baggage)      (13s after bag)
  15:11:15   RESULT-EVENT      (no bounds — bound already APPR)
  15:11:42   DERIVED-BAGGAGE   BAG_CREATED bags 5759, 5760       (next 2 bags)
  15:11:45   EVENT-DETECTION   DETECT  
  15:11:45   RESULT-EVENT      (no bounds)
  15:12:14   DERIVED-BAGGAGE   BAG_CREATED bags 5761, 5762       (next 2)
  15:12:30   EVENT-DETECTION   DETECT
  15:12:30   RESULT-EVENT      (no bounds)

  15:28:06   DERIVED-BAGGAGE   BAG_ONLOADED bag=…5760            (loaded on aircraft)
  15:28:07   DERIVED-BAGGAGE   BAG_LOADED_ON_AIRCRAFT            (state change)
  15:28:15   EVENT-DETECTION   DETECT (re-eval: bag now on a/c)
```

Total: 43 events across 5 feeds in 25 minutes to track one passenger's booking + bag check-in + aircraft loading.

---

## Cross-feed test cases

All test cases below assume the cross-feed invariants above. Each names the feed(s) that must be asserted together.

### MF-1: Fan-out completeness

| Property | Assertion |
|---|---|
| **Given** | A new `DERIVED-PNR` message with `eventName=PNR_CREATION`, `data.version=1` |
| **When** | The pipeline runs for 30 seconds |
| **Then** | Exactly one `TRANSFORMED-PNR` record upserts `journey_updates` for that `(pnr, version)` |
|  | Exactly one `EVENT-DETECTION` record inserts `trip` for that `pnr` |
|  | Exactly one `RESULT-EVENT` record emits either bounds or `(no bounds)` |
| **Edge** | If only 2 of 3 downstream records appear within 30s, one of the transforms is lagging. Differentiate: if TRANSFORMED-PNR missing but DETECT/RESULT present, TRANSFORMED-PNR is the laggard (it often takes 14s per `AQGXTA`). If DETECT+RESULT missing, the detection service is down. |

### MF-2: Regime classifier correctness

| Property | Assertion |
|---|---|
| **Given** | A PNR with a segment departing > 24h from now |
| **When** | DERIVED-PNR → TRANSFORMED-PNR → EVENT-DETECTION fires |
| **Then** | RESULT-EVENT bound regime should NOT be `APPR` (that regime is for imminent departure) |
| **Given** | A PNR with a segment departing < 4h from now |
| **Then** | RESULT-EVENT bound regime MUST be `APPR` |
| **Edge** | Flight time change that pulls a bound from outside-APPR → inside-APPR window should produce a regime transition event. |

### MF-3: Baggage-triggered trip re-evaluation is bounded

| Property | Assertion |
|---|---|
| **Given** | A PNR with 5 bags in BAG_ACCEPTED state |
| **When** | Bag scanners re-emit BAG_ACCEPTED heartbeats every 10 min for 2 hours (12 heartbeats × 5 bags = 60 events) |
| **Then** | DETECT+RESULT cycles fire ≤ **20 times** (aggregated, debounced) rather than 60 |
| **Why** | Per invariant X5/X6, every bag event currently triggers full trip re-eval. At scale, this is expensive and produces 60 no-op RESULT-EVENT messages per PNR. Debouncing is required. |
| **Implementation** | In EVENT-DETECTION consumer: coalesce bag events within a 60s window per PNR before re-evaluating. |

### MF-4: Consistency under out-of-order arrivals

| Property | Assertion |
|---|---|
| **Given** | A PNR where DERIVED-PNR v4 (PNR_CREATION) arrives AFTER v2 events (SSR, CONTACT_ADDED) |
| **When** | All events are processed |
| **Then** | TRANSFORMED-PNR, EVENT-DETECTION, RESULT-EVENT all reflect the **same final state** regardless of DERIVED-PNR partition arrival order |
| **Method** | Consumers must buffer by PNR and reorder by `data.version` before fan-out, OR the fan-out must be idempotent per `(pnr, version, eventName)`. |
| **Real example** | `AWSY3I`: v2 events at 17:53:06, v4 PNR_CREATION 12s later. Pipeline should present a consistent v4-sealed state, not a partial v2-only state between 17:53:06 and 17:53:18. |

### MF-5: Baggage-PNR join survives PNR absence

| Property | Assertion |
|---|---|
| **Given** | A baggage event arrives (BAG_CREATED with `data.pnr=X`) but no PNR record for X has been seen yet |
| **When** | The baggage event is processed |
| **Then** | Either: (a) buffer until PNR lands, OR (b) emit a soft warning and retain the bag event in a separate store keyed by PNR |
| **Must not** | Drop the baggage event |
| **Real example** | `CJ2ASJ` — baggage appeared 5 days before the DERIVED-PNR window; the DETECT/RESULT records still exist, meaning the trip view persists even when raw events rotate out of the retention window (invariant X7). |

### MF-6: Bag itinerary churn detection

| Property | Assertion |
|---|---|
| **Given** | A single bag (`bagTag=X`) emits >10 `BAG_ITINERARY_CHANGED` events in <15 minutes |
| **When** | The pattern is observed |
| **Then** | An alert fires: "bag re-routing storm" |
| **Why** | `CJ2ASJ` bag `0014969329` showed this pattern for 5+ hours. Either a real mis-connection cascade (needs ops attention) or a sync loop (needs engineering fix). Either way, worth paging. |
| **Threshold** | `bag_itinerary_changes_per_bag_per_15min > 10` → WARN. `> 30` → PAGE. |

### MF-7: Heartbeat vs. real event classification

| Property | Assertion |
|---|---|
| **Given** | Two consecutive BAG_ACCEPTED events for the same bag |
| **When** | Both events have identical `bagFlightLegs` data |
| **Then** | The second is a heartbeat — do not produce customer-facing output |
| **Given** | Two consecutive BAG_ACCEPTED events where the second has different `bagFlightLegs` |
| **Then** | The second is a real event (routing changed) — produce downstream signal |
| **Why** | BAG_ACCEPTED is re-emitted every 5-15 min. Downstream must distinguish real state changes from scanner heartbeats. |

### MF-8: DETECT/RESULT pair atomicity

| Property | Assertion |
|---|---|
| **Given** | Any EVENT-DETECTION record for PNR X |
| **When** | 5 seconds elapse |
| **Then** | A matching RESULT-EVENT record for PNR X must exist |
| **Alert** | If EVENT-DETECTION produces but no RESULT-EVENT follows within 5s, the regime classifier is broken or slow. |

### MF-9: Transform lag budget

| Property | Assertion |
|---|---|
| **Given** | A DERIVED-PNR event at ts_ms = T |
| **When** | The transformed record lands in TRANSFORMED-PNR at ts_ms = T' |
| **Then** | T' - T ≤ 30 seconds (p99) |
| **Observed** | AQGXTA: 14.8s. AWSY3I: 12s (v2→v4 gap, but within same transform batch). This is already at the edge of budget. |
| **Alert** | If p99 lag exceeds 60s, the TRANSFORMED-PNR writer is falling behind. |

---

## Scenario-level cross-feed assertions

For each single-feed scenario from `test_cases_narrative.md`, here's what **other feeds** should show:

### S0 Creation-only (no downstream activity expected)

- **TRANSFORMED-PNR**: exactly one INSERT journey_updates record.
- **EVENT-DETECTION**: one INSERT trip (status=ACTIVE), plus INSERT trip_details.
- **RESULT-EVENT**: one record with bound regime per promised segment (often `APPR` if near-term, otherwise null regime).
- **DERIVED-BAGGAGE**: none (no check-in yet).

### S2 Rebooking

- **TRANSFORMED-PNR**: one record per SEGMENT_REMOVED and one per SEGMENT_ADDED within the same logical version.
- **EVENT-DETECTION**: UPDATE trip_details (new itinerary), DELETE + INSERT bound (old bound removed, new bound added).
- **RESULT-EVENT**: new bound regime for the replacement. If the new departure is > 24h out, regime changes from APPR → null.
- **DERIVED-BAGGAGE**: if bags were checked, BAG_ITINERARY_CHANGED events fire as the bag re-tags to the new route.

### S3 Cancellation

- **TRANSFORMED-PNR**: DELETE / UPDATE journey_updates.
- **EVENT-DETECTION**: UPDATE trip status=CANCELLED (or DELETE).
- **RESULT-EVENT**: emit `(no bounds)` or a specific CANCELLED regime.
- **DERIVED-BAGGAGE**: if bags were already loaded (BAG_LOADED_ON_AIRCRAFT), a BAG_OFFLOADED event *must* follow; ground-handling must receive it.

### S12 Flight operational update

- **TRANSFORMED-PNR**: UPDATE journey_updates with new segment times.
- **EVENT-DETECTION**: UPDATE bound with new scheduled times.
- **RESULT-EVENT**: regime may transition (e.g., INFL = in-flight → LANDED if status update says "Landed").
- **DERIVED-BAGGAGE**: BAG_POSITIONED_ON_FLIGHT_LEG if re-attached to new leg.

---

## Operational findings (not test cases)

1. **4 topics are retention-truncated to empty**: `DERIVED-TKT-EVENTS-CRT` (HWM=2.2M), `TRANSFORMED-TKT-EVENTS-CRT`, `DERIVED-CM-EVENTS-CRT`, `FLIGHT-CHANGE-INVOL-CRT` (HWM=5). They have valid metadata and healthy leaders, but log-start-offset equals log-end-offset — all messages aged out, producer has gone quiet. This matches the cost-parked ECS services observed in the architecture inventory. **Action:** confirm with owning teams whether these topics should be retired or whether producers are supposed to be running.

2. **`FLIGHT-CHANGE-VOL-CRT` has 3 live messages, one of which is an error** (`systemErrorCode=500` from `dbaas-rebooking-vol-sf`). The voluntary rebooking engine is barely used in this window. Retention hasn't fired yet because the topic is too quiet.

3. **Baggage retention is long** — the `CJ2ASJ` bag events span 5+ days (2026-04-16 onward) whereas the DERIVED-PNR window is ~24 hours. Bag events survive longer than raw PNR events in this cluster.

4. **EVENT-DETECTION retains more PNRs than DERIVED-PNR in a given window** (5,429 vs 4,485). This is expected because DETECT records outlive the source events that produced them (invariant X7).

---

## How to run this analysis

```bash
# Pull current samples (adjust sizes as needed)
./pull_topic.sh DERIVED-PNR-EVENTS-CRT                 100000  pnr.ndjson
./pull_topic.sh TRANSFORMED-PNR-EVENTS-CRT             50000   corr/TRANSFORMED-PNR-EVENTS-CRT.ndjson
./pull_topic.sh EVENT-DETECTION-PNR-CRT                50000   corr/EVENT-DETECTION-PNR-CRT.ndjson
./pull_topic.sh RESULT-EVENT-DETECTION-CRT             50000   corr/RESULT-EVENT-DETECTION-CRT.ndjson
./pull_topic.sh DERIVED-BAGGAGE-SMARTSUITE-EVENTS-CRT  50000   corr/DERIVED-BAGGAGE-SMARTSUITE-EVENTS-CRT.ndjson

# Cross-feed analysis with top-5 auto-selected traces
./analyze_correlated.py corr/ --trace-top 5

# Single-feed scenario analysis (test_cases_narrative.md generator)
./analyze_pnr.py pnr.ndjson
```

## Deliverables

Working directory contains:

| File | Purpose |
|---|---|
| `pull_topic.sh` | Generalized kcat puller for any CRT topic |
| `analyze_pnr.py` | Single-feed scenario classifier (S0–S14 buckets) |
| `analyze_correlated.py` | Cross-feed correlator: coverage, journeys, per-PNR traces |
| `corr/corr50k.coverage.csv` | Per-topic stats + cross-topic coverage histogram |
| `corr/corr50k.journeys.csv` | One row per PNR: event counts per feed, time span |
| `corr/corr50k.trace_<PNR>.txt` | Time-ordered cross-feed trace for specific PNRs |
| `test_cases_narrative.md` | Single-feed scenario catalog (S0–S14) |
| `test_cases_v2_multifeed.md` | This document (cross-feed catalog) |
