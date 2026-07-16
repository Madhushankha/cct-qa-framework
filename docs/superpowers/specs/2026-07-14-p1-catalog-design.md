# P1 — Catalog: gap-doc parser → use-cases + ChangeSet (design)

**Date:** 2026-07-14
**Sub-project:** P1 of CCT-QA-FRAMEWORK
**Status:** design — ready for implementation planning
**Consumes:** P0 (`Feed` descriptor, `SEEDSPEC_REQUIRED`). **Feeds:** P2 (SeedSpec + checkpoint vector), P3 (persona intent + expected), P4/P5/P6 (expected outcomes + coverage).

---

## 1. Purpose & scope

P1 turns a domain's **Miro gap-analysis HTML** into a normalized, in-memory **Catalog** of use-cases,
and diffs two catalog versions into a **ChangeSet** so a doc update only re-seeds/re-runs what changed.
It is the single source-of-truth loader that replaces the ~10 copy-pasted `build_*.py` scrapers.

**In scope:** the `catalog/` package — data model, HTML parser, content-hash + diff, and a
`cctqa catalog <feed> [--diff <old.html>]` CLI. Pure/offline, deterministic, unit-tested against a
small fixture gap doc.

**Out of scope:** seeding (P2), running (P3), any HTML report/metrics/UI. P1 does not touch AWS or the
chatbot. It also does not *resolve* the datagrid into live bookings — only parses the declared data.

## 2. Data model (`catalog/model.py`)

Frozen dataclasses:

- **`Checkpoint`** — one spine step: `id` (e.g. `GLOB-01`, `GenUC-05`), `label`, `kind` (`core`\|`branch`), `assert_count: int`.
- **`SeedSpec`** — the bound data for a case: the `SEEDSPEC_REQUIRED` fields
  (`pnr, pnr_id, passenger, route, ticket, status, system_code, amount, currency, flags`) plus
  `extras: dict` for domain-specific columns (e.g. seat, delay, rebooked). `amount` is `{currency, value} | None`.
- **`CheckpointRef`** — per-case checkpoint state: `id`, `state` (`asserted`\|`missing`\|`na`, from
  `sc-cov`/`sc-miss`/`sc-na`).
- **`UseCase`** — `id`, `regime`, `verdict`, `system_code`, `title`, `third_party: bool`,
  `checkpoint_vector: list[CheckpointRef]`, `customer_intent: str`, `expected_transcript: list[dict]`
  (`{role, text}`), `seed: SeedSpec`, and `content_hash: str` (computed, see §4).
- **`Catalog`** — `feed_id`, `checkpoints: list[Checkpoint]` (the spine), `cases: list[UseCase]`,
  `uncovered: list[str]` (spine ids with zero coverage). Helper `by_id(case_id) -> UseCase | None`.

## 3. Parser (`catalog/parser.py`)

Two real-world facts (verified against `SOC_Miro_Gap_Analysis.html`):
1. The gap doc carries use-cases + checkpoints + expected chat, but the **bound PNR data usually lives
   in a separate dataset HTML** (`SOCUAT81_…SetG_PNRs.html`, `FD_ALL239_CRT_v15.html`). Only some FD
   generators embed a `datagrid` in the card.
2. Real card markup: `<section class="card" id="SOC_UAT-001" data-feat="APPR" data-out="Not Eligible">`
   → `<span class="tcid">`, `<span class="badge req">SoC-APPR-NE-01</span>`, `<span class="outb …">`,
   a `stagerow` of `stage` spans, an `intbub`. Spine: `<div class="spx"><span class="spid">GLOB-01</span>
   <span class="spl">…</span><span class="spm …">core</span><span class="spn">81</span></div>`.

So P1 has **two entry points**, and the `Feed` descriptor gains an optional `dataset` path (P0 change:
add `Feed.dataset: str = ""`):

- **`parse_gap_doc(html_path, feed) -> Catalog`** — pure `HTML → Catalog`. Reads:
  - **Spine** — `<div class="spx">` rows → `Checkpoint[]` (`spid`/`spl`/`spm`/`spn`); the `uncov` block → `uncovered`.
  - **Per-case** `<section class="card">`: `id`, `data-feat` (regime), `data-out` (verdict); `badge req`
    (systemCode); `stagerow` → `checkpoint_vector` (`sc-cov`→asserted / `sc-miss`→missing / `sc-na`→na);
    `intbub` → `customer_intent`; `row bot`/`row user` bubbles → `expected_transcript`. If the card
    embeds a `datagrid`, its `dk`/`dv` pairs → `SeedSpec` (mapped via `feed.columns`); else `SeedSpec`
    is left empty and the case is marked `seed_pending=True`.
