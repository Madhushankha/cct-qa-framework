# CRT Environment & PNR Pipeline — Learnings

This is the long-memory reference for anyone working in this repo. It captures
everything I figured out about the Air Canada CCT-CRT environment, its Kafka
pipeline, and how to operate in it, so nobody has to re-derive it.

---

## 1. Repository layout

```
fargate-tailscale-jumpbox/
├── .env                   Cloudflare + trip-tracer DB creds (NOT committed — rotate CF key)
├── README.txt             How the cloudflared Fargate bastion was set up
├── LEARNINGS.md           ← this file
├── scripts/               Automation (all executable, run from repo root)
│   ├── pull_pnr.sh        Specialised puller for DERIVED-PNR-EVENTS-CRT
│   ├── pull_topic.sh      Generalised puller for any CRT topic
│   ├── analyze_pnr.py     Single-feed scenario classifier (S0–S14)
│   └── analyze_correlated.py  Cross-feed correlator + per-PNR traces
├── data/                  Raw ndjson pulls + per-run CSV/JSONL reports
│   ├── pnr-*.ndjson       (DERIVED-PNR dumps, large — 10s to 100s of MB)
│   ├── pnr-*.csv/.jsonl   (analyze_pnr.py outputs, co-located with their input)
│   ├── *.ndjson.err       (kcat stderr — keeps forensic evidence of retention)
│   └── corr/              Correlated-topic pulls + cross-feed reports
│       ├── TRANSFORMED-PNR-EVENTS-CRT.ndjson
│       ├── EVENT-DETECTION-PNR-CRT.ndjson
│       ├── RESULT-EVENT-DETECTION-CRT.ndjson
│       ├── DERIVED-BAGGAGE-SMARTSUITE-EVENTS-CRT.ndjson
│       ├── FLIGHT-CHANGE-VOL-CRT.ndjson
│       └── corr*.csv, corr*.trace_<PNR>.txt
└── docs/                  Written artifacts
    ├── architecture.md            Full ca-central-1 account inventory (narrative)
    ├── inventory.csv              Flat resource inventory (1,033 rows)
    ├── test_cases_narrative.md    Single-feed scenario test catalog (S0-S14)
    └── test_cases_v2_multifeed.md Cross-feed test catalog (MF-1 to MF-9)
```

Scripts take explicit paths, so nothing is hard-wired to the layout. The one
non-obvious convention: `analyze_correlated.py` auto-discovers ndjson files in
both the given dir and its parent, which is why pointing it at `data/corr/`
also picks up `data/pnr-*.ndjson`.

---

## 2. AWS environment

| Item | Value |
|---|---|
| Account | `050752605169` (`AC-CCT-CRT`) |
| Region used | `ca-central-1` only |
| SSO permission set | `CCE-Developer` (role `AWSReservedSSO_CCE-Developer_bcda3673133cf83a`) |
| AWS CLI profile | `ac-cct-crt` |
| SSO login lifetime | default 8 h; role-session STS creds auto-refresh from it |
| VPC | `vpc-074002f57df8a6967`, CIDR `10.111.196.0/22` |
| Subnets | 6 private, across `ca-central-1a/b/c`, app+db tiers |
| Egress model | TGW-central to shared-services account `378463553233`; **no IGW/NAT/EIP in-account**. Outbound UDP to `*.argotunnel.com:7844` is blocked — that's why cloudflared must be pinned to `TUNNEL_TRANSPORT_PROTOCOL=http2` |
| Terraform repo hint | tag `tf:repo-name` identifies owning infra repos (e.g. `ac-cct-msk-infra-tf`) |
| Deploy model | GitHub Actions + Terraform + CDK. No CodePipeline/CodeBuild. |

### 2.1 Engineer access path (Cloudflare WARP → cloudflared → VPC)

Configured in the prior session. Summary:

- `arc75` Cloudflare Zero Trust team, tunnel `arc75-qa-agent` (id `5cca63d6-be91-4636-b270-ed67cfa7a853`).
- Tunnel runs as an ECS Fargate service (`arc75-qa-agent-cloudflared` on cluster `arc75-qa-agent`, task def `rev 3`).
- HTTP/2 transport (QUIC blocked by TGW egress).
- Task-def rev 3 adds sysctl `net.ipv4.ping_group_range=0 2147483647` for cloudflared ICMP proxy.
- Private-network route `10.111.196.0/22 → arc75-qa-agent`.
- WARP split-tunnel Exclude list has `10.0.0.0/8` replaced with 14 narrower prefixes carving out `10.111.196.0/22`. Effect: only the CRT VPC is tunneled; other 10.x LANs still bypass.
- Tenant prereqs for WARP enrollment (see `README.txt` for details): at least one login method enabled for WARP auth identity (One-time PIN is the cheapest), plus a Device Enrollment Allow rule matching your email. Without these, `/warp` returns "Enrollment request is invalid".
- **ICMP to private IPs does not work end-to-end** — cloudflared ICMP proxy is enabled but Cloudflare edge still returns "Destination Host Unreachable" for pings to the VPC. TCP works fully. Use `nc -vz HOST PORT` or SSH/SSM, never `ping`, as your smoke test.

### 2.2 Workloads observed

See `docs/architecture.md` for the full narrative. High-level:

- 4 ECS clusters (main CRT + customer-profile + trip-tracer + arc75-qa-agent)
- 41 ECS services, 167 Lambda functions
- 1 ALB (internal), no NLBs/CLBs
- 4 Aurora PG 17.4 clusters (8 instances, multi-AZ, encrypted)
- 5 DynamoDB tables
- 1 MSK cluster (focus of this doc)
- 82 SQS queues, 11 SNS topics, 3 EventBridge buses

**Cost-parked services (relevant to empty Kafka topics):** most main-cluster services are `desired=1, running=0` (askac, acpedia, claims-dashboard, case-mgmt, case-processor). Only `case-intake` and `rule-engine-platform` actually run. This is why several of the "ticket" and "case-management" Kafka topics are empty — their producers are turned off.

### 2.3 Hot security findings

Called out during discovery; logged here so they aren't forgotten:

1. **MSK is anonymous + plaintext.** Cluster `ac-cct-msk-crt-cac1` has `Unauthenticated.Enabled=true` and `ClientBroker=TLS_PLAINTEXT`. Anyone in-VPC (including any WARP-enrolled laptop) can read/write PNRs on port 9092 without credentials. This is how I pulled the PNR data; it is the real exposure. Enforce SASL/IAM (9098) and disable unauth access.
2. **Shared IAM execution role.** `ac-cct-crt-ecs-task-execution-role` is reused by every ECS service including the arc75-qa-agent bastion. It has `SecretsManagerReadWrite` — too broad. Workaround (SCP `p-w8p5eioi` blocks `iam:CreateRole`) means new roles can't be created in-account; scoped secrets policies should at least be inline on tasks.
3. **`Unauthenticated.Enabled` is a data exfil risk** especially combined with WARP: any enrolled engineer can `brew install kcat && kcat -b <broker>:9092 -C -t DERIVED-PNR-EVENTS-CRT` to stream customer PNRs. Verified empirically.
4. **Public-ingress SG rules** (9096/443 from `0.0.0.0/0`) on trip-tracer and customer-profile Fargate SGs — inert today because there's no IGW, not defence-in-depth.
5. **40 log groups have no retention** — VPC flow logs alone 24 GB.

### 2.4 Useful host: `kafka-client` EC2

- Instance `i-04ee64277a4a29f69`, private IP `10.111.198.144`.
- Tagged `ac-cct-kafka-client-sg-crt-cac1`.
- Runs as root under SSM. Pre-installed: Kafka CLI tools at `/home/ec2-user/kafka/kafka_2.12-3.6.0/bin/`, Java 22 (Corretto).
- SG `sg-049bed8299f3bc58b` allows `-1` (all protocols) from `10.0.0.0/8` inbound — wide open within the VPC.
- Reach via `aws ssm start-session --target i-04ee64277a4a29f69 --profile ac-cct-crt`.
- SSM is the fallback for Kafka work when WARP isn't available. For interactive Kafka inspection from a laptop, `kcat` via WARP is faster.

---

## 3. MSK Kafka cluster

| Item | Value |
|---|---|
| Cluster ARN | `arn:aws:kafka:ca-central-1:050752605169:cluster/ac-cct-msk-crt-cac1/64cccdaf-7baf-4cf9-9a69-7c0bd1839f58-4` |
| Version | 3.8.x, 3 brokers `kafka.m5.large` |
| Broker DNS (port 9092) | `b-{1,2,3}.accctmskcrtcac1.05hf7o.c4.kafka.ca-central-1.amazonaws.com` |
| Plaintext port | 9092 (unauth) |
| TLS | 9094 |
| SASL/SCRAM | 9096 |
| SASL/IAM | 9098 |

Both `kcat` and the kafka CLI can connect on 9092 with no auth via WARP. From a Mac, `brew install kcat` gives you everything you need.

---

## 4. Kafka topic landscape (what I observed in April 2026)

From an initial topic listing and empirical sampling:

### 4.1 Categories

| Category | Naming pattern | Role |
|---|---|---|
| Raw source DLQs | `ALTEA-*-DLQ`, `BROCK-*-DLQ`, `DBASS-*-DLQ`, `EAI-*-DLQ`, `STORMX-*-DLQ`, `MULE-*-DLQ` | Messages that failed ingest from partner/GDS feeds |
| Replay | `*-REPLAY-CRT` | Retained replay streams (PNR, TKT, CM, FDM, BAGGAGE, ICOUPON, STORMX, AACC) |
| Derived | `DERIVED-*-EVENTS-CRT` | First-pass parsed events from each feed |
| Transformed | `TRANSFORMED-*-EVENTS-CRT` | Normalised events, usually as DB upsert queries |
| Event detection | `EVENT-DETECTION-*`, `PROCESS-EVENT-DETECTION-*` | Higher-level business events derived from the raw streams |
| Result | `RESULT-EVENT-DETECTION-CRT`, `RESULT-DISRUPTION-DETECTION-CRT` | Classifier outputs (regimes, disruption signals) |
| Specific disruption | `FLIGHT-CHANGE-VOL-CRT`, `FLIGHT-CHANGE-INVOL-CRT`, `CABIN-CHANGE-CRT`, `SEAT-CHANGE-CRT`, `NAME-CORRECTION-CRT` | End-state topics for customer-facing events |
| MirrorMaker 2 | `emh-dev.*` | Replicated topics from another (`emh-dev`) cluster — UAT/INT/BAT envs |
| Customer | `CUSTOMER-PROFILE-EVENTS-CRT`, `PERSONA-EVENTS-CRT`, `CUSTOMER-PROFILE-HISTORICAL-EVENTS-CRT` | Customer profile state (mostly empty / low-volume) |
| Chat/CMP | `ac-cct-cmp-inbound-messages-crt`, `ac-cct-cmp-outbound-messages-crt` | CMP inbound/outbound chat messages |
| MSK-internal | `__amazon_msk_*`, `__consumer_offsets`, `__transaction_state` | Not user data |

### 4.2 Which topics actually have data (snapshot 2026-04-21)

Empirically verified via `kcat`:

**High volume, actively producing:**

