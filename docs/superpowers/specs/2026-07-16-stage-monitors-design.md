# Stage monitors — seed gate + ledger + corpus audit + chat quality gate

**Date:** 2026-07-16
**Status:** Approved design (this doc), pending implementation plan
**Scope:** P2 (seed) + P3 (runner) + one new `core/` module. Future stage monitors (evidence,
metrics, analysis, jira) are out of scope — this spec defines the interface they will implement.

## Problem

1. **Seeding is unverifiable as a corpus.** The FD gap doc defines 239 cases (39 `seed_pending`);
   the INT preseed corpus holds 48 usable fixtures. There is no link between gap-doc case ids
   (`FD_TC_###`) and seeded PNRs (`FDAP36`, `ZZFDBA`, …), so nobody can answer "which cases are
   seeded, which are missing, which are broken?" 34 of 48 fixtures parse to verdict `UNKNOWN`.
2. **Seeding failures surface late.** The seed pipeline (`index → clone → publish → checkcascade →
   finalize → verify`) only proves correctness at the final `verify` step, per invocation. A phase
   that half-landed (publish acked but cascade never arrived, DDS pin missing) is discovered at the
   end, or worse at bot-run time.
3. **Chat quality is passive.** P9 computes deterministic findings + a score per transcript, but
   nothing acts on it — a case with a wrong verdict in the chat still counts as a normal run.
4. Generalizing: **every pipeline stage should have a monitor** — deterministic checks with a
   machine-readable verdict, optional LLM triage of failures — in one uniform shape.

## Decisions (made during brainstorming)

- **Watch mode:** both a live phase gate during seeding and an on-demand corpus audit.
- **Case mapping:** framework-owned ledger, written on successful seed, back-filled once for the
  existing fixtures.
- **Watcher type:** deterministic checks decide PASS/FAIL; an LLM (Bedrock, P9 plumbing) only
  triages failures into human diagnoses. Triage never affects verdicts.
- **Remediation:** report only. Seeding missing cases stays a human-initiated `cctqa seed` run.
- **Scope:** seed + chat gates now; generic `StageReport` interface documented for later monitors.

## Architecture

```
gap doc ──▶ catalog (P1) ──┐
                           ├──▶ cctqa audit <product> <env> fd ──▶ audit-report.{json,html} + triage
data/seed-ledger/fd.yaml ──┤          │
        ▲                  │          └── live checks: seed/verify.py against Aurora + DDS
        │                  │
cctqa seed (existing) ─────┘
   └─ seed/gate.py: phase gates inside the existing pipeline, writes ledger on success

runner (P3) ── per-case transcript ──▶ quality gate (P9 checks → StageReport, threshold from
                                        registry) ──▶ Result.harness.error_bucket="quality_gate"
```

New pieces: `core/monitor.py`, `seed/gate.py`, `seed/ledger.py`, `seed/audit.py`,
`data/seed-ledger/fd.yaml`, a thin runner hook, one registry key, CLI subcommands
(`cctqa audit`, `cctqa ledger backfill`).

## Component 1 — `core/monitor.py`: the generic stage-monitor pattern

Cross-stage, so it lives in `core/`, not `seed/`.

- **`StageReport`** dataclass:
  `{stage, subject_id, checks: [{area, pass, severity, evidence}], verdict: PASS|FAIL|WARN,
  triage: str|null, schema_version}`. The seed gate log and the chat quality verdict are both
  instances of this one shape.
- **Gate contract:** a monitor runs deterministic checks, writes its `StageReport` next to the
  stage's artifact, and raises **`GateFailure(stage, reason, report_path)`** when a blocking check
  fails. Blocking vs warning is per-check configuration, not code.
- **Triage hook:** one shared function wrapping the P9 Bedrock plumbing — takes failed checks +
  evidence, returns a one-paragraph diagnosis and suggested next action. Used by seed audit and
  chat gate; degrades to `triage: null` on any Bedrock error; skipped entirely by `--no-triage`
  or absent AWS credentials.

## Component 2 — `seed/gate.py`: the live seed gate

The existing `run_seed()` phase order gains a named, deterministic `PhaseCheck` at each boundary:

| Phase check | Asserts |
|---|---|
| `clone_valid` | fixture files present, JSON parses, contact `{email, phone}` injected |
| `publish_acked` | Kafka produce confirmed |
| `cascade_landed` | trip rows present in Aurora (promotes existing `_trip_landed`) |
| `dds_pinned` | by-pnr endpoint returns the pinned verdict |
| `checkpoints_pass` | existing `verify_case` full checkpoint vector (unchanged) |