- **`join_dataset(catalog, dataset_html, feed) -> Catalog`** — parses the tabular dataset HTML (rows →
  dicts via `feed.columns`, the same tolerant table-scrape) and fills each case's `SeedSpec` by joining
  on **test-case id** (the dataset's `Case`/`Test Case` column ↔ `UseCase.id`), falling back to
  systemCode/requirement. Unknown columns land in `SeedSpec.extras`.
- **`load_catalog(feed) -> Catalog`** — convenience: `parse_gap_doc(feed.gap_doc)` then, if
  `feed.dataset`, `join_dataset(…, feed.dataset)`. Content hashes (§4) are computed after the join so
  they include the seed data.

Parsing is tolerant throughout: missing optional block → empty value, never a crash; the parser is
**feed-agnostic** — domain differences live entirely in `feed.columns` + `feed.dataset`.

## 4. Content hash + diff (`catalog/diff.py`)

- **`content_hash(uc: UseCase) -> str`** — SHA-256 over a **normalized** projection of the case:
  `(seed fields, sorted checkpoint_vector as (id,state), verdict, system_code, normalized
  expected_transcript text)`. Cosmetic HTML/whitespace must not change the hash. Computed at parse
  time and stored on `UseCase.content_hash`.
- **`diff(old: Catalog, new: Catalog) -> ChangeSet`** — per case id, classify:
  - `ADDED` (in new only), `REMOVED` (in old only), `UNCHANGED` (hash equal),
  - else compare sub-hashes to pick the most specific: `DATA_CHANGED` (SeedSpec differs),
    `CHECKPOINT_CHANGED` (checkpoint_vector differs), `EXPECTED_CHANGED` (verdict/system_code/transcript differs).
    If more than one differs, report the highest-impact single label in priority order
    `DATA_CHANGED > EXPECTED_CHANGED > CHECKPOINT_CHANGED` (data change implies re-seed+re-run, the superset).
  - **Spine change**: a checkpoint added/removed at the domain level → every case referencing it is
    additionally flagged `CHECKPOINT_CHANGED`.
- **`ChangeSet`** — `{added, removed, data_changed, checkpoint_changed, expected_changed, unchanged}`
  (lists of case ids) + `summary() -> str` ("3 added, 2 data-changed, 194 unchanged") + helpers
  `to_seed(): list[str]` (added ∪ data_changed) and `to_run(): list[str]` (added ∪ data_changed ∪ expected_changed).

## 5. CLI (extends `core/cli.py` or a `catalog` subcommand)

- `cctqa catalog <feed>` — parse the feed's `gap_doc`, print counts (cases, checkpoints, by-verdict,
  by-regime, third-party, uncovered).
- `cctqa catalog <feed> --diff <old_gap_doc.html>` — parse both, print the `ChangeSet.summary()` and
  the per-bucket case ids.

## 6. Package layout

```
catalog/
├── __init__.py
├── model.py     # Checkpoint, SeedSpec, CheckpointRef, UseCase, Catalog, ChangeSet
├── parser.py    # parse_gap_doc(html_path, feed) -> Catalog
├── diff.py      # content_hash(), diff(old, new) -> ChangeSet
└── cli.py       # catalog subcommands (wired into core/cli.py)
tests/
├── fixtures/
│   ├── gap_min.html         # small synthetic gap doc (spine + ~4 cards) for fast unit tests
│   └── gap_min_v2.html      # same doc with 1 added, 1 data-changed, 1 expected-changed case
├── test_catalog_model.py
├── test_catalog_parser.py
├── test_catalog_diff.py
└── test_catalog_cli.py
```

The fixture `gap_min.html` is a hand-written minimal doc matching the real structure (spine
`<details class="spine">`, cards `<section class="card" id data-feat data-out>`, stagerow, datagrid) —
so tests are fast and don't depend on the 6 MB real docs. A follow-up (P1.1, optional) points the
parser at a real `data/gap-docs/**` doc as a smoke test.

## 7. Design decisions

1. **One parser, feed-agnostic** — all domain differences live in `feed.columns` (P0); no per-domain scraper.
2. **Content hash over the normalized model**, not raw HTML — cosmetic edits don't trigger churn.
3. **Diff priority** `DATA_CHANGED > EXPECTED_CHANGED > CHECKPOINT_CHANGED` so a single label drives
   the correct superset of re-work (`to_seed`/`to_run`).
4. **Pure + deterministic** — `HTML str → Catalog`; same input → identical output (byte-stable hashes).
5. **Tolerant parsing** — unknown columns → `extras`; missing blocks → empty, never crash.

## 8. Testing

- **model**: dataclass construction, `Catalog.by_id`, `ChangeSet.summary/to_seed/to_run`.
- **parser**: parse `gap_min.html` → assert spine count, case count, one case's regime/verdict/
  systemCode/seed fields/checkpoint states/intent/transcript; unknown column → `extras`.
- **diff**: `gap_min.html` vs `gap_min_v2.html` → exact ADDED/DATA_CHANGED/EXPECTED_CHANGED/UNCHANGED
  sets; identical doc → all UNCHANGED (hash stability); a whitespace-only edit → still UNCHANGED.
- **cli**: `cctqa catalog fd` (against fixture via a test hook) prints counts; `--diff` prints summary.
- All offline; no network.

## 9. Deliverables

- `catalog/` package, the two fixtures, tests green, `cctqa catalog`/`--diff` working.
- No change to P0's public API; P1 only *consumes* `Feed`.
