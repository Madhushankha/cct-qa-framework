# P0 — Core: descriptors, canonical Result schema, registry (design)

**Date:** 2026-07-14
**Sub-project:** P0 (foundation) of CCT-QA-FRAMEWORK
**Status:** design — ready for implementation planning

---

## 1. Purpose & scope

P0 is the foundation every other module consumes. It defines **what a feed / product / environment
is** (declarative descriptors + a loader) and **what a test result is** (one canonical, versioned
schema), plus the **registry** that resolves a run and validates everything.

It exists to kill the two structural problems in the current `cct-qa-1` code:
- "product = a string key indexing three hand-synced dicts, re-declared in every generator"
- "env = whichever engine module you import, producing two incompatible result schemas"

**In scope (P0):** descriptor model (Feed/Product/Env) + YAML loader; `RunContext` resolution; the
canonical `Result` JSON schema + validator; the registry; a thin `list`/`validate` CLI.

**Out of scope (later sub-projects):** parsing gap docs (P1), seeding/verifying (P2), driving the bot
or judging (P3), any HTML/metrics/analysis/UI/JIRA (P4–P8). P0 ships **no runtime that talks to AWS or
the chatbot** — only descriptors, schema, and validation.

## 2. Goals / non-goals

**Goals**
- A feed/product/env is **one declarative file**; adding one adds **zero engine code**.
- **One** result schema, env-agnostic and versioned, that P4–P8 all read.
- Fail-fast validation with clear messages (descriptors at load, results at write).
- No secrets in files; secrets referenced by name and resolved at runtime.
- Pure/deterministic and unit-testable with no network.