| Topic | Approx HWM / Log |
|---|---|
| `DERIVED-PNR-EVENTS-CRT` | 87M events, ~12K new/day, **partition 0 only** (scaling bottleneck) |
| `TRANSFORMED-PNR-EVENTS-CRT` | retained, ~1.5M events |
| `EVENT-DETECTION-PNR-CRT` | ~100K retained |
| `RESULT-EVENT-DETECTION-CRT` | ~40K retained |
| `DERIVED-BAGGAGE-SMARTSUITE-EVENTS-CRT` | retained ~days, steady stream |
| `emh-dev.*` | active MirrorMaker replicas |

**Retention-truncated to empty (HWM > 0 but log-start = log-end, `_PARTITION_EOF` immediately):**

| Topic | Last HWM | Likely reason |
|---|---|---|
| `DERIVED-TKT-EVENTS-CRT` | 2,222,859 | producer (ticket service) cost-parked |
| `TRANSFORMED-TKT-EVENTS-CRT` | ~637K | same |
| `DERIVED-CM-EVENTS-CRT` | ~200K | case-mgmt service cost-parked |
| `FLIGHT-CHANGE-INVOL-CRT` | 5 | barely used — upstream detector not firing |
| `CUSTOMER-PROFILE-EVENTS-CRT` | ~30K | producer gone quiet |

**Tiny:**

- `FLIGHT-CHANGE-VOL-CRT` — **3 messages total**. One is an error from `dbaas-rebooking-vol-sf`. The voluntary rebooking engine is barely exercised.

---

## 5. The PNR pipeline in detail

### 5.1 Fan-out architecture

```
                            ┌── TRANSFORMED-PNR-EVENTS-CRT
                            │     (journey_updates DB upserts)
                            │
  DERIVED-PNR-EVENTS-CRT ───┤
  (raw PNR lifecycle)       ├── EVENT-DETECTION-PNR-CRT
                            │     (trip / trip_details / bound DB upserts)
                            │           │
                            │           ▼
                            │     EDS (Event Detection Service, rule engine)
                            │           │  business rules over data-change events
                            │           ▼
                            │     RESULT-EVENT-DETECTION-CRT
                            │     (EDS output: regimes APPR / INFL / … per bound)
                            │           │
                            │           ▼
                            │     trip-tracer.eds_pnr_output (DB upsert)
                            │
                            └── (other derived feeds, e.g. PROCESS-EVENT-DETECTION)
```

Key property: **TRANSFORMED-PNR and EVENT-DETECTION fan out in parallel off DERIVED-PNR; RESULT-EVENT is downstream of EVENT-DETECTION, not parallel to it.**

**EDS = Event Detection Service.** It's a rule engine that consumes data-change events (via `EVENT-DETECTION-PNR-CRT`) and applies business rules to infer *what may have happened* to a PNR — e.g. "flight is approaching" (`APPR`), rebooking, disruption. Its output is written back to trip-tracer through the `RESULT-EVENT-DETECTION-CRT` topic, which lands in the `eds_pnr_output` table. So the `eds_*` tables in the DB are rule-engine verdicts, not raw state. (The parallel `dds_*` tables + `RESULT-DISRUPTION-DETECTION-CRT` topic are the same pattern for a Disruption Detection Service.)

`DERIVED-BAGGAGE-SMARTSUITE-EVENTS-CRT` is a separate physical-world pipeline joined to PNRs by `data.pnr`. Each baggage event re-triggers a DETECT + RESULT cycle (this produces a lot of noise — see "Heartbeat vs real event" below).

### 5.2 Shapes by topic

All DERIVED-PNR events are emitted **at least once** (every logical event appears twice within ~1 ms with different UUIDs).

- **DERIVED-PNR-EVENTS-CRT**
  - Top-level envelope.
  - Key: `PNR-YYYY-MM-DD` (e.g. `AX32W9-2026-04-21`).
  - `payload.data.pnr` is the join key.
  - `payload.data.version` is a per-PNR monotonic version; multiple events share one version (one business transaction).
  - `payload.data.lastModification.pointOfSale.office.id` identifies origin: `YULAC*` = AC Montreal desk, `LON1A*` = Amadeus London, `IAHUA*` = United Houston, `NCE1A*` = Amadeus Nice, `MADID*` = Amadeus Madrid, `VIEOS*` = Austrian Vienna. System codes `AC` / `1A` / `UA` / `OS` / `F1`.
  - Event names: `PNR_CREATION`, `SEGMENT_ADDED/REMOVED/UPDATED`, `SPECIAL_SERVICE_REQUEST_ADDED/UPDATED`, `CONTACT_ADDED/REMOVED`, `REMARK_ADDED/REMOVED`, `SPECIAL_KEYWORD_ADDED/UPDATED/REMOVED`, `SEATING_ADDED/UPDATED`, `CODESHARE_OTHER_AIRLINE_ASSOCIATION`, `FLIGHT_TIME_UPDATE`, `FLIGHT_NUMBER_UPDATE`, `SEGMENT_STATUS_UPDATE`, `PASSENGER_NAME_CHANGE`, `GROUP_PNR`, `SPLIT_PNR_ASSOCIATION`.
  - **Not all records are PNR events.** About 63% of records in a 100k sample are `OAG_STATUS` flight-ops events from source-feed `SNOWFLAKE`, wrapped in `payload.value` with different shape. Any consumer has to branch on `payload.data.pnr` presence vs `payload.value.sourceFeed == "SNOWFLAKE"`.

- **TRANSFORMED-PNR-EVENTS-CRT**
  - Same events as DERIVED-PNR, but the payload is `{queries: [{command: INSERT, targetTable: journey_updates, values: {pnr, pnr_id, entity, entity_version, event_type, event_action, data, …}}]}`.
  - This is the "operational DB" form — ready to be replayed against the journey_updates table.
  - Upstream → TRANSFORMED lag is **~14 s** in observed samples (the slowest hop in the pipeline).

- **EVENT-DETECTION-PNR-CRT**
  - `{id: "PNR-DATE", queries: [...]}`. No `eventName`.
  - Upserts against higher-level tables: `trip`, `trip_details`, `bound`, and other aggregate models.
  - Each DERIVED-PNR write produces at least one DETECT record ~100 ms later.

- **RESULT-EVENT-DETECTION-CRT** — output of the **Event Detection Service (EDS)** rule engine.
  - `{eventMetadata:{trigger, entity, timestamp}, pnr, pnrId, bounds:[{boundRph, origin, destination, regimes:["APPR"/…], promisedSegments, actualSegments, originalSegments}]}`.
  - EDS consumes `EVENT-DETECTION-PNR-CRT`, evaluates business rules (e.g. "flight departs within N hours", "segments changed vs original"), and emits inferences here. `regimes`, `promised/actual/originalSegments` are rule-engine *verdicts*, not raw state.
  - **Regime codes observed:** `APPR` is **not** a time-windowed "imminent departure" flag — the empirical finding from Contrail's ZZTEST-2099-12-30 run (real run, Apr 2026) was that `APPR` fires for a PNR whose flight is in year 2100. Best current reading: `APPR` means **active pre-departure** — default regime for any future-dated booking, emitted once on creation and persisting until the flight departs. Other codes (likely `INFL` in-flight, `LANDED`, `COMPLETED`) remain unobserved; the transitions between them are time-driven by Flink/EDS rather than tied to a specific event.
  - `bounds` can be empty — RESULT re-fires on every DETECT even when nothing material changed. Expect lots of `(no bounds)` records. These are effectively no-ops but are not filtered out.
  - Ingestion writes these records back to `eds_pnr_output` / `eds_flight_output` in the trip-tracer DB (§6.3).

- **DERIVED-BAGGAGE-SMARTSUITE-EVENTS-CRT**
  - `payload.data.pnr` correlates to PNR pipeline.
  - `payload.data.bagTag` is the bag id, `bagId` is an internal id.
  - Event names: `BAG_CREATED`, `BAG_ACCEPTED`, `BAG_ITINERARY_CHANGED`, `BAG_ONLOADED`, `BAG_LOADED_ON_AIRCRAFT`, `BAG_POSITIONED_ON_FLIGHT_LEG`, `BAG_DELAYED_RECORD_CREATED`, `BAG_DELAYED_FORWARDED`.
  - **Heartbeat pattern:** `BAG_CREATED` and `BAG_ACCEPTED` for the same bag re-emit every 5–15 min even when nothing has changed. Consumer must distinguish heartbeats from real state changes (compare `bagFlightLegs`).
  - Bag itinerary churn (`BAG_ITINERARY_CHANGED` firing hundreds of times for one bag) is either a real mis-connection cascade or a sync loop — worth alarming on.

---

## 6. trip-tracer RDS (Aurora PostgreSQL) — Kafka consumer side

The materialised end-state of the PNR pipeline lives in an Aurora PG 17.4 cluster
reachable through the same WARP tunnel as the MSK brokers.

### 6.1 Connection

| Item | Value |
|---|---|
| Cluster endpoint | `ac-cct-trip-tracer-rds-cluster-crt-cac1.cluster-cxqe2wacy866.ca-central-1.rds.amazonaws.com` |
| Resolves to | `10.111.199.87` (in-VPC, tunneled via WARP) |
| Port | `5432` |
| Database | `trip-tracer` (hyphenated — always quote) |
| User | `dbadmin` |
| Creds | `.env` → `RDS_PGSQL_PASSWORD` (server uses plain password auth; SSL enforced by server — `TLSv1.3 AES_256_GCM`) |
| TLS | enabled at the server, no client config needed |

One-shot:

```bash
PGPASSWORD="$(grep RDS_PGSQL_PASSWORD .env | cut -d: -f2 | xargs)" \
  psql -h ac-cct-trip-tracer-rds-cluster-crt-cac1.cluster-cxqe2wacy866.ca-central-1.rds.amazonaws.com \
       -U dbadmin -d 'trip-tracer'
```

Or set `PG*` env vars for the session. WARP must be connected; `nc -vz 10.111.199.87 5432` should succeed first.

### 6.2 Schema: entity graph (32 tables, all in `public`)

FK-verified (every listed edge is a real foreign key):

```
trip (pnr_id PK)  ── 1:1 ──▶ trip_details (pnr_id PK)
                                  │
                                  ├─▶ journey_updates              (220k rows, ALL PNR events)
                                  ├─▶ passenger                    (37k)
                                  │       └─▶ passenger_updates    (87k, CONTACT/DOCUMENT/NAME/LOYALTY)
                                  ├─▶ flight_segment               (42k)
                                  ├─▶ special_service_request      (81k)
                                  ├─▶ baggage_updates, cm_bag_*
                                  ├─▶ emd, ticket_updates, ticket_emd
                                  ├─▶ eds_pnr_output, dds_pnr_output
                                  └─▶ stormx_*, icoupon_*, cld_*, cancelled_voucher   (ALL empty)

flight_leg (PK=flight_leg_id)  ── 1:N ──▶ flight_leg_updates       (separate ops stream,
                                                                     not triggered by PNR events)
eds_flight_output (standalone)
```

Primary keys are all `pnr_id` (e.g. `AX32W9-2026-04-21`) — the PNR code + booking date. The 6-char `pnr` alone is not unique (see §6.6 PNR reuse).

### 6.3 Kafka topic → DB table mapping

