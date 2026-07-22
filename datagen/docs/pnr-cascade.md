# PNR Cascade — Kafka topic flow (CRT)

How a single PNR event traverses the CCT pipeline. Validated against live AWS as documented in `LEARNINGS.md` §4–§7, §12 (raw-feed ingest), and §6.6 (gap-day analysis). GitHub renders the diagram inline.

```mermaid
flowchart TB
  classDef topic fill:#fff8e1,stroke:#f9a825,color:#000
  classDef proc fill:#e3f2fd,stroke:#1976d2,color:#000
  classDef sink fill:#e8f5e9,stroke:#388e3c,color:#000
  classDef src fill:#fce4ec,stroke:#c2185b,color:#000
  classDef issue fill:#ffebee,stroke:#c62828,color:#000
  classDef ext fill:#f3e5f5,stroke:#7b1fa2,color:#000

  %% ───────── Upstream EMH (EIP account, UAT tier) ─────────
  subgraph EIP["EIP account · EMH MSK (UAT tier)"]
    direction LR
    EMH1["ALTEA-PNRDATA-UAT"]:::src
    EMH2["ALTEA-PNRCORR-UAT"]:::src
    EMH3["ALTEA-TKT-UAT<br/>⚠ no upstream production"]:::issue
    EMH4["ALTEA-TKTCORR-UAT"]:::src
  end

  %% ───────── CCT MSK · mirrored raw topics ─────────
  subgraph CRTM["CCT MSK ac-cct-msk-crt-cac1 · stage 1 (mirror)"]
    direction LR
    MIR1["emh-dev.ALTEA-PNRDATA-UAT"]:::topic
    MIR2["emh-dev.ALTEA-PNRCORR-UAT"]:::topic
    MIR3["emh-dev.ALTEA-TKT-UAT"]:::topic
    MIR4["emh-dev.ALTEA-TKTCORR-UAT"]:::topic
  end

  EMH1 -- MirrorMaker2 --> MIR1
  EMH2 -- MirrorMaker2 --> MIR2
  EMH3 -. no flow .-> MIR3
  EMH4 -- MirrorMaker2 --> MIR4

  %% ───────── S3 archive (parallel branch from mirrored topics) ─────────
  S3LIVE[("s3://cct-data-feeds-crt/pnr/<br/>emh-dev.ALTEA-PNRDATA-UAT/year=…<br/>30-day TTL · 1 file per msg")]:::sink

  MIR1 -. S3SinkConnector<br/>cct-shared-infra-crt-PNRFeedMskConnectS3-* .-> S3LIVE
  MIR2 -. S3SinkConnector .-> S3LIVE

  %% ───────── Historical replay path ─────────
  SNOW[(Snowflake EDW_UAT<br/>CCT_TRIPTRACER_HISTORICAL)]:::ext
  GLUE["Glue · cct-pnr-historical-migration-job-crt<br/>(checkpointed in SSM)"]:::proc
  S3HIST[("s3://cct-historical-data-feeds-crt/pnr/<br/>no TTL · per-PNR JSON")]:::sink
  RPLY["PNR-REPLAY-CRT"]:::topic
  RPLYI["PNR-REPLAY-INT"]:::topic

  SNOW --> GLUE --> S3HIST -. MSK Connect S3 Source .-> RPLY
  S3HIST -. .-> RPLYI

  %% ───────── Flink change-detector ─────────
  FLK{{"Flink MSF · cct-pnr-crt (RUNNING, v6)<br/>change-detector — emits eventNames<br/>twin: cct-pnr-historical-crt, cct-pnr-etl-crt"}}:::proc

  MIR1 --> FLK
  MIR2 --> FLK
  RPLY --> FLK

  %% ───────── DERIVED ─────────
  DER["DERIVED-PNR-EVENTS-CRT<br/>1 partition · HWM 87M+ · at-least-once<br/>key = {PNR}-YYYY-MM-DD<br/>eventName ∈ {PNR_CREATION, SEGMENT_*, SSR_*,<br/>CONTACT_*, REMARK_*, KEYWORD_*, SEATING_*,<br/>FLIGHT_TIME_UPDATE, SEGMENT_STATUS_UPDATE, …}<br/>⚠ also carries OAG_STATUS (.value-wrapped) — ~63% of records"]:::topic

  FLK --> DER

  %% ───────── Chain A — materialization to Aurora ─────────
  TRX_A["transformer-service-pnr-crt (ECS Fargate)"]:::proc
  TRA["TRANSFORMED-PNR-EVENTS-CRT<br/>DB-upsert-query payload<br/>~14s p99 lag from DERIVED"]:::topic
  ING["ingestion-service-pnr-crt (ECS Fargate)<br/>INSERT…ON CONFLICT DO NOTHING<br/>23503 → fk-queue · 23505 absorbed silently"]:::proc

  DER --> TRX_A --> TRA --> ING

  %% ───────── Chain B — event detection cascade ─────────
  EDU["event-detection-updater (ECS)"]:::proc
  EVD["EVENT-DETECTION-PNR-CRT"]:::topic
  CHG["change-processor-service-pnr-crt (ECS)<br/>⚠ silent stall Apr 17–19 (LEARNINGS §12.6)"]:::issue
  PED["PROCESS-EVENT-DETECTION-PNR-CRT"]:::topic
  EDS{{"Event Detection Service<br/>(external rule engine)"}}:::ext
  RED["RESULT-EVENT-DETECTION-CRT<br/>bounds + regimes ∈ {APPR, INFL, …}"]:::topic

  DER --> EDU --> EVD --> CHG --> PED --> EDS --> RED

  %% ───────── Disruption detection (parallel) ─────────
  DPROC["PROCESS-DISRUPTION-DETECTION-CRT"]:::topic
  DDS{{"Disruption Detection Service"}}:::ext
  DRES["RESULT-DISRUPTION-DETECTION-CRT"]:::topic

  EVD -.-> DPROC --> DDS --> DRES

  %% ───────── Aurora sink ─────────
  subgraph AUR["Aurora PG · ac-cct-trip-tracer-rds-cluster-crt-cac1"]
    direction LR
    T1[("trip<br/>trip_details")]:::sink
    T2[("journey_updates")]:::sink
    T3[("passenger<br/>passenger_updates")]:::sink
    T4[("flight_segment")]:::sink
    T5[("eds_pnr_output<br/>eds_flight_output")]:::sink
    T6[("dds_pnr_output")]:::sink
  end

  ING --> T1
  ING --> T2
  ING --> T3
  ING --> T4
  RED --> T5
  DRES --> T6

  %% ───────── Read path (Lambda over the materialized DB) ─────────
  subgraph READ["Read path · Lambda reads materialized state"]
    direction LR
    LAM["cct-sp-getTrip-crt-get-trip (Lambda, nodejs20)<br/>queries RDS Proxy READER endpoint"]:::proc
    SP["cct-sp-api-crt<br/>POST /trip-tracer/search<br/>auth = JWT (CUSTOM)"]:::proc
    JN["ac-cct-journey-gateway-api-crt<br/>POST /trip-tracer/search<br/>auth = AWS_IAM (SigV4)"]:::proc
  end

  T1 -. .-> LAM
  T2 -. .-> LAM
  SP --> LAM
  JN --> LAM

  %% ───────── Customer-facing end-state topics ─────────
  subgraph CUST["End-state / customer-facing topics (downstream of detection)"]
    direction LR
    FCV["FLIGHT-CHANGE-VOL-CRT<br/>(3 msgs total)"]:::issue
    FCI["FLIGHT-CHANGE-INVOL-CRT<br/>(empty)"]:::issue
    CC["CABIN-CHANGE-CRT"]:::topic
    SC["SEAT-CHANGE-CRT"]:::topic
    NC["NAME-CORRECTION-CRT"]:::topic
    PER["PERSONA-EVENTS-CRT"]:::topic
  end

  RED -. drives notifications .-> CUST

  %% ───────── Source-feed DLQs ─────────
  subgraph DLQ["Source-feed DLQs (failed ingest at MirrorMaker layer)"]
    direction LR
    DLQ1["ALTEA-PNRDATA-CRT-DLQ"]:::issue
    DLQ2["ALTEA-CM-CRT-DLQ"]:::issue
    DLQ3["BROCK-BAGGAGE-CRT-DLQ"]:::issue
    DLQ4["DBASS-ICOUPON-CRT-DLQ"]:::issue
    DLQ5["EAI-FDM-CRT-DLQ"]:::issue
    DLQ6["STORMX-HOTEL_COMPENSATION-CRT-DLQ"]:::issue
    DLQ7["MULE-DAMAGEDBAGGAGE-CRT-DLQ"]:::issue
  end
```

