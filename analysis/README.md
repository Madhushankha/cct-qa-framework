# P6 — analysis (cascade-style)

**Turns runs into insight.** Reads `metrics.json` (P5) + the canonical `Result` set across runs and
produces graded, clustered, trend-aware analysis keyed by **date / product / env / feed** — including
the **run-over-run diff** that cct-cascade lacks.

## Why (req #5)
Raw PASS/FAIL isn't actionable. cct-cascade's grading + clustering separate product defects from
harness/env noise and reveal systemic issues. See [`../docs/context.md`](../docs/context.md) §4.

## What it produces
- **Grade taxonomy** per case: `Strong PASS / Weak PASS / Invalid PASS / Valid FAIL / Harness FAIL /
  Environment TIMEOUT / Environment ERROR` — plus a **confidence score 0–100** per run.
- **Trustworthy pass-rate**: over *working* tests only (PASS+FAIL); infra noise surfaced separately.
- **Machine-coded findings** `{level, code, message, severity}` counted at aggregate level to reveal
  systemic problems (e.g. "18 cases: eligible determination in DDS but bot escalated").
- **Three clusterings**: reason-string `Counter`, `(family, predicate)` timeout clusters, payload-hash reuse.
- **Run-over-run scenario diff** (the new bit): previous terminal outcome vs current →
  **newly-failing / newly-passing / still-failing** sets, keyed by scenario id.
- **Rollups**: by date (rolling windows + buckets), product, env, feed; time-series pass/fail.
- Deterministic-first; an **optional** LLM interpretation layer (cached, never source of truth).

## Inputs / outputs
- **In:** `metrics.json` per run + `Result` sets (for findings/evidence-completeness) + history store.
- **Out:** an analysis JSON document per query (`{summary, perf, by_axis, findings, clusters, diff}`) —
  the contract the UI (P7) renders. Optional Markdown executive summary.

## Design notes
- **JSON API is the contract** (like cascade) so analysis is reusable headless (CI, alerts, exports).
- Persist runs in a small store (SQLite/DuckDB) keyed by scenario id + date for cheap cross-run queries.
- Evidence-completeness: downgrade a PASS that lacks inject/downstream/DDS evidence (ties back to P2).

## Harvest from
`cct-cascade/contrail/audit/batch.py` (grades, findings, clustering), `analysis/result_explanations.py`
(reason grouping, LLM-optional), `reactor/.../report.rs`/`perf.rs` (window/timeseries computation).

## Status
Design. Build after P5.