| Kafka topic | → | DB table(s) | Rows (snapshot) |
|---|---|---|---:|
| `TRANSFORMED-PNR-EVENTS-CRT` | → | `journey_updates` | 220,915 |
| `EVENT-DETECTION-PNR-CRT` | → | `trip`, `trip_details` | 23,479 / 23,479 |
| (travellers, from PNR) | → | `passenger`, `passenger_updates` | 36,808 / 87,339 |
| (SSR, from PNR) | → | `special_service_request` | 81,686 |
| (segments, from PNR) | → | `flight_segment`, `flight_leg`, `flight_leg_updates` | 42,379 / 880 / 11,552 |
| `TRANSFORMED-TKT-EVENTS-CRT` | → | `ticket`, `ticket_updates`, `emd`, `emd_updates` | 26k / 34k / 7k / 8k |
| `DERIVED-BAGGAGE-SMARTSUITE-EVENTS-CRT` | → | `baggage_updates`, `cm_bag_updates`, `cm_bag_group_updates` | 7.6k / 3.5k / 876 |
| `RESULT-EVENT-DETECTION-CRT` | → | `eds_pnr_output`, `eds_flight_output`, `dds_pnr_output` | 15k / 3.5k / 19 |
| stormx/icoupon/cancelled/cld feeds (all cost-parked) | → | corresponding `*_updates` tables | **0** |

### 6.4 Event normalisation (Kafka eventName → DB `journey_updates.event_type`)

`journey_updates.event_type` uses a more abstract vocabulary than Kafka eventNames:

| Kafka eventName | DB `event_type` / `event_action` |
|---|---|
| `SEGMENT_ADDED` / `SEGMENT_REMOVED` / `SEGMENT_UPDATED` | `SEGMENT` / `INITIAL`\|`ADDED`\|`UPDATED`\|`REMOVED` |
| `SPECIAL_SERVICE_REQUEST_ADDED` / `_UPDATED` | `SERVICE` / `ADDED`\|`INITIAL` |
| `SPECIAL_KEYWORD_ADDED` / `_UPDATED` / `_REMOVED` | `SPECIAL_KEYWORD` |
| `REMARK_ADDED` / `_REMOVED` | `REMARKS` / `ADDED`\|`REMOVED` |
| `SEATING_ADDED` / `_UPDATED` | `SEATING` / `SEATING_UPDATED` |
| `FLIGHT_TIME_UPDATE` | `FLIGHT_TIME` |
| `FLIGHT_NUMBER_UPDATE` | `FLIGHT_NUMBER` |
| `SEGMENT_STATUS_UPDATE` | `SEGMENT_STATUS` |
| `CODESHARE_OTHER_AIRLINE_ASSOCIATION` | `CODESHARE_OTHER_AIRLINE_ASSOCIATION` |
| `PNR_CREATION` | — (creates `trip` + `trip_details` rows; no `journey_updates` entry) |
| `PASSENGER_NAME_CHANGE` | (routed to `passenger_updates.attribute_type='NAME'`) |
| `SPLIT_PNR_ASSOCIATION` / `GROUP_PNR` | `SPLIT_PNR_ASSOCIATION` / `GROUP_PNR_UPDATE` |

Observed top event_types (from 220k rows of `journey_updates`): `LAST_MODIFICATION/UPDATED` (108k — metadata-only, fires on every change), `REMARKS/ADDED` (36k), `REGULATORY_CHECKS` (19k total), `SEGMENT/INITIAL` (9.5k), `SPECIAL_KEYWORD/ADDED` (5.3k), `SERVICE/INITIAL` (5.2k), `PNR_ASSOCIATION/ADDED` (4.7k), `CHECK_IN/UPDATED` (4.4k), `CODESHARE_OTHER_AIRLINE_ASSOCIATION/ADDED` (3.2k).

`journey_updates.entity` is a 3-value enum: `PNR`, `CM`, `AACC`. Three upstream domains multiplex into the same table.

### 6.5 Idempotency protection

Enforced via UNIQUE constraints — observed working for most streams:

| Table | Idempotency key | Dup groups in current data |
|---|---|---:|
| `journey_updates` | `(entity_id, event_type, event_action)` | **0** ✅ |
| `passenger_updates` | `(passenger_id, last_modified_event_log_id, attribute_type, attribute_action)` | **788** ❌ |
| `flight_leg_updates` | `(flight_leg_id, event_type, last_update)` | (not measured) |

**Known bug — `passenger_updates` NAME dedup:** all 788 duplicate groups are `attribute_type='NAME'` rows with `attribute_action IS NULL`. PostgreSQL treats NULL as distinct in unique constraints, so NAME changes from `PASSENGER_NAME_CHANGE` events — which are emitted at-least-once like all PNR events — accumulate duplicates because the producer doesn't set an action for NAME. Fix options:

1. Producer sets `attribute_action='ADDED'` for NAME (non-NULL → UNIQUE enforces).
2. `ALTER TABLE passenger_updates ADD CONSTRAINT uq_passenger_updates_idempotency UNIQUE NULLS NOT DISTINCT (passenger_id, last_modified_event_log_id, attribute_type, attribute_action);` (PG 15+).
3. Partial unique index: `CREATE UNIQUE INDEX … (passenger_id, last_modified_event_log_id, attribute_type) WHERE attribute_action IS NULL;`.

### 6.6 Operational gotchas

- **Cancellation has no dedicated status.** `trip.status` CHECK allows only `ACTIVE` or `INACTIVE`. Kafka's 31% S3-cancellation scenario maps to `INACTIVE` or `archive_date` — there is no `CANCELLED` bucket. If you're searching for cancellations, filter on `status='INACTIVE' OR archive_date IS NOT NULL`, not on a status=CANCELLED.
- **PNR reuse.** 23,480 `pnr_id` rows but only 22,457 unique `pnr` codes — 1,023 six-char PNR codes appear under multiple booking dates. Don't key anything by `pnr` alone.
- **Trips with zero segments.** 749 (3.2%) `trip` rows have no matching `flight_segment`. Matches the Kafka "creation-only" class — the segment data either lags, never arrived, or was removed before any segment event reached the DB.
- **Test data in production.** `AQGXTA` has passenger names PAXA/PAXB/PAXC TEST. Several S13 name-change PNRs from the same AC Montreal office (`YULAC00DC` / `YULAC0985`) carry masked-looking names (`"L IOERKW"`, `"QJY OZKMMS"`) — likely test bookings or masked data flowing through the live pipeline. Don't confuse test data for pipeline bugs when exploring.
- **Apr 18–19 2026 = zero trips created** — baseline is ~2,700/day. Almost certainly a pipeline outage, not a real booking drought. Still unresolved at time of writing; worth asking operations. Apr 17 was 66 (below baseline too); Apr 1–7 were single-digit / zero, but that's the seeding period before the DB went live.
- **Pipeline lag.** Freshness measured at ~5 min 37 s between wall clock and `MAX(journey_updates.received_at)`; last trip created ~13 min prior to the check. In other words: end-to-end Kafka→DB lag is well under 10 min when the pipeline is up.

### 6.7 API access path — two parallel entry points (validated 2026-04-23)

Trip-tracer has **no dedicated public REST API**, but two internal-only APIs now front the same `cct-sp-getTrip-crt-get-trip` Lambda with different auth models. Both are PRIVATE (VPCE-only) — no internet exposure.

**Service Proxy API — `cct-sp-api-crt` (id `lph92mkuvb`, created 2026-04-15):**

- **PRIVATE endpoint**, `disableExecuteApiEndpoint: true` (no default AWS URL), VPCE `vpce-07235cc34fac22811` only.
- **Custom domain:** `cct-service-proxy-crt.ac-cct-crt.cloud.aircanada.ca`.
- **Authorizer:** `JWTAuthorizer` (id `mkyn96`), REQUEST-type Lambda authorizer `cct-sp-infra-crt-jwt-authorizer`, reads `Authorization` header.
- **23 routes** in five auth tiers: 6 JWT-gated (`baggage-tracker/by-{id,pnr}`, `booking-change` + `/eligibility`, `customer-profile/search`, **`trip-tracer/search`**); 14 AWS_IAM-gated (all `flightstatus/*`, OTP flow, `idv/create-inquiry`, `notifications`, `get-contact-info`, `validate-login-token`, `case-management/discovery` GET + `{action+}` POST); 1 `ANY /case-management/{action+}` with auth `NONE` (likely CORS preflight catch-all — worth double-checking).
- **CDK stacks** (12, all `UPDATE_COMPLETE` as of 2026-04-22): `cct-sp-{infra,api,baggage,bookingChange,case,customer,dashboard,flightStatus,getTrip,notifications,stepUp,validateToken}-crt`.
- **JWT sessions** persisted in DDB `cct-sp-infra-crt-SessionJwtTableF35A45F5-*`.

**Journey API — `ac-cct-journey-gateway-api-crt` (id `crblgy3r29`, created 2026-04-22):**

- **PRIVATE endpoint**, same VPCE restriction, `disableExecuteApiEndpoint: false` (default URL usable from inside the VPCE).
- **No custom domain** yet — callers must hit `https://crblgy3r29-<vpce>.execute-api.ca-central-1.amazonaws.com/crt/…`.
- **No authorizers defined.** Every route uses `AWS_IAM` (SigV4).
- **6 routes** — a subset of SP: `POST /trip-tracer/search`, `POST /customer-profile/search`, `POST /booking-change`, `POST /booking-change/eligibility`, `POST /case-management/{action+}`, `ANY /case-management/{action+}`.
- **CFN stack `ac-cct-journey-gateway-api-crt`** contains ONLY the REST API + stage — zero Lambdas, zero authorizers. It's a thin alternate front door to SP's existing Lambdas.
- **Every `/trip-tracer/search` integration points to the same Lambda** as SP: `cct-sp-getTrip-crt-get-trip` (AWS_PROXY). The Lambda resource policy uses wildcard `*/*/*/*` so both APIs are allowed invokers.

**"Less restrictive" means: drops the JWT layer, not the network gate.** Both APIs are VPCE-only. Journey is easier for in-account service-to-service callers (Lambda / ECS tasks with IAM roles can call via SigV4 natively, no JWT round-trip through `cct-auth-service-crt`). Still internal-only at the network layer.

**Caller decision matrix:**

| Caller | Use | Why |
|---|---|---|
| External / interactive / UI (user JWT) | Service Proxy (`cct-sp-api-crt`) | JWT authorizer chain via `cct-auth-service-crt`, enforces user identity + step-up / OTP flow |
| In-account service (Lambda / ECS / Step Function) | Journey API (`ac-cct-journey-gateway-api-crt`) | SigV4 with caller's IAM role — no JWT round-trip |
| Engineer ad-hoc (debug / inspection) | Direct psql via WARP — bypasses both APIs (§6.1) | Not the prod read path |

**Backend (identical for both APIs):**

- Lambda `cct-sp-getTrip-crt-get-trip`: `nodejs20.x`, 128 MB, 29s timeout, in VPC, last modified 2026-04-22 16:05.
- Reads Aurora via the **RDS Proxy reader endpoint** (`ac-cct-trip-tracer-rds-proxy-crt-cac1-ro.endpoint….`) — reads don't lock the writer.
- Observability: OTel Application Signals + Dynatrace instrumented, 100% sampler.

