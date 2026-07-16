# Context — findings behind this design

This captures what four parallel exploration passes found across the existing codebases. It is the
"why" behind the framework decomposition. Sources: `cct-qa-1/` (current project), `cct-qa-1/CCT_Agent_New 2/`
(reference implementation), `cct-qa-1/reports/cct-qa-ai-evals/` (evalkit), `cct-cascade/` (analysis).

---

## 1. Current architecture (`cct-qa-1/`) — what we're replacing

The live path: `run_flow_async.py` drives the chatbot with an LLM playing a customer, a second LLM
judges the transcript, results land as `out_crt_<flow>/<TC>_result.json`, and a set of generators
emit HTML + JIRA payloads.

**How product & env are expressed today (the core problem):**
- **Product/feed = a string key** (`FLOW` env var) that indexes three hand-maintained dicts in one
  516-line file — `CFG` (paths), `BUILD` (customer persona + case builder), `JUDGE` (verdict + tool
  schema). The same flow list is **re-declared** in every report/JIRA generator. Adding a product =
  editing 3+ dicts in lockstep. No product abstraction.
- **Env (CRT vs INT) is NOT a parameter** — it's decided by *which engine module you import*:
  `run_flow_async → run_nc_crt → config_crt.json` is hardwired CRT; INT goes through a *different*
  entrypoint (`run_fd_flow.py → config.json`) that emits a **different, incompatible result schema**
  (`bot_result` vs `bot_said_eligible`), forcing `x.get(a) or x.get(b)` everywhere.

**Top maintainability pain points (drive the redesign):**
1. One giant runner + three parallel dicts that must stay in sync.
2. Two near-duplicate chat engines + a pile of dead runners (`run_fd_crt`, `run_fd_v2`, `run_anc_crt`, …).
3. Env baked into imports → CRT/INT can't be flipped with a flag, and they produce different schemas.
4. ~10 copy-pasted HTML-scraper builders; versions/sets done by **file-copy** (`_v5/_v6/_v7`, `_set3/_set8`) not parameters.
5. Hardcoded paths (absolute Windows path in `run_nc_crt.py:22`), JIRA field/component IDs, case-ID lists, 8-domain roll-up list + hand-written "finding" strings.
6. Env-var propagation is order-sensitive (`os.environ.update` must run *before* the engine import); runtime monkeypatching of `converse`/`otp_provider` to inject semaphores.
7. Verdict/output schema drift — each judge defines its own `bot_result` enum; reports hard-code per-flow branches.
8. Fragile keyword-matching OTP control flow; **Mailinator API token committed** in `config_crt.json`.

**Redesign leverage points (the fix):** a single **Product descriptor** (build + persona + judge +
schema + checkpoints + paths) registered once and consumed by runner *and* reporters; an **Env
object** (endpoint + OTP strategy + config + seed targets) passed as a parameter so one engine serves
all envs with **one result schema**; a shared **dataset/gap-doc parser**; externalized config/IDs.

**Result schema today** (`save_result`): `{ case, session, run_meta, verdict, widgets, transcript }`
— this is the starting point for the ONE canonical schema in `core/`.

---

## 2. Gap docs + seed/verify model (`CCT_Agent_New 2/`) — the reference

**`CCT_Agent_New 2/CCT_Agent_New/` is the canonical spec + engine to mirror.** Most important file:
`HOWTO_CREATE_PNR_DATA.md` — the definitive seed+verify recipe.

**Gap-doc anatomy (identical across FD/SOC/NC/ANC/Baggage/SeatChange/BookingChange/Non-MVP):**
- A canonical Miro **"spine"** (`<details class="spine">` → `<div class="spx">` rows) = the ordered
  **checkpoint catalog** for the domain. Each step: `spid` (e.g. `GLOB-01`, `GenUC-05`, `SoC-02a`),
  label, `core`/`branch`, and `spn` = how many test cases assert it. An `uncov` block lists Miro
  branches with zero coverage.
