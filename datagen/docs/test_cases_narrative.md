# PNR Event Pipeline — QA Test-Case Narratives

Generated from `pnr-20260421-173610-n100000.llm_ready_samples.jsonl` (100k messages window, 2,509 complete-history PNRs).

Each scenario section contains:

- **What it is** — the real pattern observed in production.
- **Reference PNRs** — live examples from the sample (anonymized by PNR only; no PII).
- **Test cases** — numbered, each with preconditions / action / expected result / edge cases.
- **Monitoring suggestions** where the pattern hints at operational issues rather than a feature.

The universal invariants from every scenario (apply to *every* test case) are listed once at the end as "cross-cutting invariants."

---

## S0 — Creation-only (897 PNRs, 36%)

**What it is.** A PNR is created and no further activity occurs in the window. The stream shows exactly one logical `PNR_CREATION` event (emitted twice at-least-once).

**Reference PNRs.**
- `AKHJWU` — origin Amadeus London (`LON1A0955`), first observed at `data.version=40`, 0.014s span between duplicates.
- `A3HUCS` — same origin, `version=8`, 0.031s span.
- `BCO92G` — Amadeus Nice (`NCE1A01FF`), `version=21`, 0.018s span.

**Why it matters.** First-observed version ≠ 1. The consumer sees these PNRs appear at arbitrarily high versions (v8, v21, v40) — it has no history of what happened before. The downstream event-detection service must treat "first observation = PNR_CREATION" as "new to me" regardless of the absolute version number.

**Test cases.**

| # | Action | Expected |
|---|---|---|
| TC-S0.1 | Emit a single `PNR_CREATION` at version=1 for a previously-unseen PNR | Downstream registers PNR; no customer notification (this is operational create, not customer action) |
| TC-S0.2 | Emit `PNR_CREATION` at version=47 for a previously-unseen PNR (gap in history) | Same outcome as TC-S0.1. No "missing versions" warning. No replay request. |
| TC-S0.3 | Emit `PNR_CREATION` for a PNR that *already* has history in the consumer store | Treat as idempotent: existing record updated in place, no duplicate downstream event. |
| TC-S0.4 | Emit `PNR_CREATION` twice (at-least-once duplicate) within 20ms | Exactly one downstream effect. |

---

## S1 — New simple booking (4 PNRs)

**What it is.** Fresh PNR with 1–3 segments and nothing else. Rare in this window because almost every new booking is accompanied by an SSR, codeshare link, or tagging (→ S4/S5/S8a).

**Reference PNRs.**
- `A5FODU` — origin United Houston (`IAHUA1TTY`, UA system). Sequence: `[v3] SEGMENT_ADDED` then `[v4] PNR_CREATION` — segments arrive *before* creation in stream order (version-wise still consistent).
- `A85GPW` — AC Montreal (`YULAC0986`). 5.8 min to first downstream operational update (`SEGMENT_STATUS_UPDATE` + `FLIGHT_NUMBER_UPDATE`).

**Test cases.**

| # | Action | Expected |
|---|---|---|
| TC-S1.1 | PNR created with a single AC-operated, AC-marketed segment | One downstream "new booking" event, typed as direct-AC. |
| TC-S1.2 | SEGMENT_ADDED events arrive *before* PNR_CREATION in partition order (v3 before v4) | Consumer buffers by PNR and reorders by `data.version` before processing. No "orphan segment" error. |
| TC-S1.3 | PNR created at a partner GDS point-of-sale (`IAHUA1TTY`, `1A...`, `OS...`) | Different downstream routing vs AC-originated PNRs (`...AC...`). |

---

## S2 — Rebooking (104 PNRs, 4%)

**What it is.** Itinerary change: segments removed and added in the same logical version. The signature is at least one `SEGMENT_REMOVED` paired with `SEGMENT_ADDED`.

**Reference PNRs.**
- `A575V9` — United Houston (UA). Clean rebook: v2 create → v4 `SEGMENT_ADDED SEGMENT_REMOVED SEGMENT_ADDED SEGMENT_REMOVED` in 10 seconds.
- `AWOZV5` — AC Vancouver. Create at v3 → 2.7 min later, massive rebook block at v4: 4 remove/add pairs + REMARK_ADDED + SPECIAL_KEYWORD_UPDATED.
- `ABQHA6` — AC São Paulo. **Outlier**: 12 versions, 84 raw events, 22.9-hour span. Keyword/remark churn interleaved with rebooks across v1 → v21. The `[v15]...[v14]` in the signature shows event arrival out of version order — a real stress test for the consumer's reorder logic.

