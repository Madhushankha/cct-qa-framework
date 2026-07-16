# NON-MVP (Intent Routing) Seed Plan

**Date:** 2026-07-17
**Status:** Grounded plan (registry landed; no-seed feed documented)
**Feed registry:** `core/registry/feeds/nonmvp.yaml`
**Gap doc:** `data/gap-docs/nonmvp/Non_MVP_Miro_Gap_Analysis.html`

## What NON-MVP is

Non-MVP tests **pure chat intent-routing**. There is **NO seed at all** — the design doc's per-feed
table lists it as `none | reuses an existing PNR; chat routing only | none`. Nothing is published to
Kafka, no ticket/EMD is issued, and no DDS is pinned. The feed exercises whether the agent, given a
stated intent, **sorts it into the right category and routes to the right destination**:

- **Claims Dashboard** (open/track a claim),
- **Live Agent Handoff** (LAH — transfer to a human),
- **FAQ** (answer first, before opening a case / transferring),
- **Manual Handling**.

Case count (`catalog.parser.load_catalog`): **55 cases**, all `seed_pending`, all titled
(e.g. `TC-NMVP-001` = *Baggage Damage — Post-Travel — Claims Dashboard (BG)*).

## Seed mechanism — none (reuse a pool PNR)

Because the routing decision does not read any per-case seed data, **there is nothing to seed per
case**. The only precondition is that a **valid test PNR exists to identify against**: the routing
flow still runs identification/authentication (`GenUC-01`/`GenUC-05` appear in the spine), so the
conversation needs *a* real booking to attach to — but **the same pool PNR works for every case**.

So the "seed" for Non-MVP is:

1. **Ensure one (or a few) pool PNR(s) exist** in the target env — reuse an FD/SOC-seeded PNR, or a
   long-lived fixture booking. No new publish, no DDS.
2. That's it. Every Non-MVP case injects `{email, phone}` for the pool PNR at runtime and then drives
   the chat with the case's intent text.

There is **no temporal-intent → date mapping** (no flight message), **no CREATE-prelude** (no change
event), **no DDS verdict** to pin.

## What is actually tested

The gap-doc spine is entirely routing logic, confirming intent-sorting is the unit under test:

- `GLOB-20` — intent extraction & sorting,
- `GLOB-20a` — disambiguation + Claims-Dashboard-vs-Live-Agent decision,
- `GLOB-16` — LAH branch (transfer to agent),
- `GLOB-20a · ADD-122` — **FAQ first** (before opening a case / transferring),
- `GLOB-20b` — Aeroplan intent category / does-intent-require-identification branch.

So the `nonmvp.yaml`:

- `verdict_enum` = the **routing destination** the router chose
  (`CLAIMS_DASHBOARD / LIVE_AGENT / FAQ / MANUAL_HANDLING / …`),
- `judge.match_on: [status, system_code]` where `status` = routing verdict and
  `system_code` = the intent category,
- `checkpoints.areas` = `intent_extraction`, `intent_category_match`, `routing_destination`,
  `faq_first`, `live_agent_handoff` — i.e. assertions about the routing decision, not about any
  seeded PNR/DDS state.

## How it uses the engine

It **does not use the seed engine's publish/DDS/checkpoint pipeline.** In the generic engine terms
(design doc §Architecture), Non-MVP is:

- steps 2–8 (template / rekey / mutate / gate / prelude / publish / DDS): **skipped**,
- the only prerequisite is a **pool PNR** in the env (satisfied once, out-of-band),
- step 9 (verify) becomes a **chat-routing auditor** rather than an Aurora/DDS auditor.

## Build steps

- [ ] Document/provision a **pool PNR** per env (reuse an existing FD/SOC fixture booking; no per-case
      seed). Record it as an env fixture, not a per-case seed row.
- [ ] `nonmvp` auditor: assert the router's category + destination match the expected routing verdict
      (LIVE; deterministic transcript checks offline where the expected transcript is embedded).
- [ ] Confirm the runner can drive a Non-MVP case with **no seed step** (skip publish/DDS entirely).

## Grounding notes

- All 55 cases are `seed_pending` and that is **correct** — Non-MVP genuinely needs no per-case seed.
  The registry `columns` (`Intent category`, `Routing verdict`, …) exist only to satisfy the schema.
- `verdict` is empty / `system_code` empty for these cases (doc authored with `data-flow`, not
  `data-out`) — a doc-authoring property, not a parse failure. The routing target lives in the case
  titles (e.g. "… → Claims Dashboard (BG)").
- Because the same pool PNR is reused, Non-MVP is the cheapest feed to stand up once identification
  against a pool booking works.
