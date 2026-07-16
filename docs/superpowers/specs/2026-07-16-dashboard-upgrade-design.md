# Dashboard upgrade (P7.1) — doc links, filters, downloads, index collision fix

**Date:** 2026-07-16
**Status:** Approved design
**Scope:** `ui/` + one-line `quality/` fix + download anchors in `evidence/`/`quality/` renderers.
Separate from the stage-monitors spec; the StageReport "pipeline strip" remains a later increment.

## Problems (found by driving the live dashboard)

1. **`index.html` collision:** both `evidence/build.py` and `quality/build.py` write `index.html`
   into the same run dir — whichever runs last wins. Runs `204833`/`212125` show the quality index
   where the dashboard promises the Expected-vs-Actual run report.
2. **Dead links:** run `184731` has no `index.html`; the dashboard links it anyway → 404.
3. **No direct access to the per-stage docs** (evidence, quality, bot-issues, metrics) from the
   dashboard.
4. **No filtering** by env / product / feed / date.
5. **No download affordance** for sharing reports.

## Design

- **Collision fix:** `quality/build.py` writes `quality-index.html` (never `index.html`).
  `index.html` belongs to the evidence Expected-vs-Actual report alone. Update the one caller
  (`core/cli.py`) only if it references the filename.
- **Per-run doc chips:** each dashboard row links: Report (`index.html`) · Quality
  (`quality-index.html`) · Bot issues (`bot-issues.html`) · Metrics (`report.html`). A chip
  renders only if the file exists in the run dir; missing = greyed, unlinked.
- **Filters:** rows carry `data-env / data-product / data-feed / data-date`; a vanilla-JS filter
  bar offers dropdowns for env / product / feed (populated from values present) + from/to date.
  Pure client-side (works from `file://`). Stat tiles (runs / cases / PASS / rate) recompute from
  visible rows.
- **Download:** report pages are already self-contained (inlined CSS, no external assets), so
  downloads are `<a download>` anchors — one per chip on the dashboard, one on each per-case
  evidence/quality page.

## Testing (offline)

- quality build writes `quality-index.html`, never `index.html`.
- Chips present only when files exist; missing files → greyed, unlinked.
- Filter bar markup + per-row data attributes present; stat-tile recompute logic asserted.
- Download anchors present on dashboard chips and per-case pages.