**Test cases.**

| # | Action | Expected |
|---|---|---|
| TC-S2.1 | `[v4]` batch of 4 events (2× SEGMENT_REMOVED + 2× SEGMENT_ADDED) emitted in one transaction | One downstream `FLIGHT_CHANGE_VOL` event, not four. |
| TC-S2.2 | Same batch emitted twice (at-least-once) | Exactly one downstream. |
| TC-S2.3 | SEGMENT_ADDED arrives before matching SEGMENT_REMOVED within v4 | Aggregator reorders; outcome identical to TC-S2.1. |
| TC-S2.4 | Version v15 arrives before v14 in partition order (real case: ABQHA6) | Consumer reorders by `data.version` before fold. |
| TC-S2.5 | 22-hour rebook cycle (v1→v21 with mixed tagging/remark events between) | Each version produces one downstream event — no collapsed history, no cross-version fold. |
| TC-S2.6 | Remove all existing segments + add one replacement in same version | Downstream: `FLIGHT_CHANGE_VOL` not `PARTIAL_CANCELLATION`. |

---

## S3 — Cancellation, no replacement (789 PNRs, 31% — dominant pattern)

**What it is.** One or more `SEGMENT_REMOVED` events with zero `SEGMENT_ADDED`. May be partial (some segments remain) or full (all segments removed).

**Reference PNRs.**
- `A6XTRX` — AC Montreal (`YULAC0980`). Clean and minimal: v6 create → v9 single SEGMENT_REMOVED. 27s total span.
- `A89DPH` — same office. Create + SSR + cancel within 70s. Real workflow: "book a thing with accessibility request, then cancel".
- `8OCACT` — **full-cancellation outlier**: Amadeus Madrid (`MADID3002`). 62min span, 52 raw events. v12 fires 4× SEGMENT_REMOVED plus 8× REMARK_REMOVED plus CONTACT_REMOVED — essentially "burn the booking to the ground". The REMARK_REMOVED storm indicates this is not a "graceful cancel" but a full wipe.

**Test cases.**

| # | Action | Expected |
|---|---|---|
| TC-S3.1 | Single SEGMENT_REMOVED on a 3-segment PNR | Downstream `PARTIAL_CANCELLATION` event. No customer refund kicked off. |
| TC-S3.2 | All 3 segments removed in one version | Downstream `FULL_CANCELLATION`; refund workflow initiated. |
| TC-S3.3 | Cancel → rebook within 10 minutes (S3→S2 transition) | If second version carries SEGMENT_ADDED, the detection system should emit `REBOOKING` not `CANCELLATION`. Verify time/version window. |
| TC-S3.4 | Full-wipe pattern: SEGMENT_REMOVED + multiple REMARK_REMOVED + CONTACT_REMOVED (case `8OCACT`) | Cancellation workflow should not panic on the cascade of remark/contact removals. No duplicate refund. |
| TC-S3.5 | SEGMENT_REMOVED on a codeshare segment | Cancellation event must include partner-airline association so partner GDS gets notified too. |
| TC-S3.6 | Cancel-then-recreate with a new PNR number (split scenario) | Link old → new via split/group association rather than treating as unrelated. |

**Capacity check:** S3 is 31% of complete-history PNRs. Cancellation path is the single hottest test surface — over-invest here.

---

## S4 — New booking with codeshare (271 PNRs, 11%)

**What it is.** PNR created and includes at least one `CODESHARE_OTHER_AIRLINE_ASSOCIATION` event — a segment marketed by one carrier, operated by another.

**Reference PNRs.**
- `A6XIT7` — United Denver (`DENUA1RIS`). Codeshare association fires at v0 *before* PNR_CREATION at v3 (system registers the codeshare tag before the record is formally created — a pre-creation race the consumer must handle).
- `AHPJDU` — United Houston, flagged country `JP`. Codeshare at v0, create at v1, cancel by v5 — suggests a quickly-abandoned booking.
- `A8JFZP` — AC Toronto (`YYZAC01BT`). 3.7-day span, 46 events across 5 versions. Full lifecycle: create → massive segment churn (v3) → codeshare add (v4) → SSR bundle (v5) → segment status updates (v6). Good end-to-end regression case.

**Test cases.**

| # | Action | Expected |
|---|---|---|
| TC-S4.1 | CODESHARE_OTHER_AIRLINE_ASSOCIATION at v0, PNR_CREATION at v1 | Consumer holds codeshare tag until create lands, then applies. No orphaned codeshare. |
| TC-S4.2 | AC-marketed, UA-operated segment | Customer-service ownership = AC (marketing carrier); disruption events from UA auto-routed to AC. |
| TC-S4.3 | Codeshare segment cancelled (S3 + S4) | Partner's GDS receives cancellation notification within SLA. |
| TC-S4.4 | Codeshare re-associated on an existing segment after flight number change | Verify downstream carrier notifications don't duplicate. |