**Gaps worth flagging:**

1. **Journey has no custom domain.** Callers hardcode the execute-api hostname + VPCE id. Add a Route 53 + ACM + base-path mapping for parity with SP.
2. **Journey has no usage plan / throttling.** If internal traffic ramps, add one.
3. **SP routes NOT mirrored to Journey:** baggage-tracker, flightstatus, otp, idv, notifications, validate-login-token, get-contact-info. Probably intentional (some are already IAM-gated on SP, so same auth either side — mirroring would only help if SP's JWT layer was being bypassed for some reason), but worth confirming intent with the team.
4. **`NONE` auth on `ANY /case-management/{action+}` (SP)** — stays suspicious even if it's CORS preflight. Worth a look.

### 6.8 Useful one-liners

```sql
-- Full lifecycle for a PNR across all child tables
SELECT 'journey'   AS kind, event_type, event_action, last_modified FROM journey_updates WHERE pnr='AWSY3I'
UNION ALL SELECT 'passenger', attribute_type, attribute_action, last_modified FROM passenger_updates pu JOIN trip t ON pu.pnr_id=t.pnr_id WHERE t.pnr='AWSY3I'
UNION ALL SELECT 'ssr',       code,           status,            last_modified FROM special_service_request s JOIN trip t ON s.pnr_id=t.pnr_id WHERE t.pnr='AWSY3I'
ORDER BY last_modified;

-- Trip creation rate with gap-day detection
SELECT day::date, COALESCE(n, 0) AS trips
  FROM generate_series(CURRENT_DATE - 20, CURRENT_DATE, '1 day') day
  LEFT JOIN (SELECT created_at::date d, COUNT(*) n FROM trip GROUP BY 1) t ON t.d = day::date
 ORDER BY 1 DESC;

-- Passenger-update dup finder (keeps NAME-null pattern visible)
SELECT attribute_type, attribute_action IS NULL AS action_is_null, COUNT(*) AS groups
  FROM (SELECT passenger_id, last_modified_event_log_id, attribute_type, attribute_action, COUNT(*) c
          FROM passenger_updates GROUP BY 1,2,3,4 HAVING COUNT(*) > 1) d
 GROUP BY 1,2;
```

---

## 7. Universal invariants (apply to every consumer)

| ID | Invariant | Consequence |
|---|---|---|
| I1 | At-least-once duplicate emission | Dedupe on `(entityId, version, eventName)` or on `event.id` (UUID) |
| I2 | Multiple events share a `data.version` | Group by version before processing |
| I3 | First observed version can be ≠ 1 | Consumer must not assume history is complete; enter the stream at any version |
| I4 | Partition arrival order ≠ version order | Buffer and sort by `data.version` within a PNR before fold |
| I5 | Null / tombstone records exist | Parser must skip, not DLQ |
| I6 | Mixed-entity topics (OAG_STATUS on PNR topic; baggage events on a physical-world topic) | Route by payload shape, not just topic |
| I7 | Point-of-sale identifies origin system (AC / 1A / UA / OS / F1) | Different downstream routing; test across at least AC + 1A + UA |
| I8 | Duplicate emission doubles raw counts — use logical (deduped) counts for classification | `analyze_pnr.py` does this via `_logical_counts` |
| X1 | Fan-out completes within ~500 ms after the first hop | Anything slower = transform lag, alert |
| X2 | EVENT-DETECTION always precedes RESULT-EVENT (50–150 ms) | RESULT-EVENT is downstream of DETECT, not parallel |
| X3 | Baggage joins to PNR via `data.pnr` directly | No bag-tag mapping needed on the PNR side |
| X4 | `RESULT-EVENT (no bounds)` records are idempotent no-ops | Safe to re-emit; don't produce customer-facing output |
| X5 | Baggage BAG_ACCEPTED heartbeats every 5–15 min | Debounce before re-evaluating the trip |
| X6 | Every baggage event triggers a full DETECT+RESULT cycle today | Bug-worthy at scale; consumer debouncing needed |
| X7 | EVENT-DETECTION retains more PNRs than DERIVED-PNR in the same window | DETECT persists state across DERIVED retention rolls |
| X8 | Transform lag budget: p99 ≤ 30 s upstream → TRANSFORMED | Alert when exceeded; TRANSFORMED is the slowest hop |

---

## 8. PNR lifecycle scenarios

See `docs/test_cases_narrative.md` for the single-feed scenario catalog and
`docs/test_cases_v2_multifeed.md` for the cross-feed narrative. Summary
(single-feed classifier buckets from `analyze_pnr.py`):

| Code | Name | Rough share | Notes |
|---|---|---:|---|
| S0 | Creation-only | 36% | New PNR, no downstream activity within window |
| S3 | Cancellation (no replacement) | 31% | Dominant real-world pattern; over-index QA here |
| S4 | New with codeshare | 11% | Partner-airline segments |
| S8a | New with tagging (keyword/remark) | 10% | Agent annotation |
| S5 | New with SSR | 6% | Accessibility / meal / medical |
| S2 | Rebooking (remove + add segments) | 4% | Classic "change itinerary" |
| S6 | Seat change only | <1% | Not customer-notified |
| S12 | Flight operational update (carrier-pushed) | <1% | FLIGHT_TIME_UPDATE etc. |
| S13 | Passenger name change | <1% | Regulatory — secure-flight / DGR |
| S7 | Contact update storm | <1% | **Likely bug** — 62-74 CONTACT_ADDED/REMOVED in 1s |
| S11 | High churn (≥4 versions) | rare | Reorder-stress case |
| S14 | Split / group PNR | 0% observed | Rule ready for when they appear |

---

## 9. Running the tooling

All commands assume you're in the repo root (`cd /Users/suresh/dev/fargate-tailscale-jumpbox`) with WARP connected.

### 9.1 Pull data

```bash
# single-topic pull (generalised) — default N=100000, auto-timestamped file
./scripts/pull_topic.sh DERIVED-PNR-EVENTS-CRT 100000 data/pnr-$(date +%Y%m%d).ndjson

# classic PNR pull, backwards-compatible
./scripts/pull_pnr.sh 100000
```

Script handles low-volume topics: falls back to `-o beginning` if `-o -N`
returns zero rows (retention-truncated topics).

### 9.2 Single-feed scenario analysis

```bash
./scripts/analyze_pnr.py data/pnr-20260421-173610-n100000.ndjson
```

Outputs (co-located with the input):

- `*.scenario_summary.csv` — per-scenario counts
- `*.pnr_timelines.csv` — one row per PNR
- `*.llm_ready_samples.jsonl` — PII-scrubbed samples for LLM narration
- `*.flight_ops_summary.csv` — non-PNR (OAG_STATUS) events on this topic

### 9.3 Cross-feed correlation

Pull the correlated topics into `data/corr/`:

```bash
for T in TRANSFORMED-PNR-EVENTS-CRT EVENT-DETECTION-PNR-CRT RESULT-EVENT-DETECTION-CRT DERIVED-BAGGAGE-SMARTSUITE-EVENTS-CRT; do
  ./scripts/pull_topic.sh "$T" 50000 "data/corr/${T}.ndjson"
done
```

Then correlate:

```bash
./scripts/analyze_correlated.py data/corr/ --trace-top 5
```

The analyzer auto-discovers ndjson files in both `data/corr/` and its parent
`data/`, so a DERIVED-PNR dump in `data/` is picked up automatically.

Outputs in `data/corr/`:

- `*.coverage.csv` — per-topic stats + cross-topic coverage histogram
- `*.journeys.csv` — per-PNR event counts across topics
- `*.trace_<PNR>.txt` — time-ordered cross-feed trace per traced PNR

### 9.4 LLM-driven narration (optional)

```bash
cat data/pnr-*.llm_ready_samples.jsonl | <your-llm> -p \
  'Given these grouped PNR event sequences, write a QA test-case narrative
   per scenario: preconditions, event sequence, expected downstream output,
   edge cases to cover.'
```

### 9.5 Scenarios & the scenario engine (raw-topic injection)

The goal here is end-to-end pipeline validation: inject synthetic raw payloads on the actual source topics (the `emh-dev.*` family — see §12.3) and observe whether the Flink → TRANSFORMED → EVENT-DETECTION → EDS → Aurora cascade produces the expected output. **Raw topics are the only injection point that exercises the full pipeline;** publishing to a DERIVED-* topic would skip the Flink change-detector and mis-simulate real behaviour.

**`scenarios/`** is now organised around the **scenario document** as the primary artefact. Each scenario is a single JSON file that doubles as human-readable documentation AND the input program for the engine. See `scenarios/README.md` for the full v2 schema.

Key pieces:

- `scenarios/<scenario>.json` — declarative: identity, POS, passengers, segments, timeline of versions, expected_cascade (assertions), classification/tags/dimensions.
- `scenarios/_canvas/<base>.json` — a real `processedPnr` captured from live data, stripped of the outer envelope. The engine mutates this to cover Amadeus fields we don't want to model (`automatedProcesses`, `financialValues`, `fareElements`, etc.).
- `scripts/scenario_engine.py render` — turns a scenario + canvas into a sequence of raw Kafka records ready for `emh-dev.ALTEA-PNRDATA-UAT`.

The engine auto-computes per version:
- `previousRecord` (RFC 6902 JSON-Patch from current state back to previous);
- `events.events[]` COMPARISON events (CREATED / UPDATED / DELETED) derived from the forward patch;
- a fresh `meta.triggerEventLog.id` (hex32-hex16 format).

**Invariant about timestamps across versions:** within one scenario, `creation.dateTime` stays constant across all versions (it's the PNR's original booking moment); `lastModification.dateTime` changes per version. Traveler document creation timestamps are pinned to the booking moment too — a passport attached at booking time doesn't get re-stamped just because the PNR's version number bumps. Violating either produces spurious diff entries in `previousRecord`.

**Canvas-based scrub:** the engine inherits Amadeus fields from the canvas but aggressively scrubs canvas-specific identifiers — `bookingIdentifier`, `id` (pnr_id), office_id, iata_number — so no identifiers from the source PNR leak into the synthesized output. Verify with `grep -c <canvas_pnr> /tmp/rendered.ndjson` (must be 0).

**Raw PNR payload structure** (the shape the engine produces, and what `emh-dev.ALTEA-PNRDATA-UAT` contains natively):

```
{
  meta: { triggerEventLog: {id: "hex32-hex16"}, version: "1.13.0" },
  events: { recordDomain: "PNR", recordId: "<pnr_id>",
            originFeedTimeStamp: "<iso-utc>",
            events: [{origin: "COMPARISON",
                      eventType: "CREATED"|"UPDATED"|"DELETED",
                      currentPath, previousPath?}, …] },
  previousRecord: [ JSON-Patch ops from current → previous ],
  processedPnr: { bookingIdentifier, id, version, type, owner,
                  creation, lastModification, queuingOffice,
                  travelers[], products[] (= flight segments),
                  flightItineraries[] (= bounds referencing products[]),
                  contacts, remarks, automatedProcesses,
                  paymentMethods, fareElements, quotations,
                  ticketingReferences?, deliveryData, financialValues } }
```

Segments are nested: `flightItineraries[i].flights[j].flightSegment.id` is a `ref` pointer into `products[]`, which holds the actual `airSegment` detail (carrier, flight number, dep/arr, cabin, status).

**Observed PNR lifecycle pattern at the raw layer:** a PNR typically starts with a v0 "pre-ticketing stub" and v1 "ticketing added" within the same second. Flink emits `PNR_CREATION` on the DERIVED-PNR topic when it observes v1 (not v0). Subsequent versions drive the downstream UPDATE events. B45OZB-2026-04-22 had 18 versions (v0–v17) spanning ~57 min, with the DB materialising only the first few versions at any given instant (change-processor lag).

**At-least-once duplication is at the raw layer too** — each version's raw message appears on 2+ partitions across the 25-partition `emh-dev.ALTEA-PNRDATA-UAT`. Consumers (Flink) must dedupe on `meta.triggerEventLog.id`.

**Example workflow (render-only — Phase 1 complete):**

```bash
./scripts/scenario_engine.py validate --scenario scenarios/ZZTEST-2099-12-31-domestic-create-only.json
./scripts/scenario_engine.py render \
    --scenario scenarios/ZZTEST-2099-12-31-domestic-create-only.json \
    --out /tmp/zztest.ndjson
# → 2 raw records (v0 bootstrap, v1 ticketing_added) ready to inject
```

**Phase 2 (not yet built):** `scripts/publish_raw.py` to actually produce to Kafka (with `--dry-run` default), and `scripts/watch_downstream.py` to tail DERIVED/TRANSFORMED/EVENT-DETECTION/RESULT-EVENT-DETECTION + Aurora for a time window after publish and assert against `expected_cascade`.

---

## 10. Known traps and time-savers

1. **Don't use `ping`** to smoke-test VPC connectivity — cloudflared ICMP proxy is on, but Cloudflare edge still returns "Destination Host Unreachable". Use `nc -vz HOST PORT`.
2. **`-o -N` on kcat silently returns nothing** for topics whose log-start is above `HWM - N` (retention-truncated). Use `-o beginning -c N -e` as a fallback. `pull_topic.sh` handles this automatically.
3. **SSO tokens expire (default 8 h)** mid-session. When `aws` commands start erroring with "Token has expired and refresh failed", run `aws sso login --profile ac-cct-crt`.
4. **Global API keys in `.env`** (Cloudflare) are dangerous. Rotate the current one and replace with a scoped API Token when you get a chance. See README.txt note.
5. **MSK unauth + WARP means anyone enrolled can read customer PII.** Do not treat WARP as a security boundary; file tickets to enforce SASL/IAM.
6. **Per-PNR-version events all share the same `ts_ms`** (down to the ms) — don't rely on timestamp ordering within a version, rely on `data.version` + internal event ordering.
7. **`analyze_pnr.py` uses logical counts** (deduped by `(version, eventName)`) for classification. This is important — raw counts double every threshold because of I1.
8. **Baggage storm** (`CJ2ASJ` bag `0014969329` had 100+ `BAG_ITINERARY_CHANGED` in 5 hr) is not a hypothetical — it's real, and worth alarming on before someone notices the downstream trip-tracer burning CPU.
9. **Broker DNS resolves to private `10.111.x` IPs**, so WARP must be routing `10.111.196.0/22`. If `dig b-1.accctmskcrtcac1.05hf7o.c4.kafka.ca-central-1.amazonaws.com` returns a 10.x address but `nc -vz b-1... 9092` fails, WARP is enrolled on a profile that still excludes the VPC range — re-check the device profile's Split Tunnels.
10. **`corr50k` files supersede `correlated.*` files** — I removed the 2k-sample outputs during the reorg since the 50k run covers them entirely.
11. **DB name has a hyphen** — `trip-tracer`. Always quote it in psql (`-d 'trip-tracer'`) or it's parsed as flags.
12. **Cancellation ≠ status=CANCELLED** in the trip-tracer DB — look for `status='INACTIVE'` or `archive_date IS NOT NULL`. The check constraint only allows `ACTIVE`/`INACTIVE`.
13. **PNR code alone is not unique** — key by `pnr_id` (6-char PNR + booking date, e.g. `AX32W9-2026-04-21`). 1,023 PNR codes appear under multiple dates.
14. **NAME `passenger_updates` duplicates** (788 groups) are a real dedup bug — the producer doesn't set `attribute_action` for NAME events, and NULL in a UNIQUE key doesn't block dupes. See §6.5 for fixes.
15. **`.env` uses YAML-ish colon syntax**, not `KEY=VALUE`, for the RDS credentials. Parse with `grep KEY .env | cut -d: -f2 | xargs`, don't `source .env`.
16. **"Non-Retryable error encountered" in ingestion logs is misleading.** It means the *SQL statement* can't be retried inline (e.g. `ON CONFLICT` can't resolve a `23503` FK violation), NOT that the message is dead. The service routes the record to `cct-ingestion-{feed}-fk-queue-crt` for later retry when the parent row arrives. Confirm via the `"SQS batch message pushed to … fk-queue-crt"` log line that follows. Only when it exhausts the fk-queue retry budget does it land in `-dlq-crt`.
17. **Idempotency is layered, not just one mechanism.** Duplicate rows → `ON CONFLICT DO NOTHING` absorbs silently (23505 never surfaces). FK-missing → fk-queue retry (23503 is expected and handled). Transient errors → transient-queue with backoff. Only terminal failures land in DLQ. Don't read DB-layer `ERROR`/`23503` log lines as pipeline defects without checking the next line for SQS routing.

