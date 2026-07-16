# Architecture

The framework is a **linear pipeline of small, independently-testable modules** joined by two stable
contracts: the **`Result` schema** (P0) and **`metrics.json`** (evalkit / P5). Everything is keyed on
`(product, env, feed, date)` via a structured scenario id `product.env.feed.case`.

## Data flow

```
                    ┌─────────────┐
   gap-doc HTML ───▶│ P1 catalog  │── Catalog{checkpoints, cases[UseCase{SeedSpec, checkpoint-vector, expected}]}
                    └─────────────┘
                          │
        {email, phone} ───┤
                          ▼
                    ┌─────────────┐   seed both sources (Kafka→Aurora, DDS→S3+execution_traces)
                    │ P2 seed+ver │── seed-verification (checkpoint PASS/FAIL) ─────────┐
                    └─────────────┘                                                    │ go/no-go
                          │ seeded bookings + DDS pins                                 │
                          ▼                                                            ▼
   descriptors ────▶ ┌─────────────┐   drive chatbot (persona) + judge          ┌───────────┐
   (P0 registry)     │ P3 runner   │── Result{case,session,run_meta,verdict,     │  gate     │
                     └─────────────┘        widgets,transcript} (canonical)      └───────────┘
                          │
             ┌────────────┼─────────────────────────┐
             ▼            ▼                          ▼
        ┌─────────┐  ┌─────────┐               ┌──────────┐
        │P4 evid. │  │P5 metrics│── metrics.json│  history │ (SQLite/DuckDB, keyed scenario-id + date)
        │  HTML   │  │ (evalkit)│               │  store   │
        └─────────┘  └─────────┘               └──────────┘
             │            │                          │
             │            └───────────┬──────────────┘
             │                        ▼
             │                  ┌───────────┐  grades, confidence, findings, clusters,
             │                  │P6 analysis│── run-over-run diff, rollups → analysis JSON
             │                  └───────────┘
             │                        │
             ▼                        ▼
        ┌─────────────────────────────────────┐        ┌──────────┐
        │ P7 ui (browse date/product/env/feed) │        │ P8 jira  │ (Valid FAIL → ticket + proof)
        └─────────────────────────────────────┘        └──────────┘
```

## The two contracts (integration seams)

1. **`Result` schema (P0)** — canonical, env-agnostic, versioned. Produced by the runner (P3);
   consumed by evidence (P4), metrics (P5), analysis (P6), jira (P8). Kills the current
   `bot_result`-vs-`bot_said_eligible` dual-schema mess.
2. **`metrics.json` (P5 / evalkit)** — deterministic, schema-versioned. The only thing analysis (P6)
   and UI (P7) read for scores. Never read the HTML.

## Module boundaries (one clear purpose each)

| Module | Does | Depends on | Testable in isolation via |
|---|---|---|---|
| core | descriptors + schema + registry | — | schema validation, registry lookups |
| catalog | gap-doc HTML → use-cases | core | fixture gap docs → expected model |
| seed | inject {email,phone}, seed+verify | core, catalog | recorded fixtures / dry-run against test env |
| runner | drive bot + judge → Result | core, catalog, (seed) | mocked chat client + judge |
| evidence | Result → HTML | core | golden HTML from fixture Results |
| metrics | Result → metrics.json | core (+ evalkit) | evalkit's own deterministic tests |
| analysis | metrics+Result → analysis JSON | core | fixture runs → expected grades/diff |
| ui | render analysis/metrics JSON | — (HTTP) | component tests over fixture JSON |
| jira | Valid FAIL → ticket | core, analysis, evidence | dry-run payload golden |

## Gap-doc updates → incremental work (living source of truth)

The gap doc is versioned. On a new version, the catalog (P1) diffs against the last and emits a
`ChangeSet`, which gates the expensive downstream steps:

```
new gap-doc  ──▶  P1 catalog.diff(old,new)  ──▶  ChangeSet{per case: ADDED|DATA_CHANGED|
                                                  CHECKPOINT_CHANGED|EXPECTED_CHANGED|REMOVED|UNCHANGED}
                                                          │
                        ┌─────────────────────────────────┼───────────────────────────────┐
                        ▼                                  ▼                                ▼
              re-seed (P2): ADDED,DATA_CHANGED   re-verify (P2): CHECKPOINT_CHANGED   re-run (P3): ADDED,
                                                                                       DATA_CHANGED, EXPECTED_CHANGED
                        └──────────────── UNCHANGED → skip (no seed, no run) ──────────────┘
```

This keeps a doc update cheap: only the changed cases are seeded/run; the analysis run-over-run diff
(P6) then shows whether the *behavior* changed for exactly those cases.

## Principles

- **Deterministic-first, LLM-optional** — every score is arithmetic over records; LLM output is an
  optional cached interpretation, never the source of truth (evalkit + cascade principle).
- **Living gap doc → incremental work** — a doc update produces a `ChangeSet`; only changed cases are
  re-seeded/re-run. Never blindly re-do everything.
- **Gap doc is the source of truth** — seed data, expected outcomes, checkpoints, and coverage all
  derive from one parsed catalog.
- **Verify before you blame the bot** — a failure is only a bot defect once seed checkpoints pass
  (systemCode-match on both sources).
- **Declare once, consume everywhere** — a feed/product/env is a descriptor, not code scattered across
  a runner and every generator.
- **Config & secrets externalized** — no hardcoded paths/IDs/case-lists; no committed tokens.