- Per-use-case **`<section class="card">`** with machine-readable attributes: `id` (`SOC_UAT-001`),
  `data-feat` (regime), `data-out` (verdict), `data-gaps`, plus a `badge req` = **systemCode**
  (`SoC-APPR-NE-01`) and scenario title. Inside: **customer intent** (opening utterance),
  **canonical Miro path coverage** = a `stagerow` of `stage` spans (`sc-cov` ✓ / `sc-miss` ✕ / `sc-na` ·)
  — this is the **per-case checkpoint vector**, a projection of the spine onto that case — the
  **gap analysis**, and the **full expected chat transcript** with embedded assertions
  (`TRIP TRACER UI VALIDATIONS`, `CLAIMS DASHBOARD VALIDATION`, masked contact `t***@gmail.com`).
- **Bound DATA** (datagrid): `PNR, pnrId, Passenger, Route, systemCode, Amount, Ticket, flags`
  (+ domain extras: NC old→new name; SeatChange reason code + seat; BookingChange VOL/INVOL + delay +
  rebooked; Baggage feature→outcome; Non-MVP expected routing Team).

**Two-source seed + verify model:**
1. **Booking → trip-tracer Aurora**, reached by **publishing a PNR to Kafka** (`emh-*.ALTEA-PNRDATA-*`)
   which cascades (~30s) into `trip / trip_details / passenger / flight_segment / eds_pnr_output`.
2. **DDS verdict** (eligibility + amount) → written to **S3** and **pinned** in the rule-engine
   `execution_traces` table, served by `/rule-engine/dds/output/<pnrId>`.
   ⚠️ **`dds_pnr_output` in trip-tracer is a decoy — the bot does NOT read it.**

A case is "seeded" only when both sources land, and "verified" only when a per-domain **checkpoint
auditor** prints `PASS ✅`. Verification is **systemCode-match** (validates NOT_ELIGIBLE / ND / PENDING
too, not just eligible). Phase pipeline is idempotent: `index → clone → publish → checkcascade →
finalize → verify`. UPDATE cases (name/seat/segment change) need a **CREATE prelude** first (the
change detectors FK to a parent a bare UPDATE has no parent for).

**The "only email + phone" insight (confirmed):** in the SIT generators the bound data (PNR, pax,
route, ticket, amount, systemCode) are "from-file" values, but **email, phone, OTP, Aeroplan#,
banking are placeholders** — the only fields NOT in the data file. The `eds_pnr_output` contact is
the **OTP gate**: the bot's `stepup.py` sends the code to the seeded contact, so if it isn't the
tester's real inbox, every case stalls at auth. → **User supplies exactly `{email, phone}`**; the
framework injects it as the contact on every seeded PNR; everything else derives from the gap doc.

**Note:** the per-domain `*_checkpoints.py` auditors and `crt_fd_build*.py` builders are *referenced*
by the HOWTO but **not physically present** — they must be rebuilt from the checkpoint-area lists.

---

## 3. evalkit (`reports/cct-qa-ai-evals/`) — the metrics layer (P5)

Self-contained stdlib-only Python package; deterministic (byte-identical on rerun). Job: turn each
run's messy artifact folder into **one identically-shaped `report.html` + schema-versioned
`metrics.json`** so results compare across products/envs/reruns.

- **`adapters.py`** — one loader per artifact format → normalized `EvalRecord`. **The only file you
  touch to onboard a new product.** (alpha = `*_result.json`+`*_transcript.md`; bravo = `*_qa_report.json`+`*_chat_transcript.md`.)
- **`taxonomy.py`** — flow-stage detectors, anomaly detectors, intent regex, check canonicalizer —
  tightly coupled to each bot's transcript dialect (a new product needs its own regex block).
- **`trajectory.py`** — deterministic transcript analysis → stages reached, anomalies, intent, and a
  `score` = longest-in-order coverage of the expected flow.