---

## 11. Operational reminders for the next session

- Re-login if needed: `aws sso login --profile ac-cct-crt`.
- One-line SSO smoke test: `aws s3 ls --profile ac-cct-crt`. Success = session valid. "Token has expired" = run `sso login` first. Listing the CRT bucket names costs nothing and is also a nice reminder of the apps running in the account.
- Confirm WARP: `/Applications/Cloudflare\ WARP.app/Contents/Resources/warp-cli status` should say `Connected`.
- Smoke-test VPC reachability: `nc -vz b-1.accctmskcrtcac1.05hf7o.c4.kafka.ca-central-1.amazonaws.com 9092`.
- Need a bigger PNR sample: `./scripts/pull_pnr.sh 500000 data/pnr-big.ndjson` (expect ~1-3 GB file).
- Re-run architecture inventory (changes are likely): spawn a subagent with the original prompt used to generate `docs/architecture.md` and `docs/inventory.csv`.
- DB quick-check: `PGPASSWORD=... psql -h <host> -U dbadmin -d 'trip-tracer' -c "SELECT MAX(received_at) FROM journey_updates;"` — if the max timestamp is more than ~10 min behind wall clock, the Kafka→DB pipeline is lagging. See §6.6.

---

## 12. Raw feed ingestion — S3, MSK Connect, MirrorMaker (validated)

**Motivation:** confirm that every raw feed file landing in S3 is correctly
processed into a Kafka topic, i.e. parity between S3 objects and Kafka
offsets per feed per day.

**Conclusion up front:** the initial hypothesis (S3 is the upstream source,
Kafka derives from it) was wrong for the live flow. For the live flow **S3
is a sink**, archiving what's already on Kafka. For the historical
backfill flow, S3 is the source. Details below are all validated against
live AWS as of 2026-04-22, with corroborating context from the
`/Users/suresh/dev/cc-analysis/knowledgebase/` reference documents (AODs
for Trip Tracer, CCT overview, historical data migration).

### 12.1 Validated facts from live AWS

**The S3 landing bucket is `cct-data-feeds-crt`.** Top-level prefixes match the 10 MSK Connect connector pairs exactly: `aacc/ baggage/ cm/ fdm/ gigya/ icoupon/ ifly/ pnr/ stormx/ tkt/`.

Under each feed, a second level of prefix names the mirrored Kafka topic, and below that is Hive-style hourly partitioning. Example:

```
cct-data-feeds-crt/
└── pnr/
    ├── emh-dev.ALTEA-PNRDATA-UAT/
    │   └── year=2026/month=04/day=22/hour=00/
    │       └── emh-dev.ALTEA-PNRDATA-UAT+0+0000011355.json  (6.3 KB, 1 record)
    └── emh-dev.ALTEA-PNRCORR-UAT/
        └── year=2026/month=04/day=22/hour=00/…
```

The filename format `TOPIC+PARTITION+OFFSET.json` is the standard
Kafka-Connect S3-sink naming pattern. Each file is **one Kafka message** (confirmed
by inspection: 6.3 KB JSON, 1 line, containing `meta.triggerEventLog` +
`processedPnr` + `previousRecord` JSON-patch diff).

**All 20 MSK Connect connectors, resolved via `describe-connector`:**

| Pair | Source-side connector (`MirrorSourceConnector`) | Source topics on `emh-dev` | Sink-side connector (`S3SinkConnector`) | S3 bucket |
|---|---|---|---|---|
| AACC | `cct-shared-infra-crt-AACCFeedMskConnect-*` | `ALTEA-AACC-UAT` | `...-AACCFeedMskConnectS3-*` | `cct-data-feeds-crt` |
| BaggageSmartSuite | `...-BaggageSmartSuiteFeedMskConnect-*` | `BROCK-BAGGAGE-UAT` | `...-BaggageSmartSuiteFeedMskConnectS3-*` | `cct-data-feeds-crt` |
| CM | `...-CMFeedMskConnect-*` | `ALTEA-CM-UAT` | `...-CMFeedMskConnectS3-*` | `cct-data-feeds-crt` |
| FDM | `...-FDMFeedMskConnect-*` | `EAI-FDM-UAT` | `...-FDMFeedMskConnectS3-*` | `cct-data-feeds-crt` |
| ICoupon | `...-ICouponFeedMskConnect-*` | `DBASS-ICOUPON-UAT` | `...-ICouponFeedMskConnectS3-*` | `cct-data-feeds-crt` |
| PNR | `...-PNRFeedMskConnect-*` | `ALTEA-PNRDATA-UAT, ALTEA-PNRCORR-UAT` | `...-PNRFeedMskConnectS3-*` | `cct-data-feeds-crt` |
| StormX | `...-StormXFeedMskConnect-*` | `STORMX-HOTEL-COMPENSATION-UAT` | `...-StormXFeedMskConnectS3-*` | `cct-data-feeds-crt` |
| TKT | `...-TKTFeedMskConnect-*` | `ALTEA-TKT-UAT, ALTEA-TKTCORR-UAT` | `...-TKTFeedMskConnectS3-*` | `cct-data-feeds-crt` |
| Gigya | `cct-kafka-mirroring-crt-GigyaFeedMskConnect-*` | `MULE-LOYALTY-GIGYA-CUSTPROFILE-UAT` | `...-GigyaFeedMskConnectS3-*` | `cct-data-feeds-crt` |
| iFly | `cct-kafka-mirroring-crt-iFlyFeedMskConnect-*` | `MULE-TOTALBALANCEUPDATES-UAT`, `IFLY-TIERSTATUSUPDATES-UAT`, `IFLY-MEMBERSHIPSTATUSCHANGES-UAT`, … | `...-iFlyFeedMskConnectS3-*` | `cct-data-feeds-crt` |