- On failure: raise `GateFailure(phase, reason, evidence)`; pipeline stops; CLI exits non-zero and
  prints phase, reason, evidence path.
- `gate-log.json` (a `StageReport`: per-phase timings + check results) is written to the clone dir
  on success **and** failure — triage always has something to read.
- `--no-verify` keeps its meaning: skips only the final `checkpoints_pass` gate, never the
  structural checks.
- The ledger entry is written **only after all gates pass** — a failed seed is invisible to
  coverage, which is correct: it is not seeded.

## Component 3 — `seed/ledger.py` + `data/seed-ledger/fd.yaml`

- Append-on-success entry: `{case_id, pnr, pnr_id, env, seeded_at, gate: all-pass}`.
- One entry per `(case_id, env)`; re-seeding updates the entry, previous value pushed onto a
  `history` list (last write wins).
- Committed to git — the durable answer to "what covers what."
- **Backfill:** `cctqa ledger backfill fd` maps the existing 48 fixtures to `FD_TC_###` ids
  best-effort (matching regime / verdict / amount / scenario text). Unmatched or ambiguous entries
  are written with `case_id: null, needs_review: true` for a human to finish directly in the YAML.
- Ledger load validates shape: duplicate `(case_id, env)` pairs and case ids unknown to the
  catalog are reported as warnings/`ORPHAN` — never a crash (humans edit this file).

## Component 4 — `seed/audit.py` + `cctqa audit`: the corpus audit

`cctqa audit <product> <env> fd [--offline] [--no-triage] [--include chat]`

Joins three sources — gap-doc catalog (expected), ledger (claimed), live re-verification
(`verify_case` per ledger PNR, concurrency-limited, reusing P2 source connections) — and places
**every** catalog case in exactly one bucket:

| Bucket | Meaning |
|---|---|
| `HEALTHY` | ledgered + all checkpoints pass now |
| `BROKEN` | ledgered but at least one checkpoint fails now |
| `MISSING` | in gap doc, no ledger entry |
| `SEED_PENDING` | gap doc marks data not yet defined (39 today) |
| `ORPHAN` | ledgered but no longer in the gap doc (or unknown case id) |
| `UNCHECKED` | ledgered but the live check could not run (source unreachable) |

- `UNCHECKED` ≠ `BROKEN`: an unreachable source records the connection error; a **fully**
  unreachable env fails the audit loudly rather than reporting 0% healthy.
- Output: `results/<date>/audit_<env>_<feed>/audit-report.json` (with `schema_version`) +
  `audit-report.html` (evidence-renderer style, coverage counts up top). Keyed
  `(product, env, feed, date)` like every other artifact so the dashboard can consume it later.
- `--offline`: catalog × ledger only, no live calls, no AWS — usable in CI.
- LLM triage runs per `BROKEN` case after buckets are final (failed checkpoint areas + gate log +
  raw source rows → diagnosis paragraph embedded in the report).
- Gap-doc drift is reflected, not diagnosed: dropped cases show as `ORPHAN`, new ones as
  `MISSING`; the P1 ChangeSet diff remains the tool for *why*.
- **Report only:** the audit never seeds, republishes, or repairs anything.

## Component 5 — the chat quality gate (runner wiring, thin)

- After each case's transcript is scored by P9 `quality_report()`, the findings are mapped into a
  `StageReport`.
- A blocking threshold comes from the feed registry YAML:
  `quality_gate: {min_score: 70, block_on: [wrong_verdict, wrong_amount]}` (per-feed, optional —
  absent key means the gate is report-only for that feed).
- A FAIL does **not** abort the run: the case's Result is marked
  `harness.error_bucket: "quality_gate"` so it is counted, visible in evidence/metrics, and
  triaged; other cases continue.
- `cctqa audit --include chat` folds the latest run's chat StageReports into the audit report, so
  one page answers "is the data healthy?" and "is the bot conversation quality healthy?"

## Component 6 — `seed/campaign.py` + `cctqa seed-campaign`: seed the full corpus

**Goal:** seed every seedable gap-doc case (239 for FD today) onto a target env, each provably
mapped to its `FD_TC_###` id, gate-verified, and ledgered. User-initiated (`cctqa seed-campaign
<product> <env> fd`), staged (pilot batch first), resumable (skip cases already `HEALTHY` in the
ledger).

Prerequisite gaps this component closes:

1. **Dataset join for all cases.** `catalog.parser.join_dataset` currently binds dataset rows only
   to `seed_pending` cases; extend it to bind every case whose id matches a dataset row (the
   `FD_ALL239_CRT_v15` dataset carries locator/passenger/route/ticket/status/systemCode/amount for
   all 239). Cases keep `seed_pending` semantics only when no dataset row matches.
2. **Cloner rewrites for passenger.** `seed.clone.clone_fixture` gains passenger-name rewrite
   (surname + given name across 01_pnr / 02_ticket / FDM XML / meta) so each seeded PNR carries the
   dataset's passenger, keeping the `passenger` and `name_uniqueness` checkpoints meaningful.
   Route rewrite is NOT attempted (airport codes are entangled with FDM legs/timings); instead the
   matcher (below) selects a source fixture and the case's *bound* route is updated in the ledger
   entry to the fixture's actual route.
3. **Source-fixture matcher.** For each case, pick the clone source by (regime, verdict/systemCode
   family, structural flags: pax count / group / infant / multi-segment); prefer exact systemCode
   family match, then same regime+verdict, else report the case as `UNSEEDABLE(no_source)` — never
   silently seed a structurally wrong fixture.
4. **DDS template families.** Harvest real determination JSONs from the env's by-pnr endpoint for
   existing NE / ND / PENDING / EU / ASL / UK / MIXED fixtures, store them under
   `data/dds-templates/<family>.json`, and register them in the env descriptor. A family with no
   harvestable sample is reported `UNSEEDABLE(no_template)`.
5. **Batching + ledger.** Seed in batches (default 25): clone all → one Kafka publish per batch →
   settle → pin DDS → gate-verify each case → ledger entry with `case_id` = the gap-doc id.
   Re-running the campaign skips ledgered `HEALTHY` cases, so it converges over multiple sessions.
   Every batch ends by printing the running coverage tally (`HEALTHY x/239`).

The campaign never invents data: anything it cannot seed faithfully lands in the final report as
`UNSEEDABLE` with a machine-readable reason, feeding the audit's `MISSING` bucket honestly.

## Testing (all offline, repo convention — no AWS in CI)

- **Gate:** each `PhaseCheck` with faked sources — ≥1 pass and ≥1 fail case each; `GateFailure`
  stops at the right phase and still writes `gate-log.json`; `--no-verify` skips only
  `checkpoints_pass`.
- **Ledger:** round-trip write/read; update-with-history on re-seed; backfill against a fixture
  dir with one clear match, one ambiguous (→ `needs_review`), one unmatchable; validation of
  duplicate/unknown entries.
- **Audit:** bucket-assignment matrix over a synthetic catalog + ledger + stubbed verifier
  covering all six buckets; `--offline` makes no live calls; report JSON validates against its
  schema; HTML renders non-empty.
- **Chat gate:** threshold from registry respected; absent key → report-only; FAIL marks
  `error_bucket` without aborting the run.
- **Triage:** stubbed Bedrock client — diagnosis embedded on success, `triage: null` on error,
  `--no-triage` never constructs the client.
- **Live smoke (manual, not CI):** seed one PNR on INT end-to-end, run `cctqa audit`, confirm it
  lands `HEALTHY` — same pattern as P2's live validation.

## Out of scope

- Monitors for evidence, metrics, analysis, jira stages (they implement `StageReport` later).
- Auto-healing / auto-reseeding of `MISSING`/`BROKEN` cases.
- Scheduled/continuous auditing (the audit is on-demand; scheduling can wrap the CLI later).
- **Feeds other than FD.** This phase targets FD end-to-end (ledger, backfill, audit, chat gate
  thresholds). The code stays feed-parameterized throughout, so extending to the other feeds
  (`soc`, `nc`, `anc`, `baggage`, `seatchange`, `bookingchange`, `nonmvp`) is a follow-up phase:
  register the feed (registry YAML), validate the parser against its gap doc, add its checkpoint
  auditor, and start its ledger. No redesign expected.
- **Dashboard "pipeline strip" (P7 follow-up).** Once StageReports exist on disk, the dashboard
  gains a per-cell pipeline strip — `Seed ✅ 48/239 · Run ✅ 3P/0F · Quality ⚠ 1 gated ·
  Metrics ✅` — one chip per stage, each linking to that stage's existing HTML artifact
  (`audit-report.html`, run `index.html`, `*.quality.html`, `report.html`). Because `StageReport`
  is one uniform schema, the dashboard renders chips without stage-specific knowledge, and future
  monitors light up automatically. The UI stays strictly read-only: ordering/orchestration remain
  in the CLI and seed gate, never in the dashboard.
