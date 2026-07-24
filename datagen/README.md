# datagen — the reference data-creation pipeline (vendored)

The proven PNR data-creation toolchain from `CCT_Agent/cct-crt-kb`, vendored here so the framework
creates test data the same way it is created today, instead of a parallel re-implementation.

**This is the tool of record for creating PNR data.** `seed/` remains for the framework-native
path (registry-driven seeding, the checkpoint model the runner and reports consume), but when the
question is "how do I create a correct set of PNRs", the answer is here. See
[HOWTO_CREATE_PNR_DATA.md](HOWTO_CREATE_PNR_DATA.md) — the definitive recipe — and
[LEARNINGS.md](LEARNINGS.md).

## Why vendored rather than referenced

The scripts are inseparable from their data: 13,211 scenario JSONs and 6,339 DDS determination
templates under `scenarios/`. A case is built by **donor cloning** — binding it to a real scenario +
determination carrying the exact systemCode it expects, then cloning that donor under a fresh
identity. Without the corpus the scripts cannot resolve a donor, so both travel together (~80 MB).

## Layout

| Path | What |
|---|---|
| `scripts/` | 77 builders, checkpoint auditors and reporters |
| `scenarios/fd-sit/` | canonical scenario JSONs + `_dds-templates/` + per-set `_FD_*_index.json` |
| `docs/`, `LEARNINGS.md` | environment notes, per-domain recipes, historical gotchas |

Shared foundation: `scenario_engine.py` (scenario JSON → raw PNR ndjson), `publish_raw.py` (→ Kafka),
`crt_uniqnames.py` (DB-absent names), `pnr_common_checks.py` (shared checkpoint logic),
`universal_checkpoints.py` (full suite, any index, any env).

## What changed on vendoring

The scripts are otherwise **unmodified** — they are the proven artifact. Three portability fixes:

1. **Root resolution.** `KB` was a hardcoded absolute path to the original checkout, so a vendored
   copy would silently read and write the *old* tree. It now derives from the script's own location:
   `KB = os.environ.get("CCTQA_DATAGEN_ROOT", <parent of scripts/>)`. Same for the two `.sh` sweeps
   (zsh `${0:a:h:h}`).
2. **Credentials removed from source.** This tree is version-controlled with a remote; the originals
   carried a plaintext trip-tracer password, a rule-engine password and the DDS API key inline across
   23 files and 4 docs. All now resolve from the environment, matching `core/secrets.py` policy. The
   CRT trip-tracer config uses its Secrets Manager entry like `int`/`bat` already did, with a
   credential-pair fallback (the proxy accepts only `dbdevuser`, the rule-engine cluster only
   `dbadmin` — picking one statically fails half the paths).
3. **Work directories.** Defaults pointed at scratchpad paths from expired sessions; they now use
   `/tmp/cctqa-datagen`. Env overrides (`CRT239_WORK`, `BC_WORK`, …) still win.

## Running it

```bash
export AWS_PROFILE=ac-cct-crt          # or ARC75-Temp-INT / CCE-Developer-BAT
export DDS_API_KEY=...                 # DDS by-pnr endpoint
aws sso login --profile $AWS_PROFILE   # tokens last ~1h; finalize needs a live one
warp-cli status                        # must be Connected — brokers/DB/endpoint resolve over WARP

# verify an existing set (read-only)
python3 scripts/fd_checkpoints.py scenarios/fd-sit/_FD_SIT132_crt_index.json --env crt

# build a fresh set: index -> clone -> publish -> checkcascade -> finalize, then verify
python3 scripts/crt_fd_build239.py index      # see HOWTO §5 for the full env-var set
```

A set is done **only** when the checkpoint script prints `PASS ✅`.

## Time-sensitive data

`PENDING flight≤72h` fails once the seeded flight drifts outside ±3 days of today — by design, not a
defect. A PENDING case re-audited more than 3 days after seeding needs its flight re-dated and the
determination re-pinned. Everything else is stable.

## Seeding checklist (per domain) — run every step, don't skip verify

Baked-in requirements learned from live CRT seeding. The flow per domain:

```
index  →  publish  →  checkcascade  →  finalize  →  <domain>_checkpoints.py   (MANDATORY)
```

A set is done only when its checkpoint script prints `PASS ✅`. Checkpoints are not optional —
they are the definition of "seeded correctly".

**Before building:**
- **Free ticket prefix** — never reuse a prefix. A consumed prefix does not error; the ticket
  insert is `ON CONFLICT DO NOTHING`, so tickets are silently dropped. Use
  `_cctdb.free_ticket_prefix()` (scans trip-tracer) and pass it via the builder's `*_TPREFIX` env.
- **Unique names** — set `CRT_UNIQ_NAMES=1` for DB-absent unique passenger names (the default is
  OFF, which reuses canonical names already in the DB). All builders support it, incl.
  crt_fd_build239 now. When building several sets in one batch, seed each before building the next
  (or use distinct `*_SEED` values) so their generated name pools don't overlap.
- **Contact** — `CRT_EMAIL=lahiru@ae-qa1-aircanada.mailinator.com CRT_PHONE=+94712534323`.

**Environment facts (already wired):**
- DB credentials resolve from Secrets Manager via `_cctdb` (trip_tracer / rule_engine), trying both
  credential pairs. No password lives in source. `_cctdb` also reads a local secret cache
  (`/tmp/cctqa_secrets.json`) so a session survives SSO token lapses — write it once while
  authenticated.
- DDS/eligibility endpoint host is `rule-engine-platform-service-**be**.ac-cct-crt.cloud.aircanada.com`
  (the `-be` matters; without it the host does not resolve). DDS reads work live there; the
  eligibility COMPUTE endpoint (sc/nc/bc) is health-only on the ALB and 403s on the API Gateway, so
  those checkpoints validate via the offline rule-replica against the live DB — automatic in the
  checkpoint scripts, not a manual choice.
- MSK/Kafka TLS uses certifi (a python.org build ships no CA bundle).

**PENDING cases** (FD/SOC PE-*) are time-sensitive: their flight must be within ±72h of today.
crt_fd_build239 now dates them near-term at clone time (`CRT239_PENDING_DATE`, default today-2) and
shifts the scenario segments + DDS to match, so the cascade produces a consistent eds
promisedWindow. They still age out in ~3 days — re-seed (or re-date) before a PENDING test run.

**Long finalize** (239-case) holds a DB connection across the S3-put loop; it reconnects + retries
on a dropped connection. SSO tokens are short — keep a session alive across the ~28-min finalize, or
re-run (idempotent: `--start N`).