- The **source** is always `MirrorSourceConnector` (Kafka MirrorMaker 2) pulling from a remote cluster aliased **`emh-dev`** (Enterprise Messaging Hub, in the **EIP** AWS account — per kb `architecture/cct-overview.md`).
- After mirroring, on **our** MSK cluster the topics are prefixed `emh-dev.` (e.g. `emh-dev.ALTEA-PNRDATA-UAT` — that's why every topic in our cluster with `emh-dev.` prefix is a mirrored raw feed).
- The **sink** is always `S3SinkConnector` writing those same mirrored topics back out to S3.
- All topic names end in `-UAT`. These are **UAT/staging topics from EMH**, not production — i.e. the CRT environment here is hooked up to EMH's UAT tier, which makes sense given the `-crt` environment naming (`crt` = pre-prod).

**Daily hit count on `cct-data-feeds-crt/pnr/emh-dev.ALTEA-PNRDATA-UAT/` (hour granularity, Apr 2026):**

| day | h=00 | h=06 | h=12 | h=18 | note |
|---|---:|---:|---:|---:|---|
| 15 | 0 | 0 | 0 | 35,416 | backfill wave when topic bootstrapped |
| 16 | 0 | 532 | 894 | 972 | |
| 17 | 1,518 | 856 | 862 | 342 | |
| **18** | **458** | **292** | **362** | **544** | **data present — upstream healthy** |
| **19** | **490** | **332** | **420** | **608** | **data present — upstream healthy** |
| 20 | 698 | 672 | 716 | 478 | |
| 21 | 506 | 642 | 970 | 734 | |
| 22 | 532 | 584 | 642 | 0 | (current hour in progress) |

**Gap-day verification.** In §6.6 we flagged that the `trip-tracer` DB had **zero trip rows created on Apr 18 or 19**. The corresponding S3 counts above prove the **upstream was NOT the problem**:
- EMH → MirrorMaker (source connector) was running both days.
- MirrorMaker → CCT MSK (on-cluster topic) was receiving messages both days.
- CCT MSK → S3 sink (sink connector) was writing files both days.

Therefore the **Apr 18-19 trip-creation outage is strictly downstream of the S3 sink** — in the Flink/DERIVED→TRANSFORMED→Ingestor chain that lands rows in Aurora. Likely suspects: Flink job paused, ECS transformer/ingestor task crashed, or DB outage. Needs CloudWatch log correlation on those days (§12.4).

**Second feed confirmation (TKT, CM):**

| feed/topic | day=18 files | day=19 files | notes |
|---|---:|---:|---|
| tkt/ALTEA-TKT-UAT | **0** | **0** | This topic appears **empty upstream** — likely the Altea TKT feed isn't wired yet; only TKTCORR is flowing |
| tkt/ALTEA-TKTCORR-UAT | 5,377 | 6,249 | Healthy through gap days |
| cm/ALTEA-CM-UAT | (large — day 15 alone had 197,325 files, backfill) | … | Steady flow |

The `ALTEA-TKT-UAT` topic being empty across every day in the window is itself a finding worth surfacing to the team — if anything expects tickets to flow through the non-correlation stream, it's going to get nothing.

### 12.2 What the knowledgebase says (validated where it overlaps with live data)

Facts from `cc-analysis/knowledgebase/` that I have **confirmed against live AWS** and can now treat as canonical:

- **Account topology** (from `architecture/cct-overview.md`): CCT (050752605169) ↔ EIP ↔ CIAM/DBaaS v2 ↔ AC Digital, all in ca-central-1, linked via AC Transit Gateway. EMH Kafka lives in the EIP account.
- **"Feed Archival"** — the kb doc `systems/trip-tracer.md` calls this "Feed Archival Flink", but the live implementation is **MSK Connect S3 sinks** (not Flink). Same outcome — 30-day rolling S3 archive — but the component is different. Inventory shows `S3SinkConnector` connectors, not a Flink app for archival.
- **Two S3 buckets, two purposes:**
  - `cct-data-feeds-crt` — live archive of every mirrored topic (naming: `cct-data-feeds-{env}` per `architecture/data-migration.md` Part 2 §"Phase 1: Deploy ac-cct-infra").
  - `cct-historical-data-feeds-crt` — historical data pulled from Snowflake / ADLS / S3 ODH via Glue jobs; consumed by `cct-*-historical-migration-job-crt` Glue jobs and the `cct-flink-etl-{feed}-crt-FlinkHistorical*` stacks. Prefixes confirmed live: `baggage/ cancel_voucher/ cm-passenger-corr/ gigya/ glue-scripts/ icoupon/ icoupon_redemption/ ifly/ pnr-ticket-emd-correlation/ pnr/ stormx/`.
- **Historical feed flow (kb + inventory):** Snowflake/ADLS/ODH → Glue → `cct-historical-data-feeds-crt` → MSK Connect S3 **source** → Kafka `*-REPLAY-CRT` topics (per-feed) → same Flink/ETL pipeline as live → DERIVED-*. This is the ONLY path with an S3 *source* connector. The MSK Connect connectors for this path are managed by the `cct-flink-etl-{feed}-crt` stacks, not the `cct-shared-infra-crt` connectors above.
- **Deployment order** is three repos, strict: `ac-cct-infra` → `ac-cct-service-proxy` → `ac-cct-trip-tracer-ingestion`. Environment = branch (`develop=INT`, `release=CRT`, `bat=BAT`, `main=PROD`). CRT account is 050752605169 (our account), PROD account is `861276123487`.
- **Raw feed payload structure** (confirmed by downloading a real file from S3): JSON body `{meta:{triggerEventLog:{id:...}, version:"1.13.0"}, previousRecord:[JSON-Patch ops], processedPnr:{…full PNR state…}}`. The `meta.triggerEventLog.id` is the **same identifier** that shows up in the DB as `last_modified_event_log_id` on `journey_updates`, `passenger_updates`, etc. — that is the cross-feed idempotency key.

- 39 S3 buckets in the account. Candidates for the raw-feed landing zone:
  - **`cct-data-feeds-crt`** (created 2026-03-26) — most likely the active landing zone for the 10 MSK-Connect-sourced feeds. Naming matches "data feeds". Created the same day as other shared-infra resources.
  - **`cct-historical-data-feeds-crt`** (created 2026-03-25) — backfill / historical dump used by the `cct-{pnr,tkt,baggage,stormx,cm,icoupon,aacc}-historical-migration-job-crt` Glue jobs and the `cct-flink-etl-*-crt-FlinkHistorical*` Flink stacks.
  - **`cct-customer-profile-input-crt`** (2026-04-14) — customer-profile specific input. Much newer than the other feeds, matches the recently-active Customer Profile service.
  - **`cct-entity-resolution-input-crt`** (2026-03-18) — entity-resolution specific.
  - **`cct-cp-msk-connect-crt`** — confirmed S3 *sink* from the architecture doc's customer-profile diagram (`ConnG/iF -->|S3 sink| S3G`). Gigya/iFly MSK Connect writes here, not reads from.
  - **`cct-msk-connect-crt`** — shared-infra MSK Connect bucket; probably plugin JARs and/or S3 sink archive for the eight `cct-shared-infra-crt-*FeedMskConnect*` connectors.

- 20 MSK Connect connectors are all RUNNING (from inventory), in 10 feed pairs:
  - `cct-shared-infra-crt-{Feed}FeedMskConnect-connector-*` + `*FeedMskConnectS3-connector-*` for: AACC, BaggageSmartSuite, CM, FDM, ICoupon, PNR, StormX, TKT (8 feeds × 2 connectors = 16).
  - `cct-kafka-mirroring-crt-{Gigya,iFly}FeedMskConnect{,S3}-connector-*` (2 × 2 = 4).
  - Architecture doc confirms the `*S3` variant is a **sink** (MSK → S3 archive). The non-`S3` variant is the source — either S3→MSK (if upstream drops files) or JDBC/MirrorMaker (if upstream pushes directly). Which, specifically, needs a live `describe-connector` to confirm.

- 7 `cct-flink-etl-{feed}-crt-FlinkHistorical{Feed}Flink*` stacks exist, one per feed (baggage, cm, cm-pax-correlation, fdm, stormx, tkt, pnr, icoupon, icoupon-redemption, aacc, pnr-tkt-correlation, cancel-voucher). These are **Flink ETL jobs** running on (likely) Amazon Managed Service for Apache Flink, pulling from historical data feeds and producing `DERIVED-*-HISTORICAL-*-CRT` topics.

- 11 Glue jobs. 7 are per-feed historical migration jobs (`cct-{pnr,tkt,baggage,stormx,cm,icoupon}-historical-migration-job-crt`). Plus `cct-pnr-ticket-emd-correlation-migration-job-crt`, `cct-cm-passenger-pnr-correlation-migration-job-crt`, `cct-historical-d0-processor-crt`, `cct-oag-status-glue-job-crt`, `cct-arrival-code-glue-job-crt`, `cct-cancel-code-glue-job-crt`, `cct-snowflake-glue-test-job-crt`.

### 12.3 Corrected ASCII flow — live + historical

```
(A) LIVE FLOW
──────────────────────────────────────────────────────────────────
   EIP account              AC-Transit GW            CCT account (ours)
 ┌────────────────┐       ┌──────────────┐       ┌──────────────────────────────┐
 │ EMH MSK        │       │              │       │ CCT MSK (ac-cct-msk-crt-cac1)│
 │ Kafka, UAT tier│──────▶│  (TGW hop)   │──────▶│ topic: emh-dev.ALTEA-PNRDATA │
 │  ALTEA-PNRDATA │       │              │       │        (and 13 others,       │
 │  ALTEA-PNRCORR │       └──────────────┘       │         `emh-dev.` prefix)   │
 │  ALTEA-TKT/CORR│                              └──────────────┬───────────────┘
 │  ALTEA-CM      │                                             │
 │  ALTEA-AACC    │             *FeedMskConnect                 │ Flink (MSF)
 │  EAI-FDM       │             (MirrorSource)                  │ change-detector
 │  DBASS-ICOUPON │                                             ▼
 │  STORMX-HOTEL  │                              ┌──────────────────────────────┐
 │  BROCK-BAGGAGE │                              │ DERIVED-PNR-EVENTS-CRT,      │
 │  Gigya (MULE-..│                              │ DERIVED-TKT-EVENTS-CRT, …    │
 │  iFly (MULE-.. │                              └──────────────┬───────────────┘
 └────────────────┘                                             │
                                                                │ ECS transformer
                                                                ▼
                                              ┌──────────────────────────────────┐
                                              │ TRANSFORMED-*-EVENTS-CRT         │
                                              └──────────────┬───────────────────┘
                                                             │ ECS ingestor
                                                             ▼
                                              ┌──────────────────────────────────┐
                                              │ trip-tracer Aurora Postgres      │
                                              │  (journey_updates / trip / …)    │
                                              └──────────────────────────────────┘

 branches off every `emh-dev.*` topic:
                                              ┌──────────────────────────────────┐
              *FeedMskConnectS3               │ S3: cct-data-feeds-crt/          │
            (S3SinkConnector)  ───────────▶  │   {feed}/emh-dev.{topic}/         │
                                              │   year=/month=/day=/hour=/       │
                                              │   TOPIC+PARTITION+OFFSET.json    │
                                              │   (one Kafka msg per object)     │
                                              └──────────────────────────────────┘
                                              ~30-day rolling archive

(B) HISTORICAL / BACKFILL FLOW
──────────────────────────────────────────────────────────────────
 Azure ADLS / Snowflake (AC Data Lake) ─────┐
                                             │ Glue jobs
 AWS Digital S3 ODH ─────────────────────── │  (cct-*-historical-migration-job-crt)
                                             ▼
                              ┌───────────────────────────────────────┐
                              │ S3: cct-historical-data-feeds-crt/    │
                              │  pnr/ baggage/ cm-passenger-corr/     │
                              │  icoupon/ icoupon_redemption/ stormx/ │
                              │  pnr-ticket-emd-correlation/ …        │
                              └──────────────────┬────────────────────┘
                                                 │ MSK Connect S3 Source
                                                 │ (managed by cct-flink-etl-*)
                                                 ▼
                              ┌───────────────────────────────────────┐
                              │ Kafka REPLAY topics                   │
                              │  PNR-REPLAY-CRT, TKT-REPLAY-CRT, …    │
                              │  (entry point identical to LIVE after │
                              │  this line — shares Flink + ECS path) │
                              └───────────────────────────────────────┘
```

### 12.4 Parity answer (live flow)

For the live flow, **S3 is authoritative archive, not source**. The parity
question flips from what the user originally asked:

- If a record is on `cct-data-feeds-crt/{feed}/emh-dev.{topic}/…+PARTITION+OFFSET.json`, it was on CCT MSK (because the S3 sink reads from there).
- If it was on CCT MSK's `emh-dev.*` topic, it came from EMH via MirrorMaker2 (because that's the only producer to those topics).
- So "all messages in S3 end up in Kafka" is trivially yes — the temporal order is Kafka first, then S3. Validated: files per feed per day are non-zero on every day Apr 15-22, **including Apr 18 and 19**.