---

## S5 — New booking with SSR (149 PNRs, 6%)

**What it is.** PNR creation followed by 1-N `SPECIAL_SERVICE_REQUEST_ADDED` events. SSR codes in production include WCHR/WCHC/WCHS (wheelchairs), VGML/KSML (meals), UMNR (unaccompanied minor), MEDA/STCR (medical), DOCS (travel documents).

**Reference PNRs.**
- `A8SNV9` — AC Montreal. Minimal: v1 create → v2 SSR within 2.8 seconds. Likely agent adding wheelchair request right after booking.
- `BJHXFO` — Amadeus Nice. 4 SSRs added at v8, 10 minutes after creation.
- `8EVH43` — Amadeus London Singapore Airlines (`LONSG38CS`). **Storm pattern**: 98 raw events in 29 seconds — mass contact + remark + SSR additions all in v3 before PNR_CREATION at v8. Probably a bulk-loader / migration job, not a live agent.

**Test cases.**

| # | Action | Expected |
|---|---|---|
| TC-S5.1 | PNR_CREATION + WCHR SSR within 5 seconds | Downstream ops-system picks up accessibility request; wheelchair assignment workflow triggered at the airport. |
| TC-S5.2 | 4 SSRs added in one version | All 4 preserved individually; not deduped by PNR. |
| TC-S5.3 | SSR + PNR_CREATION arrive in reversed partition order (SSR first, create second — `8EVH43`) | Consumer buffers SSRs until creation arrives; no "orphan SSR" DLQ message. |
| TC-S5.4 | Conflicting SSRs: WCHR + WCHS (ambulatory and stretcher) for same traveler | Validation raises conflict flag, not silent last-write-wins. |
| TC-S5.5 | MEDA (medical) SSR with free-text | Text stored encrypted / access-controlled. Not logged in CloudWatch. Not emitted in derived events without PII masking. |
| TC-S5.6 | SSR update (not add): `SPECIAL_SERVICE_REQUEST_UPDATED` after initial add | Downstream treats as modification, not duplicate add. |

---

## S6 — Seat-only change (11 PNRs)

**What it is.** Pure seat assignment add/update, no segment or contact changes.

**Reference PNRs.**
- `BN956E` — Amadeus London. v16 create → v17 SEATING_UPDATED. Customer changed a seat mid-trip (v16 is high, so PNR existed before our window).
- `AKP5RQ` — Amadeus Nice. v34 create → v36 with 4 seat updates — probably a seat map change by the carrier.
- `AQWD5X` — AC Toronto. v3 contact additions → v5 seat additions + remarks → v6 PNR_CREATION. Out-of-order stream; creation comes last.

**Test cases.**

| # | Action | Expected |
|---|---|---|
| TC-S6.1 | Single SEATING_UPDATED | Downstream does *not* emit customer-facing notification (seat changes are too frequent to alert on). |
| TC-S6.2 | Bulk SEATING_ADDED (seat map reassignment on an aircraft swap) | Treated as operational event, not customer action. Aggregated into one `AIRCRAFT_SWAP` signal if accompanied by SEGMENT_UPDATED on same segment. |
| TC-S6.3 | Seat change that implies cabin-class upgrade | Extract cabin change from SEATING_UPDATED diff; emit to `CABIN-CHANGE-CRT` topic. |
| TC-S6.4 | Seat change on a PNR with UMNR SSR (unaccompanied minor) | Verify seat location rules (no exit row, etc.); fail loudly if violated. |

---

## S7 — Contact storm (4 PNRs) **[INVESTIGATE — likely bug]**

**What it is.** A PNR emits 60+ CONTACT_ADDED/CONTACT_REMOVED events within a second or two, all at the same logical version. Zero segment/SSR activity surrounds it.

**Reference PNRs.**
- `AB48TJ` — AC Toronto (`YYZAC002A`). **62 raw events, 3 logical events, 1.2 seconds.** Every contact add is immediately removed and re-added; the pattern looks like a sync loop.
- `AAZE3O` — same office. **74 raw events, 3 logical, 1.3 seconds.** Same signature.
- `855WXM` — Austrian Vienna (`VIEOS08BC`). Cleaner: 8 events / 3 versions / 66s — a legitimate contact update.