**Non-goals**
- No scoring/grading logic in P0 (that's P5/P6; the Result stays raw observations).
- No dynamic behavior beyond an optional per-feed Python hook for persona/branch selection.
- Not a general config system — only these three descriptor types.

## 3. Descriptor model

Python package + **YAML** descriptor files under `core/registry/`. Loaded into frozen dataclasses.
One dependency (PyYAML); otherwise stdlib.

### 3.1 Feed — `registry/feeds/<id>.yaml`
Everything specific to a business domain.

| Field | Type | Meaning |
|---|---|---|
| `id`, `label` | str | e.g. `fd`, "Flight Disruption" |
| `gap_doc` | path | source-of-truth HTML (parsed by P1) |
| `columns` | map | datagrid column → `SeedSpec` field; a value may be a list of accepted column names (e.g. third-party columns) |
| `persona.default` | str (template) | customer prompt; `{slots}` filled from the use-case |
| `persona.branches` | map[str→template] | e.g. `third_party` |
| `persona.hook` | dotted path (optional) | optional Python callable for branch selection / dynamic prompt |
| `judge.verdict_enum` | list[str] | this feed's outcome vocabulary |
| `judge.match_on` | list | which fields define "matches expected" (e.g. `[status, system_code, amount]`) |
| `judge.hook` | dotted path (optional) | optional custom judge |
| `checkpoints.auditor` | str | which auditor (P2) |
| `checkpoints.areas` | list[str] | ordered checkpoint areas (from the gap-doc spine) |

### 3.2 Product — `registry/products/<id>.yaml`
A chatbot deployment/brand.

| Field | Type | Meaning |
|---|---|---|
| `id`, `label` | str | e.g. `brove` |
| `transcript_dialect` | str | selects evalkit taxonomy regex block (P5) |
| `overrides.persona` | map (optional) | per-feed persona overrides |
| `overrides.judge` | map (optional) | per-feed judge overrides |
| `defaults.envs`, `defaults.feeds` | list | which cells this product is allowed to run |

### 3.3 Env — `registry/envs/<id>.yaml`
An environment. **Secrets by name only.**

| Field | Type | Meaning |
|---|---|---|
| `id`, `label` | str | e.g. `crt` |
| `chatbot.base_url`, `.endpoint_path`, `.region` | str | API Gateway endpoint |
| `aws.profile`, `.account` | str | AWS SSO profile + account id |
| `otp.strategy` | enum `mailinator`\|`fixed` | how OTP is obtained |
| `otp.*` | — | mailinator: `domain/inbox/token_secret`; fixed: `code` |
| `seed_targets.kafka_topic` | str | PNR publish topic (P2) |
| `seed_targets.aurora_secret`, `.aurora_host` | str | trip-tracer DB |
| `seed_targets.dds_s3_bucket`, `.dds_endpoint` | str | DDS verdict source |

### 3.4 Loader & `RunContext`
- `load_feed(id)`, `load_product(id)`, `load_env(id)` → validated dataclasses (cached).
- **`resolve(product, env, feed) → RunContext`**: validates the cell is allowed by
  `product.defaults`, layers product overrides onto the feed persona/judge, attaches the env +
  resolved secrets accessor, and builds the `scenario_id` prefix `product.env.feed`. `RunContext` is
  the single immutable object passed through the whole pipeline.

## 4. Canonical `Result` schema (v1.0)

One JSON document per case. Env is a field, not a schema variant. Raw observations only — scores are
computed downstream.

```jsonc
{
  "schema_version": "1.0",
  "scenario_id": "brove.crt.fd.FD_TC_089",       // product.env.feed.case
  "run":   { "product","env","feed","date","run_id","started","duration_s" },
  "case":  {                                      // EXPECTED, from the catalog use-case (P1)
    "test_case","pnr","pnr_id","passenger","regime",
    "expected_status","expected_system_code",
    "expected_amount": { "currency","value" } | null,
    "flags": [ ... ], "third_party": bool
  },
  "seed":  {                                      // from P2 — data proven before running
    "verified": bool,
    "checkpoints": [ { "area","pass" } ],
    "dds": { "status","system_code","amount":{ "currency","value" },"trace_s3" } | null
  },
  "auth":  { "otp_fetched": bool, "contact_id": str|null },
  "verdict": {                                    // ONE shape
    "decision": str,                              // feed verdict_enum value
    "amount": { "currency","value" } | null,
    "reached_determination": bool,
    "matches_expected": bool,                     // judge's own opinion (kept, not trusted alone)
    "checks": [ { "name","expected","actual","pass" } ],
    "reasoning": str
  },
  "harness": { "error": str|null, "error_bucket": str|null },  // fatal vs cosmetic
  "transcript": [ { "role","text","ts","note" } ],
  "evidence": { "chat_html": path|null, "evidence_html": path|null }
}
```

**Design decisions**
1. **Env-agnostic**: one shape for crt/int/bat.
2. **`seed` embedded**: every result carries proof the data was verified (checkpoints + DDS
   determination) → *verify-before-blame*; a failure with `seed.verified=true` is provably the bot.
3. **Raw only**: no grades/pass-rate/rescored in the Result — computed in P5/P6.
4. **`decision`** is the feed's own enum; P5's adapter normalizes to a cross-feed `decision_class`.
5. **`harness.error_bucket`** separates product failures from harness/env noise (feeds cascade grades).

A JSON Schema for this document lives at `core/schema/result.schema.json`; `schema_version` gates
compatibility.

## 5. Registry & validation

**Registry** discovers descriptors by scanning `registry/{feeds,products,envs}/*.yaml`; exposes the
loaders + `resolve()`.

**Validation — two layers, fail fast:**
1. **Descriptor (load time):** required fields present; enums valid (`otp.strategy`); referential
   integrity — `feed.gap_doc` file exists, every named secret is resolvable, `feed.columns` cover the
   required `SeedSpec` fields, a product's `defaults` reference real feeds/envs. Clear, located errors.
2. **Result (write time):** validate each result against `result.schema.json` before write.

**CLI (thin, grows per module):**
- `cctqa list` — registered feeds/products/envs + the valid `product×env×feed` cells.
- `cctqa validate` — validate all descriptors + referential integrity (exit 1 on failure; CI-friendly).

## 6. Package layout (P0)

```
core/
├── __init__.py
├── descriptors.py     # Feed/Product/Env/RunContext dataclasses
├── registry.py        # discovery, load_*(), resolve()
├── validate.py        # descriptor + result validation
├── result.py          # Result dataclass + helpers (build/validate/write)
├── secrets.py         # name → value resolution (env / AWS secretsmanager) — interface + local impl
├── schema/
│   └── result.schema.json
├── cli.py             # `cctqa list|validate`
└── registry/          # the descriptor DATA (feeds/, products/, envs/)
```

## 7. Testing

- **Descriptor round-trip**: load each stub → dataclass; assert fields.
- **Validation**: golden bad descriptors (missing field, bad enum, dangling secret, missing gap_doc)
  → precise error; `cctqa validate` exit codes.
- **resolve()**: product overrides layer correctly; disallowed cell rejected; `scenario_id` correct.
- **Result schema**: valid sample passes; each malformation fails with the offending path.
- All tests **offline** (no AWS/network); secrets resolver stubbed.

## 8. Deliverables

- `core/` package as above, with the four stub descriptors filled to real (fd/crt/int/brove) + one
  more feed stub to prove "add a file, no code".
- `result.schema.json` v1.0 + validator.
- `cctqa list` / `cctqa validate` working against the checked-in registry.
- Unit tests green, offline.

## 9. Deferred / consumed-by

- **P1 (catalog)** consumes `Feed.columns`, `gap_doc`, and produces the use-cases that fill
  `Result.case`. The `SeedSpec` field set is finalized with P1 (P0 defines the map, P1 defines the target).
- **P2** fills `Result.seed`; **P3** fills `run/auth/verdict/transcript`; **P4–P8** read the Result.
- Optional persona/judge **hooks** are defined here but exercised in P3.