The meaningful integrity question instead is: **"does every `emh-dev.*` Kafka
message eventually produce a DB row for that PNR?"** That's the question
answered by §6.6 of this doc: **no**, Apr 18-19 had 0 new `trip` rows despite
thousands of PNR files landing in S3 both days, so the failure is strictly
**downstream of the S3 sink** — in the Flink→Transformer→Ingestor chain.

Empirically: Apr 18-19 = **~4,700 PNRDATA-UAT files** landed in `cct-data-feeds-crt`, but 0 new `trip_id` rows in Aurora. Confirming Flink or ECS transformer/ingestor outage on those days — next step is to pull CloudWatch log groups `/aws/msf/*`, `/ecs/transformer-pnr-crt`, `/ecs/ingestion-pnr-crt` for those dates.

### 12.5 Historical backfill details (new — validated live)

**`cct-historical-data-feeds-crt` is active and real.** Sampled objects (from
the `2025-04-01_2025-06-30/year=2023/month=09/…` subtree) confirm per-PNR JSON
files, 15-200 KB each, produced 2026-04-18 01:09-01:27 by the PNR historical
Glue job run that completed Apr 17 23:29. File naming:

```
pnr/{migration-window}/year={YYYY}/month={MM}/day={DD}/{PNR}-{DATE}/{PNR}-{DATE}_{epoch}.json
```

Each file aggregates one PNR's full history, partitioned by event (creation)
date. The `migration-window` top-level prefix (e.g. `2025-04-01_2025-06-30`)
is how the Glue job chunks 3-month windows (per kb `data-migration.md`
"batches of 3 months").

**Glue historical jobs (validated):**

| Job | Output bucket/prefix | Source (Snowflake) | Last run |
|---|---|---|---|
| `cct-pnr-historical-migration-job-crt` | `cct-historical-data-feeds-crt/pnr/` | `EDW_UAT.CCT_TRIPTRACER_HISTORICAL.*` (PNR tables) on `aircanadaprod.east-us-2.azure.snowflakecomputing.com` | 2026-04-17 23:29 SUCCEEDED (9,427 sec) |
| `cct-baggage-historical-migration-job-crt` | `cct-historical-data-feeds-crt/baggage/` | same Snowflake host, baggage tables | 2026-04-18 02:52 SUCCEEDED |
| `cct-oag-status-glue-job-crt` | (writes somewhere different — to confirm) | OAG status table (Snowflake) | 2026-04-21 22:00 SUCCEEDED — **scheduled daily at 22:00** |

All three use:
- **Snowflake credentials** from Secrets Manager: `/crt-cac1/ac-cct-trip-tracer-historical-data-glue-crt-cac1/snowflake-credentials`.
- **Checkpoint** in SSM Param Store: `/cct/crt/historical-migration/{feed}/checkpoint` — resume-on-failure state.
- **Scripts** in S3: `cct-glue-historical-scripts-crt/scripts/{feed}/{feed}-historical-data-migration.py`.
- **DLQ** in SQS: `cct-{feed}-historical-migration-dlq-crt` — failed records land here.

**Bucket lifecycle rules:**

| Bucket | Lifecycle |
|---|---|
| `cct-data-feeds-crt` | **30-day expiration on all objects** (`ExpireObjects` rule, empty prefix filter). Confirms the "~30-day rolling replay archive" design. |
| `cct-historical-data-feeds-crt` | **No lifecycle** — historical data accumulates indefinitely. |

**`cct-entity-resolution-input-crt` is tiny config, not bulk data** — just
`gigya.csv` (962 B) and `pnr.csv` (1,895 B) at the top, uploaded 2026-03-18.
These are likely the AWS Entity Resolution schema-mapping or seed files, not
the stream of records.

**`cct-customer-profile-input-crt` was empty at the top level** — either data
arrives under a prefix I didn't enumerate, or the customer-profile ingest
route writes direct-to-Kafka rather than via S3.

### 12.6 Gap-day root cause drill-down (new — validated via CloudWatch)

Followed the Apr 18-19 `trip`-creation outage (§6.6 C8) into CloudWatch. Full
pipeline is three ECS services per feed for PNR: **transformer** (DERIVED-PNR
→ TRANSFORMED-PNR + internal signalling) → **change-processor** (consumes
`EVENT-DETECTION-PNR-CRT`, produces `PROCESS-EVENT-DETECTION-PNR-CRT`) →
**ingestion** (TRANSFORMED-PNR → Aurora). Log groups:

```
/aws/ecs/cct-trip-tracer-cluster-crt/transformer-service-task
/aws/ecs/cct-trip-tracer-cluster-crt/processor-service-task
/aws/ecs/cct-trip-tracer-cluster-crt/ingestion-service-task
```

Per-day log event counts (PNR services), pulled with
`aws logs filter-log-events --log-stream-name-prefix …`:

| day | transformer-pnr | change-processor-pnr | ingestion-pnr | trip rows (§6.6) |
|---|---:|---:|---:|---:|
| Apr 16 | 1,364 | 1,486 | 1,072 | 422 |
| Apr 17 | 2,004 | 13 | 717 | 66 |
| **Apr 18** | **2,011** | **13** | **13** | **0** |
| **Apr 19** | **2,003** | **46** | **161** | **0** |
| Apr 20 | 1,757 | 1,447 | 1,313 | 322 |
| Apr 21 | 1,592 | 1,588 | 1,100 | 474 |

**Interpretation:** transformer was perfectly healthy every day. The break is
at the **change-processor** level, which went near-silent at 01:43 UTC on Apr
17 after a final clean `INFO "Batch processing completed"` message, and barely
produced anything until it recovered on Apr 20. Ingestion behaviour follows
change-processor's pattern because change-processor produces the signals
ingestion depends on (the PNR lifecycle inserts that create `trip` rows).

**No ERROR / WARN / Exception events** were emitted by change-processor
during the outage window — the service was logged as running, with steady
`/api/liveness` passes, but simply wasn't processing. This is consistent
with either:

1. **Kafka consumer group offset lag / stuck** — consumer alive, not making
   fetch progress (no visible errors, no ops signal).
2. **Upstream `EVENT-DETECTION-PNR-CRT` topic quiet** during Apr 17-19 — the
   rules-engine / event-detection-service (external producer) wasn't
   emitting. Change-processor was waiting on data that never came.
3. **DB/connection starvation** — downstream (Aurora RDS Proxy) slow or out
   of connections, so change-processor blocks on writes. RDS Proxy logs
   weren't pulled yet.

The ECS service shows no stopped-task events in the retention window (ECS
only keeps stop reasons for ~1 hour), so crashes can't be confirmed either
way from current state.

**Correction on the idempotency pattern** (earlier I mis-framed this as a defect — user pushback: this is actually the intended design). The ingestion pipeline uses a layered idempotency / out-of-order-resilience scheme:

1. **Duplicate rows (`23505`)** → SQL writes everywhere use `ON CONFLICT DO NOTHING RETURNING 1`. Duplicates silently absorbed. Consistent with the at-least-once emission we documented (§7 I1). Confirms why `journey_updates` has 0 dup groups (§6.5) and the *only* residual dup bug is the NAME-rows-with-NULL-action case.
2. **FK parent missing (`23503`)** → ingestion service catches the error, logs `"Non-Retryable error encountered"` at the DB layer, but the batch handler **pushes the record onto `cct-ingestion-{feed}-fk-queue-crt` SQS** with delay, for later retry once the parent (e.g. a `flight_leg` row written by OAG) arrives. This is the intended happy path for out-of-order arrivals between the OAG daily batch and the FDM stream. Log line to look for: `"SQS batch message pushed to … fk-queue-crt"`.
3. **Transient errors** → `-transient-queue-crt` (different retry cadence).
4. **Terminal failures** → `-dlq-crt` (retry budget exhausted).

This is a good design. The "Non-Retryable error encountered" log message at the DB layer is misleading — it means "this statement can't be retried in this transaction", not "this message is dead"; the service above the DB handles the retry.

**What is concerning** (checked against live SQS depths as of 2026-04-22):

| Queue | Visible | In-flight | Delayed | Interpretation |
|---|---:|---:|---:|---|
| `cct-ingestion-fdm-fk-queue-crt` | 0 | 257 | 2,680 | healthy retry loop |
| `cct-ingestion-fdm-transient-queue-crt` | 0 | 0 | 0 | clean |
| **`cct-ingestion-fdm-dlq-crt`** | **703,693** | 0 | 0 | **huge backlog of permanent failures** |
| `cct-ingestion-pnr-fk-queue-crt` | 0 | 0 | 44 | healthy |
| `cct-ingestion-pnr-transient-queue-crt` | 0 | 0 | 0 | clean |
| **`cct-ingestion-pnr-dlq-crt`** | **259,751** | 0 | 0 | **large backlog of permanent failures** |
| `cct-transformer-pnr-queue-crt` | 0 | 0 | 0 | — |
| `cct-transformer-pnr-dlq-crt` | 0 | 0 | 0 | — |

DLQs are where records land after exhausting fk-queue retries. Each one represents "FK parent never arrived" — i.e. FDM had a `flight_leg_id` that OAG never published, or PNR had an `entity_id` whose parent trip/passenger never materialised. **963k combined DLQ messages** is not a rounding error; it's either a chronic data-quality signal (feeds referencing flights that don't exist), retry-TTL too short, or a mis-ordered backfill. Worth pulling a DLQ sample and examining.