## Legend

| Style | Meaning |
|---|---|
| 🟡 yellow | Kafka topic |
| 🔵 blue | Compute (ECS, Lambda, Flink job, Glue, MSK Connect) |
| 🟢 green | Sink (S3, Aurora table) |
| 🩷 pink | External / upstream system |
| 🟣 purple | External downstream system |
| 🔴 red | Operational concern (empty topic, gap, silent failure point) |

## Reading the diagram

1. **Solid arrows** are the production paths.
2. **Dotted arrows** are parallel branches: S3 archival, replay-source, downstream notification fan-out.
3. **Two parallel chains** fan out from `DERIVED-PNR-EVENTS-CRT`:
   - **Chain A** (materialization): `transformer → TRANSFORMED-PNR → ingestion → Aurora`
   - **Chain B** (detection): `event-detection-updater → EVENT-DETECTION → change-processor → PROCESS-EVENT-DETECTION → EDS → RESULT-EVENT-DETECTION → eds_*_output`
4. **Read path** is decoupled — both `cct-sp-api-crt` (JWT) and `ac-cct-journey-gateway-api-crt` (SigV4) front the **same Lambda**, which queries the materialized state from Aurora's reader endpoint. No live Kafka consumption from the read side.
5. **Risk markers (red):** the `change-processor` is the historical failure point (Apr 17-19 silent stall); `ALTEA-TKT-UAT` is empty upstream; `FLIGHT-CHANGE-INVOL-CRT` is empty (producer not wired); `FLIGHT-CHANGE-VOL-CRT` has only 3 messages total.

