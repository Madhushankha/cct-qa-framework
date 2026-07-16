# P0 — core: descriptors, result schema, registry

**The foundation. Everything else consumes this.** Defines *what a product/env/feed is* and *what a
result looks like*, so a test target is declared **once** and the runner, seeder, reporter, and
analyzer all read the same source of truth.

## Why
Today a "product" is a string key indexing three hand-synced dicts (`CFG`/`BUILD`/`JUDGE`) in a
516-line file, re-declared in every generator; and "env" isn't a parameter at all — it's baked into
which engine you import, producing two incompatible result schemas. See
[`../docs/context.md`](../docs/context.md) §1.

## What it provides

- **`Feed` descriptor** — one per business domain (`fd`, `soc`, …): the customer persona template,
  the judge + verdict tool schema, the expected-outcome shape, and a reference to its gap doc + checkpoints.
- **`Product` descriptor** — a chatbot deployment (`brove`, `alpha`): display name, defaults, any
  product-specific persona/judge overrides, transcript dialect id (for evalkit taxonomy).
- **`Env` descriptor** — an environment (`crt`, `int`, `bat`): API-Gateway endpoint, **OTP strategy**
  (real Mailinator vs fixed `123456`), config, AWS profile/account, and **seed targets** (Kafka topics,
  Aurora host, S3 bucket, DDS api). No secrets in code.
- **`RunKey`** — the `(product, env, feed, date)` tuple + a structured **scenario id**
  `product.env.feed.case` used everywhere for rollups (cascade pattern).
- **ONE canonical `Result` schema** — replaces the `bot_result`-vs-`bot_said_eligible` split. Superset
  of today's `{case, session, run_meta, verdict, widgets, transcript}`, env-agnostic, versioned.
- **Registry** — `get_feed(id)`, `get_product(id)`, `get_env(id)`; validates that a requested
  `product × env × feed` cell is defined and consistent.

## Inputs / outputs
- **In:** descriptor definitions (declarative, one file per feed/product/env under `core/registry/`).
- **Out:** typed objects + the `Result` schema (+ a JSON Schema for validation) that every other module imports.

## Design notes
- Descriptors are **data, not code paths** — no more `_v7`/`_set8` file-copies; version/set is a field.
- The `Result` schema is the stable contract; changing it is a versioned event (like evalkit's `SCHEMA_VERSION`).
- Keep secrets (Mailinator token, JIRA token) out — read from env/secret store via the `Env` descriptor.

## Harvest from
`cct-qa-1/fd-int-flow/run_flow_async.py` (CFG/BUILD/JUDGE → descriptors), `save_result()` (→ Result schema),
`config_crt.json` / `config.json` (→ Env descriptors).

## Status
Design. First sub-project to build (with P1).
