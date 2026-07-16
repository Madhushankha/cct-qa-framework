# P1 — catalog: gap-doc parser → normalized use-cases

**The single source of truth loader.** One parser reads any domain's Miro gap-analysis HTML and emits
a normalized model of use-cases: the checkpoint catalog (spine), each case's checkpoint vector, its
bound seed data, and its expected chat. Replaces ~10 copy-pasted HTML-scraper builders.

## Why
The gap doc already encodes *everything* about a test case. Today ~10 near-identical `build_*.py`
files re-scrape it per domain and only extract the seed columns, throwing away the checkpoint vectors
and expected transcripts. See [`../docs/context.md`](../docs/context.md) §2.

## What it parses (identical shape across all domains)

- **Spine** (`<details class="spine">` → `spx` rows) → **`Checkpoint[]`**: ordered catalog of Miro
  steps — `id` (`GLOB-01`, `GenUC-05`, `SoC-02a`), label, `core`/`branch`, assert-count. Plus the
  `uncov` zero-coverage list.
- **Per-case `<section class="card">`** → **`UseCase`**:
  - `id`, `regime` (`data-feat`), `verdict` (`data-out`), `systemCode` (`badge req`), title.
  - **checkpoint vector** — the `stagerow` of `sc-cov ✓ / sc-miss ✕ / sc-na ·` spans projected onto the spine.
  - **customer intent** (opening utterance) + **expected transcript** (bot/user/sysnote bubbles,
    including `TRIP TRACER UI VALIDATIONS` / `CLAIMS DASHBOARD VALIDATION` assertions).
  - **bound data** (datagrid) → **`SeedSpec`**: `PNR, pnrId, passenger, route, flight, delay, ticket,
    amount, currency, flags` + domain extras (NC old→new name; SeatChange reason+seat; BookingChange
    VOL/INVOL+delay+rebooked; Baggage feature→outcome; Non-MVP expected Team).

## Inputs / outputs
- **In:** a gap-doc HTML path + the `Feed` descriptor (from P0).
- **Out:** `Catalog { checkpoints: Checkpoint[], cases: UseCase[] }` — consumed by seed (P2, uses
  `SeedSpec` + checkpoint vector), runner (P3, uses persona intent + expected), evidence/metrics
  (expected outcomes), analysis/coverage (checkpoint coverage).

## Change detection (the gap doc is a living document)

The gap doc gets **added to and updated** over time. When a new version drops, the framework must not
blindly re-seed and re-run everything — it must diff and act only on what changed.

- **Versioned catalog** — each parsed `Catalog` is content-hashed per use-case (a hash over the case's
  `SeedSpec`, checkpoint vector, expected transcript, verdict/systemCode) and stored alongside the run.
- **`diff(old_catalog, new_catalog)` → `ChangeSet`** with per-case status:
  - `ADDED` — new use-case → **seed + run**.
  - `REMOVED` — gone → mark retired (keep history).
  - `DATA_CHANGED` — `SeedSpec` differs (PNR/flight/delay/amount/flags) → **re-seed + re-run**.
  - `CHECKPOINT_CHANGED` — checkpoint vector differs → **re-verify** (and re-run if it affects expected).
  - `EXPECTED_CHANGED` — verdict/systemCode/expected transcript differs → **re-run** (existing seed OK).
  - `UNCHANGED` — content hash identical → **skip** (no re-seed, no re-run).
- The `ChangeSet` is the **work order**: seed (P2) re-seeds only `ADDED`/`DATA_CHANGED`; runner (P3)
  re-runs only cases whose data/expected changed; everything else is left as-is.
- Also detects **spine changes** (a checkpoint added/removed at the domain level) → flags every case
  that references it for re-verification.

This makes updates cheap and safe: drop a new gap-doc version → the framework reports "3 added, 2 data
changed, 1 expected changed, 194 unchanged" and only touches the 6.

## Design notes
- One parser, domain differences handled by small per-feed field maps in the `Feed` descriptor — not
  by copying the parser.
- Parser is **pure** (HTML in → model out), deterministic, unit-testable against fixture docs.
- Content hashing must be **stable** (ignore cosmetic HTML/whitespace; hash the normalized model, not the raw HTML).
- Handles both the gap docs (`*_Miro_Gap_Analysis*.html`) and the "executable" SIT HTMLs (same shape,
  bound to concrete PNRs).

## Harvest from
`cct-qa-1/**/build_*.py` (the scrape boilerplate), the gap docs in `cct-qa-1/doc/source/**`, and the
`_sitintent.py` datagrid format in `CCT_Agent_New 2/`.

## Status
Design. First sub-project to build (with P0).