**Assessment.** Not a feature. This is almost certainly an upstream sync loop — probably Gigya/iFly/loyalty feed re-emitting contact state churn. Two storm examples are from the same AC office (`YYZAC002A`) which hints at a specific process (backfill job, nightly sync, or a PNR refresh loop).

**What to do:** don't test as a "feature" — **add monitoring** and reduce the noise at source.

| # | What to build | Spec |
|---|---|---|
| M-S7.1 | Alarm: `pnr.contact_events_per_second > 20` for any PNR for >5 seconds | Page owning team (loyalty / customer-profile). |
| M-S7.2 | Coalescing filter in `EVENT-DETECTION-PNR-CRT` | If ≥N add/remove pairs for the same PNR/version within T seconds, emit one `CONTACT_CHURN_DETECTED` event instead of N, and annotate the origin office. |
| M-S7.3 | Ticket for platform team | Investigate upstream system emitting contact churn on PNRs originating from YYZAC002A. |

---

## S8a — New booking with tagging (251 PNRs, 10%)

**What it is.** PNR_CREATION + at least one SPECIAL_KEYWORD_* or REMARK_* event, with no structural PNR changes. Agents tagging notes and operational keywords at booking time.

**Reference PNRs.**
- `CDSLU8` — Amadeus London. v47 create → v50 REMARK_ADDED, 32.7 hours later — agent came back to annotate an existing booking.
- `AJ4386` — AC Washington (`WASAC07TA`). Keywords added at v1 (before create at v4), then more keywords at v5. Multi-stage tagging.
- `AD7ZBF` — AC Sydney (`SYDAC07TA`). v3 create → v4 with 14 REMARK_ADDED + 10 SPECIAL_KEYWORD_ADDED — bulk tagging immediately on creation (probably agent using a template).

**Test cases.**

| # | Action | Expected |
|---|---|---|
| TC-S8a.1 | REMARK_ADDED on an existing PNR, days after creation | Downstream routes the remark to the agent notes system; no customer-facing event. |
| TC-S8a.2 | Bulk tagging: 10+ keywords in one version (`AD7ZBF`) | Accepted as one batch; downstream emits one `PNR_ANNOTATED` signal, not 10. |
| TC-S8a.3 | Keyword arrives before creation (`AJ4386`) | Buffered, applied when creation lands. |
| TC-S8a.4 | Regulatory keyword (e.g., UMNR, VIP, SSR-linked keywords) | Different downstream routing than generic agent note. |
| TC-S8a.5 | SPECIAL_KEYWORD_REMOVED after an ADD | Verify audit trail preserves both (agent action history). |

---

## S11 — High-churn PNR (1 PNR)

**Reference:** `AQ6R6I` — Amadeus Nice (`NCE1A0238`, different office code than the earlier NCE). 4 logical versions in 4.8 minutes, intermingled segment status / flight time / segment updates across v2 → v3 → v5 → v7. PNR_CREATION arrives last at v7, despite being logically the earliest version.

**Test case — reorder stress.**

| # | Action | Expected |
|---|---|---|
| TC-S11.1 | Replay AQ6R6I sequence in observed (partition) order: v2 → v3 → v5 → v7 | Consumer buffers everything until v7 (creation) arrives, then applies in version order. Final state matches v7. |
| TC-S11.2 | Replay with random shuffle of the 16 events within the window | Same final state regardless of partition-level arrival order. |

---

## S12 — Flight operational update (12 PNRs)

**What it is.** Carrier-pushed flight changes affect an existing PNR — flight time update, flight number swap, segment status change. Not agent-driven.

**Reference PNRs.**
- `AFBF72` — United Houston (`IAHUA1TTY`). 21-hour span. v0 codeshare, v1 flight time update, v5 PNR_CREATION (creation arrives after the ops updates).
- `A8ATAB` — AC Montreal (`YMQAC010C`). Flight status + update + contact churn within 4.4min of creation.
- `Y6YG72` — Frankfurt (`AWBN`, system `F1`). **46 raw events in 65 seconds.** Carrier-driven storm: codeshare tag → flight time → SSRs → 16× seating added → 16× seating updated → creation. This is aircraft swap cascading through every seat.

**Test cases.**

