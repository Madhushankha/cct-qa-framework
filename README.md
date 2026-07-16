# CCT-QA-FRAMEWORK

A clean, maintainable QA framework for Air Canada's **Ask AC** agentic chatbot. It replaces the
ad-hoc scripts in `cct-qa-1/` with one pipeline that is driven by the **Miro gap-analysis docs** and
parameterized by three axes so any product / environment / feed can be run, verified, evidenced,
scored, analyzed, and ticketed the same way.

> **Status:** design / scaffolding. Each folder currently holds a `README.md` describing its purpose,
> inputs/outputs, and what it harvests from the existing code. No implementation yet — see
> [`docs/context.md`](docs/context.md) for the findings behind this design and the build order below.

---

## The pipeline

Everything flows one direction, and every artifact is keyed on **`(product, env, feed, date)`**:

```
 gap-doc ─▶ ① catalog ─▶ ② seed+verify ─▶ ③ run ─▶ ④ evidence ─▶ ⑤ metrics ─▶ ⑥ analysis ─▶ ⑦ ui + ⑧ jira
              parse         inject only         drive       HTML per      evalkit       grades,        browse,
              use-cases     {email,phone},      chatbot,    case +        metrics.json  clustering,    file bugs
              + checkpoints seed both sources,  judge       roll-up                     run-over-run
                            verify checkpoints  transcript                              diff
```

## The three axes (swap freely)

| Axis | Values (examples) | Meaning |
|---|---|---|
| **product** | `brove`, `alpha`, … | which chatbot deployment / brand |
| **env** | `crt`, `int`, `bat` | which environment (endpoint + OTP strategy + seed targets) |
| **feed** | `fd`, `soc`, `nc`, `anc`, `baggage`, `seatchange`, `bookingchange`, `nonmvp` | which business domain |

A run is one cell of `product × env × feed`, stamped with the run **date**. Results are stored and
browsed along all four dimensions.

## Core principle: the gap doc is the source of truth (and it's living)

Each domain's **Miro gap-analysis HTML** is the canonical catalog of use-cases + verification
checkpoints. The framework reads it to obtain **everything** about a test case — PNR, passenger,
flight, delay, ticket, amount, systemCode, flags, expected verdict, and the ordered checkpoint
vector. **The only thing a user supplies at runtime is `{email, phone}`** (a real reachable inbox +
SMS), which is injected as the booking's contact so OTP can be received.

**The gap doc changes over time.** When you add or update it, the catalog **diffs the new version
against the last** and emits a `ChangeSet` — `ADDED / DATA_CHANGED / CHECKPOINT_CHANGED /
EXPECTED_CHANGED / REMOVED / UNCHANGED` per case — which becomes the **work order**: re-seed only
cases whose data changed, re-run only cases whose data/expected changed, skip the rest. Drop a new
version → "3 added, 2 data-changed, 194 unchanged" → the framework only touches the 5. See
[`catalog/README.md`](catalog/README.md) and [`seed/README.md`](seed/README.md).

---

## Sub-projects & build order

Design and build **one at a time**, foundation first. Each gets its own spec → plan → implementation.

| # | Folder | Sub-project | Requirement | Harvest from |
|---|---|---|---|---|
| **P0** | [`core/`](core/README.md) | Product + Env descriptors, ONE result schema, registry | "generic per feed, swap product+env" | replaces the 3-dict / dual-schema mess in `run_flow_async.py` |
| **P1** | [`catalog/`](catalog/README.md) | Gap-doc parser → normalized use-cases (spine + cards + checkpoint vectors + bound data) | "add gap doc, move to framework" | one parser replaces ~10 copy-paste builders |
| **P2** | [`seed/`](seed/README.md) | Seed + verify — inject `{email,phone}`, seed both sources, run checkpoint auditor → `PASS ✅` | req #1 | `CCT_Agent_New` HOWTO + `contrail` |
| **P3** | [`runner/`](runner/README.md) | Unified runner + engine — Env as a parameter, one result schema | req #2 | merge `run_nc_crt` + `run_fd_flow` |
| **P4** | [`evidence/`](evidence/README.md) | Evidence HTML (index / per-case chat+verdict / bot-issues) | req #3 | `gen_set3_reports.py` |
| **P5** | [`metrics/`](metrics/README.md) | evalkit metrics.json per (product, env, run) | req #4 | `reports/cct-qa-ai-evals` |
| **P6** | [`analysis/`](analysis/README.md) | Grades, confidence, findings, clustering, run-over-run diff, date/product/env rollups | req #5 | `cct-cascade` (CONTRAIL) |
| **P7** | [`ui/`](ui/README.md) | Dashboard — browse by date/product/env, drill to evidence, trends | req #6 | `cct-cascade` reactor dashboard |
| **P8** | [`jira/`](jira/README.md) | Generate + file bug tickets w/ chat + DDS proof, dedup, recreate-comments | req #7 | existing JIRA tools |

**Recommended order:** `P0 + P1` (foundation) → `P2` → `P3` → `P4` → `P5` → `P6` → `P7` → `P8`.

## Repo layout

```
cct-qa-framework/
├── README.md            ← this file
├── docs/
│   ├── context.md       ← findings from the exploration (why this design)
│   ├── architecture.md  ← the whole-framework architecture & data flow
│   └── glossary.md      ← product/env/feed/spine/checkpoint/systemCode/…
├── core/       (P0)   descriptors + result schema + registry
├── catalog/    (P1)   gap-doc parser → use-cases
├── seed/       (P2)   seed + verify (only email+phone)
├── runner/     (P3)   unified runner + engine
├── evidence/   (P4)   evidence HTML reports
├── metrics/    (P5)   evalkit integration
├── analysis/   (P6)   cascade-style analysis
├── ui/         (P7)   dashboard
├── jira/       (P8)   jira ticket support
└── data/              gap docs + datasets (inputs; referenced from cct-qa-1)
```

## Reference material (inputs, not part of this repo)

- **`../cct-qa-1/`** — the current working project being replaced; source of gap docs (`doc/source/`),
  datasets (`doc/source/All_Data/`), and the evalkit (`reports/cct-qa-ai-evals/`).
- **`../cct-qa-1/CCT_Agent_New 2/`** — reference implementation: `HOWTO_CREATE_PNR_DATA.md` (the
  definitive seed+verify recipe) and `cct-cascade/contrail` (the seeding engine).
- **`../cct-cascade/`** — reference for analysis + dashboard (CONTRAIL grading, reactor React UI).
