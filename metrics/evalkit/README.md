# evalkit — consistent agentic-QA evaluation reports

Turns raw QA-agent output folders (agent-alpha, agent-bravo, or any future
agent) into **one standard report per run set**, with identical sections,
metrics, and ordering every time.

```bash
python3 -m evalkit.run_eval agent-alpha agent-bravo --out-dir reports
# -> reports/agent-alpha/report.html + metrics.json
#    reports/agent-bravo/report.html + metrics.json
#    reports/comparison.html
```

## Why it's built this way

The two agents' own artifacts disagree in shape and, worse, in judgment:

- **Free-text check names** — 91 distinct LLM-generated names for ~10 real
  assertions ("Eligibility Status" vs "Eligibility determination" vs
  "System code FD-EU-NE-06"). Reports built on raw names change shape every run.
- **Inconsistent LLM judges** — bravo marks identical failure signatures PASS in
  some cases and FAIL in others (16 PASS cases contain failed checks); alpha's
  ESCALATED/NO_DETERMINATION labels drift toward the expected value.
- **Misleading harness errors** — 141 of alpha's 163 "errors" are a cosmetic
  end-of-run probe artifact on otherwise complete conversations.
- **Mislabelled fields** — alpha's `Regime` marks MIXED/DUP itineraries as APPR;
  the scripted systemCode is the reliable source.

So the pipeline is **deterministic-first**: every number in the report is plain
arithmetic over normalized records. Rerunning on the same folder is
byte-identical; rerunning on a new eval set gives the same schema and the same
metric definitions. LLM judgment is *kept* (as "goal success (judged)") but is
always paired with a deterministic re-score and a judge-agreement rate.

## The four measurement layers

1. **Operational** — did the harness even run? Fatal vs cosmetic error buckets,
   duration, turns. (This grades the *test agent*, not the bot.)
2. **Task / goal** — did the bot achieve the scripted goal?
   - *Goal success (judged)*: the agent's own verdict, as recorded.
   - *Goal success (re-scored)*: normalized decision == expected AND quoted
     amount matches (currency-aware, ±2 %, converted dual-currency quotes match
     on either pair, no cross-currency auto-equating).
   - *Judge agreement*: how often the two verdicts coincide.
3. **Decision quality** — the full expected × actual confusion matrix
   (ELIGIBLE / NOT_ELIGIBLE / NO_DETERMINATION / ESCALATED / …), not just
   accuracy: "escalates everything" and "refuses everything" look identical in
   an accuracy number but opposite in the matrix.
4. **Conversation / trajectory** — deterministic regex detectors over the
   transcripts mark canonical business-flow stages (intent recognized → intake →
   identity/OTP → booking → decision → payment → case reference → wrap-up).
   - *Intent recognition rate*: bot routed the opening utterance into the claim flow.
   - *Trajectory match score*: ordered coverage of the stages the scenario was
     supposed to reach.
   - *Anomaly rates*: intent misroutes, resets, forced repeats, OTP trouble,
     booking-lookup loops, escalations, duplicate-claim blocks, carrier
     redirects, output glitches.

## Per-intent slicing

Every metric bundle is reported across five fixed dimensions:

| Slice | Source | Why |
|---|---|---|
| Test family (CORE / ED / PAY) | test-case ID | breadth suite vs intake-edge variants vs payment-leg variants |
| Regime (APPR / EU / ASL / MIXED / DUP) | systemCode segment 2 | which regulation's rules the bot had to apply |
| Expected outcome | scripted status | pays-correctly vs refuses-correctly vs abstains-correctly fail differently |
| Decision class (EL / NE / ND / PE / DB) | systemCode segment 3 | scripted behavioral class |
| Scenario code family (FD-APPR-EL, …) | systemCode prefix | finest designed granularity; localizes failures to a rules branch |

## Layout

| File | Role |
|---|---|
| `adapters.py` | one loader per agent format → normalized records (add new agents here) |
| `taxonomy.py` | canonical check names, flow stages, anomaly + error-bucket regexes |
| `trajectory.py` | stage/anomaly detection over transcripts, trajectory score |
| `metrics.py` | deterministic metric arithmetic → schema-versioned dict |
| `report.py` | fixed HTML template (per-agent report + side-by-side comparison) |
| `run_eval.py` | CLI |
| `gate.py` | CI eval gate: absolute floors + regression-vs-baseline, exit code blocks merge |
| `coverage.py` | evidence-based use-case coverage matrix (CSV + HTML) from metrics.json |

## CI usage

```bash
python3 -m evalkit.run_eval <agent-output-dir> --out-dir reports
python3 -m evalkit.gate reports/<agent>/metrics.json --baseline baselines/<agent>.json
# on merge to main, promote the run:
python3 -m evalkit.gate ... --update-baseline
python3 -m evalkit.coverage reports/<agent>/metrics.json   # coverage.csv/.html
```

## Consistency contract

- `metrics.json` carries `schema_version`; bump it when metric definitions change.
- No timestamps or randomness in outputs — same input, same bytes.
- The report template renders **all** sections regardless of agent, with "—"
  where an agent doesn't capture a signal (e.g. alpha has no turn counts), so
  reports remain visually comparable.
- Environments differ per run set (alpha ran CRT, bravo ran INT); the comparison
  page labels columns with env so differences aren't misread as agent quality.
