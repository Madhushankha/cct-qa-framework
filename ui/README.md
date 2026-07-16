# P7 — ui (dashboard)

**See the results.** A web UI to browse test results by **date / product / env / feed**, drill into a
case's evidence + chat, and view trends, grades, findings, and run-over-run diffs. A thin renderer over
the analysis (P6) + metrics (P5) JSON contracts.

## Why (req #6)
"Need a UI that can see test results … date-wise, product, env as well." Today results are loose HTML
files with no index. See [`../docs/context.md`](../docs/context.md) §4.

## Views
- **Overview** — a `product × env × feed` matrix for a date/window: pass-rate (working-only), grade
  mix, run count. Filter by any axis.
- **Feed detail** — the expected-vs-actual table + checkpoint coverage; click a case → its evidence HTML (P4).
- **Trends** — pass/fail time-series, per-scenario sparklines, grade-mix over time.
- **Diff** — newly-failing / newly-passing / still-failing between two runs (from P6).
- **Findings** — systemic finding counts + clusters (timeout clusters, common reasons).
- **Seed health** — checkpoint PASS/FAIL per feed (from P2) so data issues are visible before blaming the bot.

## Inputs / outputs
- **In:** analysis JSON (P6), metrics.json (P5), links to evidence HTML (P4).
- **Out:** the browsable app; deep-links per `(product, env, feed, date, case)`.

## Design notes
- **Thin renderer over the JSON contract** — no analysis logic in the UI (cascade principle).
- Prefer a small stack (the cascade reactor dashboard is pure SVG/CSS React, no chart lib) — reuse its components.
- Live updates optional (SSE) later; static-read first.

## Harvest from
`cct-cascade/reactor/dashboard/src/` (React components: OutcomeBar/Pie, MetricCard, LiveTable,
EnvSwitch, AnalyticsCharts, AuditFindings) + its JSON API shape.

## Status
Design. Build after P6.
