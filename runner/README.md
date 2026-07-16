# P3 — runner + engine (env as a parameter)

**One runner, one engine, one result schema.** Drives the chatbot for a `product × env × feed` cell:
LLM plays the customer (persona from the catalog use-case), a second LLM judges the transcript, and
every case lands in the **canonical `Result`** (P0) — regardless of env.

## Why (req #2)
Today CRT and INT are *different entrypoints* with *different result schemas*, and concurrency/OTP
knobs are positional argv + monkeypatches. See [`../docs/context.md`](../docs/context.md) §1.

## What it does
- Takes a `RunKey (product, env, feed)` + a case selection; loads the `Feed`/`Product`/`Env`
  descriptors and the parsed `Catalog`.
- For each case: build `(case, persona_prompt, first_name)` from the use-case → drive the Amazon
  Connect websocket via one shared chat client → apply the feed's **judge** → write one `Result`.
- **OTP** comes from the `Env` OTP strategy (real Mailinator broker feed vs fixed `123456`) — not a
  hardcoded import. The OTP-phase concurrency gate is a config value, not a monkeypatch.
- Async orchestration (asyncio + thread pool), staggered starts, shared Bedrock limiter — but the
  concurrency/stagger/OTP-window are **parameters** on the run, not argv positions.
- Consumes P2's go/no-go: only run cases whose seed checkpoints passed (or `--force`).

## Inputs / outputs
- **In:** `RunKey`, case selection, run params (conc, otp-window, timeouts); `{email, phone}` for OTP.
- **Out:** `out/<product>/<env>/<feed>/<date>/<TC>.result.json` (canonical schema) + transcript + a run manifest.

## Design notes
- **One engine** replaces `run_nc_crt` + `run_fd_flow` + the dead runners; env differences live in the
  `Env` descriptor.
- Persona + judge come from the `Feed` descriptor (P0) — adding a feed adds no runner code.
- Third-party / UMNR and other branch personas are driven by use-case flags from the catalog, not
  hardcoded detection.

## Harvest from
`cct-qa-1/fd-int-flow/run_flow_async.py` (orchestration, OTP-phase gate), `run_nc_crt.py` (widget/OTP
loop, `run_flow`), `run_fd_flow.py` (Bedrock plumbing, tool schemas), `otp_broker.py` + `feed_otp.py`.

## Status
Design. Build after P2.
