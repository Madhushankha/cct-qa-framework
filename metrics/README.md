# P5 — metrics (evalkit integration)

**The standardized, deterministic scorecard.** For each `(product, env, feed, date)` run, produce one
schema-versioned `metrics.json` + `report.html` via **evalkit** — the byte-stable metrics engine that
already exists. Mostly integration, not new code.

## Why (req #4)
evalkit is a solved, deterministic metrics/report layer; `metrics.json` is the stable seam that
analysis (P6) and UI (P7) read. See [`../docs/context.md`](../docs/context.md) §3.

## What it does
- Provides **one evalkit adapter** for the canonical `Result` schema (P0) → evalkit's normalized
  `EvalRecord`. Because we have ONE schema now, there's one adapter, not per-env adapters.
- Registers each product's **transcript dialect** in evalkit's taxonomy (stage/anomaly/intent regex)
  so trajectory/intent metrics work per product.
- Runs `evalkit.run_eval` per run folder → `metrics.json` (goal_success, rescored_success,
  decision_accuracy + confusion matrix, amount_accuracy, intent_recognition, trajectory_match) +
  `report.html`; `evalkit.coverage` → coverage matrix; `evalkit.gate` for CI floors.
- **Externalizes** evalkit's hardcoded floors/targets to per-(product, env) config.

## Inputs / outputs
- **In:** a run's canonical `Result` set + transcripts (P3).
- **Out:** `metrics.json` (the integration seam) + `report.html` + `coverage.{csv,html}` per run;
  gate exit code for CI.

## Design notes
- Keep evalkit vendored/unforked where possible; contribute the adapter + taxonomy block + externalized floors.
- `metrics.json` keyed by the scenario-id namespace so P6/P7 can roll up by any axis.

## Harvest from
`cct-qa-1/reports/cct-qa-ai-evals/` (the whole evalkit package; add an adapter + taxonomy dialect).

## Status
Design. Build after P4 (can overlap).