## Per-event end-to-end latency budget (validated)

| Hop | p99 budget | Source of evidence |
|---|---|---|
| `emh-dev.ALTEA-PNRDATA-UAT → DERIVED-PNR-EVENTS-CRT` | <5 s | Flink dashboard (cct-pnr-crt) |
| `DERIVED → TRANSFORMED-PNR` | ~14 s | Real measurement on `AQGXTA-2026-04-20` |
| `TRANSFORMED-PNR → journey_updates` | <1 s | `received_at - last_modified` on row write |
| `DERIVED → EVENT-DETECTION-PNR` | <2 s | (declared, needs probe) |
| `EVENT-DETECTION → RESULT-EVENT-DETECTION` | ~21 s end-to-end | `AQGXTA`: trip_created at 15:04:00, eds at 15:04:21 |
| **Cumulative `DERIVED → eds_pnr_output`** | **~21 s p99** | LEARNINGS X1 |

When this budget is broken, the change-processor is the most likely offender (precedent: Apr 17-19).

## Companion files

- `LEARNINGS.md` — full prose context for every node and edge in this diagram.
- `docs/architecture.md` — broader CCT account inventory.
- `scripts/analyze_pnr.py`, `scripts/analyze_correlated.py` — observability primitives that walk this cascade.
- `scenarios/` — synthetic test scenarios that ride this exact path.