**What's known about the ECS pipeline structure (new):**

- 4 ECS clusters on trip-tracer workloads: `cct-trip-tracer-cluster-crt` (live), `cct-trip-tracer-historical-cluster-crt` (backfill replay), plus two support clusters.
- Per-feed services (PNR shown; similar pattern for tkt, fdm, aacc, cm-bag, smart-suite, stormx): `transformer-service-{feed}-crt`, `change-processor-service-{feed}-crt`, `ingestion-service-{feed}-crt`. Plus correlation variants like `transformer-service-pnr-tkt-crt`, `ingestion-service-pnr-tkt-corr-crt`.
- Per-feed SQS queues: `cct-{pipeline}-{feed}-queue-crt`, `-transient-queue-crt` (retry), `-fk-queue-crt` (FK failures, retry when parent arrives), `-dlq-crt` (give up).
- **24 Flink apps on Managed Service for Apache Flink:** 13 `*-crt` (live change detectors, all RUNNING) + 11 `*-etl-crt` (historical ETL, all READY — started on demand for backfill replays). Versions: `cct-pnr-crt` at v6 (most-churned), `cct-fdm-crt` at v5, others v3-4.
- Flink app logs under `/aws/kinesis-analytics/cep{Feed}CCT-crt` (e.g. `cepPNRCCT-crt`, `cepFDMCCT-crt`). These log groups are **not filterable via `filter-log-events`** in this account — returned `ValidationException: only supported on the Standard log class`, indicating they're Infrequent Access log class. Use `get-log-events` instead, which is slower but works.

### 12.6b FDM has only TWO upstream environments (TEST + PROD) — both CRT and INT subscribe to TEST

**Source of claim:** stated by Suresh (user, 2026-04-25) and validated empirically:

- CRT and INT trip-tracer DBs receive `flight_leg` writes within ~63 ms of each other on the same wall-clock instant (CRT `MAX(received_at) = 2026-04-25 03:29:14.096`, INT `… 03:29:14.159`).
- Per-day flight_leg creation counts are virtually identical in both envs (e.g. 2026-04-22: CRT=118, INT=117; 2026-04-21: CRT=103, INT=101). The very small drift is consistent with two consumers of the same upstream having slightly different replay/backfill state.
- CRT total flight_leg corpus (across 2024-01-10 → 2026-05-12) is **only 1,138 rows** — clearly a curated TEST sample, not a production firehose.

**Implications:**

1. The `cct-{pnr,tkt,baggage,…}` feeds have per-env streams (`emh-dev.*-UAT` mirrored into each env's CCT MSK, separate `cct-data-feeds-{env}` archive), but **FDM does not**. The FDM event source upstream from CCT has only two environments and CCT INT/CRT both consume the TEST one.
2. A missing flight in FDM TEST is missing in both CRT and INT simultaneously. Any PNR in either env that books a flight not in the TEST set will accumulate in `cct-ingestion-fdm-fk-queue-{env}` forever (no parent will ever arrive).
3. Active flights in the TEST stream right now (last 24 h of updates): AC2447, AC2353, AC2334, AC7181, AC1922, AC132, AC7171, AC2359, AC2074, AC2358. **AC400 is not in the test set**, even though it's a real Air Canada YYZ→YUL route.
4. INT has 17 March-2026 AC400 rows that CRT lacks — likely a one-off historical seed/replay applied only to INT. Confirm with FDM owners before relying on this drift as a feature.

**Practical guidance for synthetic test PNRs:**

- If your scenario's PNR books a flight number, **pick one from the active-TEST list** (AC2447, AC2353, etc.) so the FDM downstream actually fires. Booking AC400 will leave the segment dangling without flight_leg / flight_leg_updates rows.
- This applies to LEARNINGS §10 traps #16-17 (idempotency design): the fk-queue retry loop only resolves when the parent row arrives. For test PNRs whose parent will never arrive in TEST, expect indefinite fk-queue residency unless the suite tolerates it.

### 12.7 INT environment (account 982081066747) — separate tree, mostly mirrors CRT

Accessed via temporary SSO creds (`AWSReservedSSO_Arc75-temp_*`). VPC + layout details from the deployment playbook (validated live):

| Resource | INT |
|---|---|
| Account | `982081066747` |
| VPC | `vpc-0761edb89dad92a02` |
| ECS cluster (live) | `cct-trip-tracer-cluster-int` |
| ECS cluster (historical) | `cct-trip-tracer-historical-cluster-int` |
| Trip-tracer DB endpoint | `ac-cct-trip-tracer-rds-proxy-int-cac1.proxy-…` (not probed — no network path from laptop) |
| Live feed S3 bucket | **Missing** — `cct-data-feeds-int` does not exist; only `cct-data-feeds-dev` was found. Either Phase-1 CDK for INT wasn't run, or INT shares the dev archive. |
| Historical S3 bucket | `cct-historical-data-feeds-int` — has `baggage/ cancel_voucher/ cm-passenger-corr/ gigya/ icoupon/ icoupon_redemption/ ifly/ pnr/ pnr2/ stormx/ pnr-ticket-emd-correlation/ snowflake-extracts/` plus `glue-scripts/` (note the extra `pnr2/` and `snowflake-extracts/` prefixes not seen in CRT). |
| OTel log bucket | `cct-otel-logs-int` — S3 partitions `service=<name>/year=/month=/day=/hour=/*.gz`. |
| Athena catalog | Glue DBs `cct-entity-resolution-db-int`, `cct_otel_logs_int`, `entsre_logging_db_v7`, `lambda_logs_db`. Workgroups `cct-otel-logs-int`, `ac-cct-logs-workgroup-v2`. |
| Entity-resolution PNR table | `cct-entity-resolution-db-int.pnr_data` — 515,809 rows, columns `record_id, pnr_id, loyalty_id, email, phone`. Backed by `s3://cct-entity-resolution-input-int/pnr/`. |

**Cross-environment PNR lookup recipe** (session working example: `A5PCMS`):

```bash
# 1. Quick Athena check (no PII bucket access needed):
#    "SELECT * FROM \"cct-entity-resolution-db-int\".pnr_data WHERE pnr_id LIKE 'A5PCMS%' LIMIT 20"
#    (returned 0 — not every PNR flows through entity-resolution)

# 2. Full-coverage scan of OTel logs (INT ~280 MB, ~27k gz files — sync once, grep local):
aws s3 sync s3://cct-otel-logs-int/ /tmp/int-otel/ --quiet
find /tmp/int-otel -name '*.gz' -print0 | xargs -0 -P 8 zgrep -l A5PCMS
```

**Finding for A5PCMS:** active and healthy in INT. `pnrId=A5PCMS-2026-04-21`, 10 DEBUG events across 2026-04-21 19:58 → 2026-04-22 12:38 UTC in `service=trip-tracer-change-processor-pnr`. Every event logs the complete happy path: `Processing PNR change detection event (queryCount=N) → Built change payload (changeDetailCount=M) → Transaction completed successfully`, zero errors. Not present in CRT (correctly — environments are isolated).

**Two operational signals worth flagging:**

- **CloudWatch `filter-log-events` returned 0 hits for A5PCMS** on `/aws/ecs/cct-trip-tracer-cluster-int/{processor,ingestion,transformer}-service-task`, despite OTel S3 having 6 unambiguous hits in the same range. Either CW is dropping DEBUG-level records (fluent-bit filter) or the services log to OTel primary with CW as sampled. For audit-level "did X flow through?", **the OTel S3 bucket is the authoritative store**, not CloudWatch. Applies to both INT and (likely) CRT — re-verify when back there.
- **INT's `cct-data-feeds-int` bucket doesn't exist.** Deployment playbook says Phase-1 `ac-cct-infra` creates `cct-data-feeds-{stage}`. Absent on INT suggests the CDK stack wasn't deployed or was torn down. INT's live-flow archive is unclear — might be piggybacking on `cct-data-feeds-dev` or not archiving at all.

### 12.8 Open questions, queued

- Count per-day messages on `DERIVED-PNR-EVENTS-CRT` vs S3 file count to see exactly where the chain breaks on Apr 18-19 (`scripts/pull_topic.sh` with an offset-by-time query). Will isolate: upstream-to-DERIVED vs DERIVED-to-DB.
- Dump the `*-REPLAY-CRT` topics (`PNR-REPLAY-CRT`, `TKT-REPLAY-CRT`, …) to see if the historical backfill is still running. Empty would mean it ran once in the past; active would mean historical migration is ongoing.
- Inspect `cct-historical-data-feeds-crt` prefixes and Glue job run history (`aws glue get-job-runs`) to see if the historical pipeline is current.
- Map `cct-customer-profile-input-crt` (empty top-level currently) and `cct-entity-resolution-input-crt` (`gigya/`, `pnr/` sub-prefixes) into the Customer Profile flow described in the kb.
- `ALTEA-TKT-UAT` has zero files for all days observed. Either upstream EMH never produces to this topic, or the MirrorSource/S3Sink for it is silently broken. Worth validating with the ticket team.
- Sample messages from `cct-ingestion-{fdm,pnr}-dlq-crt` (963k combined) to see why parents never arrived — likely tells us data-quality or retry-TTL issue.

### 12.9 Parity check script (recipe)

Once the open questions are closed:

```bash
# S3 file count per feed per day
for day in 15 16 17 18 19 20 21 22; do
  aws s3api list-objects-v2 --bucket cct-data-feeds-crt \
    --prefix "pnr/emh-dev.ALTEA-PNRDATA-UAT/year=2026/month=04/day=${day}/" \
    --output text --query 'length(Contents)' \
    | awk -v d=$day '{s+=$1} END {print d, s+0}'
done

# Kafka message count per day on the corresponding topic
# (offset-by-time query via kcat)
for day in 15 16 17 18 19 20 21 22; do
  ts_start=$(date -u -j -f '%Y-%m-%d' "2026-04-${day}" '+%s000')
  ts_end=$((ts_start + 86400000))
  begin=$(kcat -b $BROKERS -Q -t emh-dev.ALTEA-PNRDATA-UAT:0:$ts_start)
  end=$(kcat   -b $BROKERS -Q -t emh-dev.ALTEA-PNRDATA-UAT:0:$ts_end)
  echo "$day S3 vs Kafka diff: $(( end - begin ))"
done
```

---

## 13. Files generated in this working session (for reference)

Kept in the tree:

- `data/pnr-last1000.ndjson` — small 1k reference sample (contains PII; keep local).
- `data/pnr-20260421-173610-n100000.ndjson` — the 100k dump used for most analysis.
- `data/corr/*.ndjson` — 50k correlated topic dumps.
- All `*.scenario_summary.csv`, `*.pnr_timelines.csv`, `*.llm_ready_samples.jsonl`, `*.flight_ops_summary.csv`, `*.coverage.csv`, `*.journeys.csv`, `*.trace_<PNR>.txt` are outputs of the scripts and can be regenerated any time by re-running the analyzers.

Rotated/retained `.err` files alongside each pull: they document retention-truncation for the empty topics — small, keep as forensic evidence.

Not kept (cleaned up during reorg): zero-byte `.ndjson` files for empty topics, `.bg.log` pull-process logs, superseded `correlated.*` 2k-sample reports.
