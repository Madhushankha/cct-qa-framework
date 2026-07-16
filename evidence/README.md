# P4 — evidence reports (HTML)

**Human-readable proof per run.** From the canonical `Result` set, emit the evidence HTML we produce
today — the per-case chat + verdict, the expected-vs-actual index, and grouped bot-issues — plus the
seed-verification evidence (P2) so a reviewer sees *both* that the data was correct and what the bot did.

## Why (req #3)
We already generate good evidence (index / per-case / bot-issues / JIRA recreate-chats), but from
multiple hardcoded generators with re-declared flow lists. This unifies them over the canonical schema.

## What it emits
- **`<TC>.evidence.html`** — full chat history (OTP masked) + verdict + failed checks + the seed
  checkpoint vector for that case + DDS determination JSON (the proof the data was correct).
- **`<feed>.index.html`** — expected-vs-actual per case, PASS/FAIL, OTP, checkpoint/gap column.
- **`<feed>.bot-issues.html`** — failures grouped into issue cards by bot outcome, with ContactIds.
- **chat-only `<CHAI>.chat.html`** — for pasting into a JIRA comment (the recreate-comment format).

## Inputs / outputs
- **In:** `Result` set for a run (P3) + seed-verification (P2) + expected outcomes (catalog, P1).
- **Out:** self-contained HTML (inlined CSS, light/dark) under the run's output dir.

## Design notes
- Templating is **declarative per feed** (grouping rules on the `Result`), not `if flow in (...)` branches.
- Reuses the same styling as evalkit/analysis so the whole suite reads as one system.
- No hardcoded case-ID or ticket lists — everything comes from the run manifest.

## Harvest from
`cct-qa-1/fd-int-flow/gen_set3_reports.py`, `gen_alldata_summary.py`, `gen_jira_recreate_chats.py`,
`widget_render.py`, and the `data_verification.html` DDS-evidence format.

## Status
Design. Build after P3.