| # | Action | Expected |
|---|---|---|
| TC-S12.1 | FLIGHT_TIME_UPDATE on a segment with confirmed passengers | Downstream emits `FLIGHT-CHANGE-INVOL-CRT` → customer SMS/email. |
| TC-S12.2 | SEGMENT_STATUS_UPDATE: "HK" → "UN" (unable) | Auto-rebook workflow initiated. |
| TC-S12.3 | Aircraft swap (16× seat changes in one version, like `Y6YG72`) | Aggregated to one `AIRCRAFT_SWAP` event. Customer is notified once, not 16 times. |
| TC-S12.4 | FLIGHT_NUMBER_UPDATE for a codeshare segment | Both operating and marketing flight numbers updated; partner GDS notified. |
| TC-S12.5 | Flight updates arrive before PNR creation (`AFBF72`) | Consumer buffers updates; applies on creation; no "flight change on non-existent PNR" error. |

---

## S13 — Passenger name change (2 PNRs) **[REGULATORY]**

**Reference PNRs.** Both from AC Montreal office `YULAC00DC`. Both follow the identical pattern:

```
[v3-4]  PNR_CREATION
[v4-5]  PASSENGER_NAME_CHANGE × 2 + CONTACT_ADDED + PASSENGER_NAME_CHANGE × 2 + CONTACT_ADDED
[v6-7]  SEGMENT_REMOVED × 4
```

12-15 seconds end to end. The identical shape across two independent PNRs suggests this is a specific workflow (not ad-hoc): **create PNR → correct name(s) + attach contact → cancel segments.** This looks like a booking-made-in-error flow.

**Test cases.**

| # | Action | Expected |
|---|---|---|
| TC-S13.1 | Name correction (spelling fix: "Jon" → "John") | Updated name propagated; **no re-vetting** required (DGR/Secure Flight interprets as correction). |
| TC-S13.2 | Actual name change (swap traveler: Jane Doe → John Smith) | Flagged for full re-vetting; Secure Flight lookup re-run; compliance log entry. |
| TC-S13.3 | Name change followed by immediate cancellation (the observed pattern) | Cancellation completes; name-change audit trail preserved for regulatory query. |
| TC-S13.4 | Multiple PASSENGER_NAME_CHANGE in one version (duplicate emission) | Treated as one logical name change; one re-vetting lookup. |

---

## S14 — Split / group PNR (0 PNRs observed; rule ready)

Not seen in this window. When seen: `SPLIT_PNR_ASSOCIATION` or `GROUP_PNR` events. Split = one PNR becomes two (e.g., travelers separating); Group = a group booking linked.

**Test cases (pre-written for when events appear).**

| # | Action | Expected |
|---|---|---|
| TC-S14.1 | SPLIT_PNR_ASSOCIATION emitted for PNR A → spawns PNR B | Consumer links A↔B; downstream notifications reference both. |
| TC-S14.2 | GROUP_PNR with 10 travelers | One group event, not 10 individual booking events. |

---

## Cross-cutting invariants (apply to every test above)

| ID | Property | Rationale / evidence |
|---|---|---|
| I1 | **At-least-once emission** — every logical event appears 2x within <100ms | Universal across all 2,509 PNRs. Dedupe key: `(entityId, version, eventName)` or `event.id` (UUID). |
| I2 | **Multiple events share a logical `data.version`** | Version is the transaction identifier; group by it before processing. |
| I3 | **First observed version ≠ 1** — PNR can enter the stream at any version | E.g., `AKHJWU` enters at v40. |
| I4 | **Partition arrival order ≠ version order** | Observed in S1, S4, S6, S11, S12. Consumer must reorder by `data.version`. |
| I5 | **Null / tombstone records exist on this topic** | ~6% of offsets have null payload. Parser must skip, not DLQ. |
| I6 | **Mixed-entity topic** — OAG_STATUS flight events share this topic with PNR events | Route by presence of `data.pnr` vs `payload.value.eventName=='OAG_STATUS'`. |
| I7 | **Point-of-sale identifies the origin system** — AC/1A/UA/OS/F1 system codes, office IDs map to airports/GDSes | Test cases must cover at least AC (direct), 1A (Amadeus), UA (Star Alliance partner) to avoid system-specific bugs. |
| I8 | **Duplicate-emission doubles raw counts** — `n_events_raw` ≈ 2× `n_events_logical` | Classifier and test assertions must use logical counts. |

---

## Suggested coverage targets

| Priority | Scenarios | Rationale |
|---|---|---|
| P0 (must-have) | S3, S0, I1, I3, I4, I5 | 67% of production traffic, plus the invariants that break every downstream consumer if wrong. |
| P1 (high) | S4, S5, S2, S8a, S12 | Common daily flows. |
| P2 (medium) | S1, S6, S13 | Less common but regulatory (S13) or important edge (S1). |
| P3 (monitor, not test) | S7 | Add alerts and coalescing filter rather than feature tests. |
| P4 (stub) | S14 | Skeleton tests ready for when data appears. |
