# Glossary

**product** — a chatbot deployment / brand (e.g. `brove`, `alpha`). One of the three run axes.

**env** — an environment: `crt`, `int`, `bat`. Carries endpoint, OTP strategy, AWS profile/account,
and seed targets. In the old code this was baked into imports; here it's a descriptor/parameter.

**feed** — a business domain: `fd` (flight disruption), `soc` (standards of care), `nc` (name
correction), `anc` (ancillary seat/bag refund), `baggage`, `seatchange`, `bookingchange`, `nonmvp`.

**scenario id** — `product.env.feed.case` — the structured key used for all rollups (borrowed from
cct-cascade). Enables free grouping by any axis.

**gap doc / Miro gap-analysis** — the per-domain HTML that is the source of truth: use-cases +
checkpoints + expected chat + bound data.

**spine** — the ordered **checkpoint catalog** for a domain (the Miro flow steps), parsed from the
gap doc's `<details class="spine">`.

**checkpoint** — one Miro flow step (e.g. `GLOB-01`, `GenUC-05` auth, `SoC-02a` 72h). A step is
`core` or `branch`.

**checkpoint vector / stagerow** — per-use-case projection of the spine: which checkpoints are
`✓ asserted` / `✕ required-but-missing` / `· not-applicable`. The verification target.

**use-case** — one test case from a gap-doc card: id, regime, verdict, systemCode, checkpoint vector,
customer intent, expected transcript, and bound seed data.

**SeedSpec** — the per-case data to seed: PNR, pnrId, passenger, route, flight, delay, ticket, amount,
currency, flags (+ domain extras).

**systemCode** — the requirement/eligibility code, e.g. `FD-APPR-EL-400`, `SoC-APPR-NE-01`. Format
`<FEED>-<REGIME>-<CLASS>-<n>`. Verification is **systemCode-match** (so NOT_ELIGIBLE / NO_DETERMINATION
/ PENDING are validated, not just eligible).

**regime** — the ruleset: `APPR` (Canada), `EU` (EU261), `ASL` (Israel). Derived from the systemCode.

**verdict / decision class** — the expected outcome: `ELIGIBLE`, `NOT_ELIGIBLE`, `NO_DETERMINATION`,
`PENDING` (and feed-specific ones).

**two-source model** — a case is seeded when BOTH land: (1) booking in trip-tracer **Aurora** via
**Kafka** cascade; (2) DDS verdict in **S3 + `execution_traces` pin**. `dds_pnr_output` is a **decoy**.

**eds contact / OTP gate** — the `eds_pnr_output` contact email/phone the bot sends the OTP to. The
**only** runtime input the user supplies (`{email, phone}`); everything else derives from the gap doc.

**checkpoint auditor** — per-feed verifier (`fd_checkpoints.py`, …) whose checks are the use-case's
checkpoint vector; prints `PASS ✅` per checkpoint.

**Result** — the ONE canonical output schema per case (`{case, session, run_meta, verdict, widgets,
transcript}`), env-agnostic and versioned. Contract between runner and everything downstream.

**metrics.json** — evalkit's deterministic, schema-versioned metrics document. The integration seam
analysis + UI read.

**grade** — cascade-style verdict beyond PASS/FAIL: `Strong/Weak/Invalid PASS`, `Valid FAIL`,
`Harness FAIL`, `Environment TIMEOUT/ERROR`. Separates product vs harness vs env vs weak-evidence.

**finding** — a machine-coded issue `{level, code, message, severity}` (e.g.
`PASS_WITHOUT_DOWNSTREAM_EVIDENCE`) counted at aggregate level to reveal systemic problems.

**run-over-run diff** — newly-failing / newly-passing / still-failing between two runs, keyed by
scenario id. The thing cct-cascade lacks and this framework adds.

**determination gap** — the recurring CRT finding: the bot authenticates but escalates to manual
without rendering the eligibility decision, even though DDS has a valid determination on file. The
class of defect the seed-verify + evidence pipeline is designed to prove and ticket.