- **`metrics.py`** — pure arithmetic → `metrics.json` (`SCHEMA_VERSION`). Metrics: `goal_success`
  (judge's own), `rescored_success` (judge-independent: status match AND amount match),
  `decision_accuracy` (+ confusion matrix), `amount_accuracy`, `intent_recognition`, `trajectory_match`.
- **`report.py`** — fixed 8-section "alpha" HTML; `render_comparison` for N agents side-by-side.
- **`gate.py`** — CI floors + regression-vs-baseline, merge-blocking exit code.
- **`coverage.py`** — evidence-based use-case coverage matrix.

**`metrics.json` is the stable integration seam** — analysis (P6) and UI (P7) read it, never the HTML.
Gaps to fix at scale: floors are hardcoded module constants (externalize per product/env); **no
cross-run aggregation / time-series**; env is a label, not a first-class dimension.

---

## 4. cct-cascade — the analysis patterns (P6/P7)

CONTRAIL (Python grading/aggregation) + reactor (Rust API + React dashboard over a persisted evidence
store). Principle: **a deterministic summary is the source of truth; the LLM is an optional
interpretation layer.**

**Patterns worth carrying in:**
1. **Structured scenario-id namespace** (`feed.domain.case`) → free, consistent product/feature rollups.
2. **Grade taxonomy** beyond PASS/FAIL: `Strong PASS`, `Weak PASS`, `Invalid PASS`, `Valid FAIL`,
   `Harness FAIL`, `Environment TIMEOUT`, `Environment ERROR` — separates product vs harness vs env vs
   weak-evidence failures. Makes pass-rate trustworthy.
3. **Pass-rate over "working" tests only** (PASS+FAIL); TIMEOUT/ERROR = infra noise surfaced
   separately; SKIPPED/INVALID/in-flight excluded from the denominator.
4. **Machine-coded findings** `{level, code, message, severity}` with stable codes
   (`PASS_WITH_FAILED_ASSERTION`, `PASS_WITHOUT_DOWNSTREAM_EVIDENCE`, …), counted at batch level to
   reveal systemic issues.
5. **Confidence score 0–100** per run (base per grade − finding penalties).
6. **Three cheap clusterings**: reason-string `Counter`, `(family, predicate)` timeout clusters,
   payload-hash reuse detection.
7. **Deterministic-first, LLM-optional** explanations (cached, never source of truth).
8. **Snapshot-and-name saved reports** for comparison — cascade's weakest area is the **missing
   run-over-run scenario diff** (previous terminal outcome vs current → newly-failing / newly-passing /
   still-failing). **This framework should add that.**

Report formats: JSON API as the contract, a React SPA (pure SVG/CSS, no chart lib), and a Markdown
executive summary (`TEST-SUMMARY-REPORT.md`).

---

## Design implications (summary)

- **One canonical result schema** (P0) end-to-end kills the dual-schema `.get(a) or .get(b)` mess and
  lets evidence/metrics/analysis be uniform.
- **Descriptor + registry** (P0): a feed/product/env is declared once; runner, seeder, reporter,
  analyzer all consume the same descriptor. This is the "generic file per feed, swap product/env".
- **Gap doc is the single source of truth** (P1): one parser → use-cases with checkpoint vectors +
  bound data + expected transcripts. Seeding, verification, expected-outcomes, and coverage all read it.
- **Only `{email, phone}` at runtime** (P2): injected as the OTP-gating contact; everything else derives.
- **Verify by systemCode-match** against both sources before running the bot — so a failure is proven
  to be the bot, not missing data (exactly the third-party/BOUCHARD-class issues we hit).
- **Scenario-id namespace `product.env.feed.case`** → free rollups by all four axes + date.
- **metrics.json is the seam**; analysis adds the **run-over-run diff** cascade lacks; UI renders the
  four-axis browse over the JSON contract.
