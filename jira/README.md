# P8 — jira (ticket support)

**Close the loop to the tracker.** Generate and (opt-in) file JIRA bug tickets for real bot-side
failures, with chat history + DDS-determination proof attached, safe dedup, and the recreate/re-run
comment workflow.

## Why (req #7)
We already file FD/ANC defects and post recreate comments, but from FD-specific scripts with hardcoded
field IDs and a split-brain between the generator and the creator. This unifies it over the canonical
`Result` + analysis grades.

## What it does
- **Select** bot-side failures only — use P6 grades to exclude Harness/Environment failures and
  Invalid/Weak passes; only `Valid FAIL` (real product defects) become tickets.
- **Generate** a wiki-markup description from the use-case (test intent, expected vs actual, systemCode,
  the DDS determination proof, ContactId) + `fields{}` payload — reviewable HTML before anything is filed.
- **File** (opt-in, dry-run default): `POST /issue` + attach chat history; **resume-safe ledger** +
  live dedupe scan by PNR/scenario so re-runs don't double-file.
- **Recreate-comment** mode: produce chat-only HTML named by ticket (`<CHAI>.chat.html`) + a ready
  comment ("recreated & re-ran, same — still moves to manual review"), like we did for CHAI-259xx.
- **Externalize** JIRA field/component/project IDs to config (per product) — no hardcoded IDs.

## Inputs / outputs
- **In:** `Result` set + P6 grades + evidence (P4) + DDS proof (P2); `JIRA_EMAIL`/`JIRA_API_TOKEN` from env.
- **Out:** `*_jira_bugs.{json,html}` (review), filed tickets + attachments (opt-in), recreate-comment HTMLs.

## Design notes
- **Never files by default** — dry-run + `--create` + `--limit`; the ledger + dedupe are mandatory.
- Root-cause framing comes from P6 findings (e.g. "eligible determination on file in DDS, bot escalated"),
  not hand-written strings.
- Secrets from env/secret store only.

## Harvest from
`cct-qa-1/fd-int-flow/gen_fd_jira_bugs.py`, `gen_flow_jira_bugs.py`, `create_jira_defects.py`
(the actual filer w/ ledger+dedupe), `gen_jira_recreate_chats.py`.

## Status
Design. Build last.
