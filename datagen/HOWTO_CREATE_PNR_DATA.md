# How to Create FD ("Ask AC") Test PNR Data

A practical guide for creating and verifying Flight-Disruption test PNRs in the CCT
environments (INT / BAT / CRT). Written for someone doing this for the first time.

> **TL;DR** — pick an environment, connect WARP + SSO, run the builder's phases
> (`index → clone → publish → checkcascade → finalize`), then **verify with
> `fd_checkpoints.py`**. A PNR is "done" only when the checkpoint script prints
> `PASS ✅`.

---

## 1. What you are building (mental model)

The "Ask AC" bot reads **two independent sources**. A valid test PNR must seed **both**:

1. **BOOKING** → the `trip-tracer` Aurora DB, reached by **publishing a PNR to Kafka**
   which cascades (~30s) into `trip / trip_details / passenger / flight_segment /
   eds_pnr_output`.
2. **DDS verdict** (the eligibility + dollar amount) → written to **S3** and **pinned**
   in the rule-engine `execution_traces` table, then served by the
   **`/rule-engine/dds/output/<pnrId>`** endpoint.

`dds_pnr_output` (in trip-tracer) is a **decoy** — the bot does NOT read it. The verdict
comes from S3 + `execution_traces`.

A `pnrId` is `<6-char-locator>-<flight-date>`, e.g. `ABCDEF-2026-06-15`.

---

## 2. Environments

| | INT | BAT | CRT |
|---|---|---|---|
| AWS account | 982081066747 | 209479273605 | 050752605169 |
| AWS profile | `ARC75-Temp-INT` | `CCE-Developer-BAT` | `ac-cct-crt` |
| PNR Kafka topic | `emh-int.ALTEA-PNRDATA-INT` | `emh-dev.ALTEA-PNRDATA-INT` | `emh-dev.ALTEA-PNRDATA-UAT` |
| trip-tracer | `...rds-proxy-int-cac1...` | `...rds-proxy-bat-cac1...` | `...rds-cluster-crt-cac1...` (direct dbadmin) |
| rule-engine RDS (execution_traces, db `postgres`) | ECS-Exec | `...rule-engine-bat-cac1...` | `...rule-engine-crt-cac1-rds-cluster...` |
| DDS S3 bucket | `ac-cct-rule-engine-store-int` | `cct-ask-ac-bat-logs` | `cct-ask-ac-crt-logs` |
| DDS endpoint host | `rule-engine-platform-service.ac-cct-int.cloud.aircanada.com` | `...ac-cct-bat...` | `...ac-cct-crt...` |
| DDS api-key | `$DDS_API_KEY (export it; not stored in the repo)` (same everywhere) | | |

> Note: **"SIT" == CRT** — there is no separate SIT environment. CRT's Kafka topic
> uses the `-UAT` suffix (`emh-dev.ALTEA-PNRDATA-UAT`).

---

## 3. Prerequisites (every session)

1. **WARP / Cloudflare must be Connected** (private brokers + DB + endpoint DNS resolve
   only over WARP): `warp-cli status` → `Connected`.
2. **AWS SSO login** for your target env:
   ```
   aws sso login --profile ac-cct-crt        # (or ARC75-Temp-INT / CCE-Developer-BAT)
   ```
   SSO expires ~1h — re-run when S3/Secrets calls return `ExpiredToken`.
   Publishing (kcat over WARP) does **not** need SSO; **finalize (S3 + pin) does**.
3. Python deps available: `boto3`, `psycopg2`, and `kcat` on PATH.

---

## 4. The tooling (in `scripts/`)

| Script | Purpose |
|---|---|
| `crt_fd_build239.py` | **Full FD catalog** (239 cases: 152 EL / 68 NE / 16 ND / 3 PE). Phase-based, env-configurable. |
| `crt_fd_build.py` | CRT **eligible-only** sets (91 ELIG + 44 SIT), named-set interface. |
| `bat_fd_build.py`, `int_fd_build.py` | Same recipe for BAT / INT. |
| `fd_checkpoints.py` | **The verifier.** Audits every area the bot depends on. `PASS`/`FAIL`. |
| `crt_uniqnames.py` | Shared unique-passenger-name helper (see §8). |
| `scenario_engine.py` | Renders a scenario JSON → raw PNR ndjson. |
| `publish_raw.py` | Publishes ndjson to a Kafka topic (`--live`). |

The builders are **phase-based and idempotent**, driven off a per-set index JSON:

```
index  →  clone  →  publish  →  checkcascade  →  finalize  →  verify
```

---

## 5. Create a set — step by step (CRT, full 239 example)

The builder is parameterised by env vars so you never edit the script. Pick:

- **contact** (`CRT_EMAIL` / `CRT_PHONE`)
- a **fresh, collision-free ticket prefix** (see §6)
- an **output index path**, a **seed**, and a **work dir**.

```bash
cd "/Users/chathuranga/QA Agents/CCT_Agent/cct-crt-kb"

export CRT_EMAIL="lahiru@ae-qa1-aircanada.mailinator.com"
export CRT_PHONE="+94712534323"
export CRT239_OUT="$PWD/scenarios/fd-sit/_FD_ALL239_crtNEW_index.json"
export CRT239_TPREFIX="014363"          # <-- a FREE prefix (see §6)
export CRT239_SEED="812108"             # <-- any distinct int (fresh locators)
export CRT239_WORK="/tmp/crt239_new_work"

# 1) build the index (fresh locators + tickets, no collisions)
python3 scripts/crt_fd_build239.py index

# 2) clone scenarios + DDS to the work dir (OAL cases auto AC-ified)
python3 scripts/crt_fd_build239.py clone

# 3) (only for the 3 PENDING cases) date their flight within ±72h of today — see §7
#    quick patch: replace 2026-06-15 with a near-term date in the 3 PENDING DDS files

# 4) publish all 239 to Kafka  (~22 min; run in background)
python3 scripts/crt_fd_build239.py publish

# 5) confirm the cascade
python3 scripts/crt_fd_build239.py checkcascade      # -> 239/239 present

# 6) finalize: ticket insert + DOB + GROUP flag + S3 put + execution_traces pin
#    (needs SSO)   (~28 min; run in background)
python3 scripts/crt_fd_build239.py finalize
```

For **eligible-only** CRT sets use `crt_fd_build.py <set> <phase>` where `<set>` is a
named entry (`elig91`, `sit44`, …) — same phases.

---

## 6. Pick a FREE ticket prefix (mandatory)

FD tickets are `<6-digit-prefix>000001 … 000239`. Many prefixes are already consumed by
other CRT test sets. **Scan for a prefix whose low band is empty** before building:

```python
import psycopg2
c=psycopg2.connect(host="ac-cct-trip-tracer-rds-cluster-crt-cac1.cluster-cxqe2wacy866.ca-central-1.rds.amazonaws.com",
   port=5432,dbname="trip-tracer",user="dbadmin",password="$CCT_TRIPTRACER_PASSWORD",sslmode="require")
cur=c.cursor()
for n in range(14363, 14420):
    p=f"0{n}"
    cur.execute("select count(*) from ticket where primary_document_number between %s and %s",
                (f"{p}000001", f"{p}000300"))
    if cur.fetchone()[0]==0:
        print("FREE:", p); break
```

A ticket collision doesn't error (finalize uses `ON CONFLICT DO NOTHING`) — it **silently
drops** the ticket, and the checkpoint's `ticket` area catches it. Avoid it up front.

---

## 7. Gotchas (the things that bite first-timers)

- **OAL AC-ify** — a booking leg with a non-AC `operating_carrier` (PAL/WS/LH…) **blocks
  the trip-tracer cascade** (trip never created). Keep booking legs AC-operated; put the
  real OAL carrier only in the pinned DDS `mslFlight`. `crt_fd_build239.py` does this
  automatically for `oal` cases (TC183/184).
- **PENDING flight ≤ 72h** — a `PENDING` verdict only holds if the flight is within ±3
  days of *today*. The canonical PENDING DDS templates carry a stale flight date — re-date
  the 3 PENDING DDS files to ~today **before finalize**, then re-pin. This check is
  time-sensitive: re-audit >3 days later and they need a fresh date.
- **Forced TC063** — the pre-travel case has no real DDS; it's built as an APPR EL-400
  shell. `crt_fd_build239.py` restores it to `ELIGIBLE / FD-APPR-EL-400 / pinned`
  automatically.
- **eds straggler** — occasionally ~1/239 cascades trip/passenger/segment but gets **0
  `eds_pnr_output` rows**. Fix: **version-bump republish** that one PNR (set
  `processedPnr.version="10"` + a later `lastModification.dateTime`/`originFeedTimeStamp`
  in its ndjson) to force reprocessing, wait ~40s, then re-finalize that index. The
  checkpoint's `eds_pnr_output` area catches these.
- **Email change after cascade = version-bump republish** — re-publishing the *same* PNR
  version is deduped by the cascade, so the eds contact won't update. Bump the version.
- **Re-publishing nulls the DOB** — any republish requires re-running the DOB update
  (finalize does it).

---

## 8. Unique passenger names (optional but recommended for new sets)

The FD catalog reuses ~190 canonical names on every PNR — fine for eligibility, but the
names are **not unique** and already exist in the DB. To build a set with realistic,
DB-absent, unique names, set **`CRT_UNIQ_NAMES=1`** when running any builder:

```bash
CRT_UNIQ_NAMES=1 CRT_EMAIL=... CRT_PHONE=... CRT239_OUT=... CRT239_TPREFIX=... \
  python3 scripts/crt_fd_build239.py index      # names assigned here; flows through clone/publish
```

- Names come from `crt_uniqnames.py` (surnames generated + DB-filtered → never exhausts).
- Sets get a `uniq_names` flag; the checkpoint then **enforces** name uniqueness for that
  set. Legacy sets (flag absent) show `name uniq (info)` and are not failed.
- Default (env unset) leaves builder output **unchanged**.

---

## 9. VERIFY — the checkpoints (this is the definition of "done")

Run the auditor against the set's index. It checks **every** area the bot depends on and
prints per-area `N/total` + a final `PASS ✅` / `FAIL ❌`:

```bash
AWS_PROFILE=ac-cct-crt python3 scripts/fd_checkpoints.py \
    scenarios/fd-sit/_FD_ALL239_crtNEW_index.json --env crt
```

Areas verified: **trip ACTIVE · trip_details · passenger · DOB · ticket ·
eds_pnr_output · eds contact email · GROUP context · DDS endpoint (systemCode match) ·
DDS amount match · NE/ND reason text · AC-Wallet loyalty · passenger count ·
PENDING flight≤72h · name uniqueness**.

- Verification is **systemCode-match**, not eligible-only — it correctly validates the
  NOT_ELIGIBLE / NO_DETERMINATION / PENDING cases too.
- `--env` = `int` | `bat` | `crt`.
- **Only report a set as done when `fd_checkpoints.py` prints `PASS ✅`.** If any area
  fails, fix it (see §7) and re-run.

Every domain has its own checkpoint script following the same pattern: `fd_checkpoints.py`,
`anc_checkpoints.py`, `bag_checkpoints.py`, `bc_checkpoints.py`, `sc_checkpoints.py`,
`nc_checkpoints.py`, `nmvp_checkpoints.py`.

---

## 10. Copy-paste PROMPT (for an AI agent / Claude Code)

Fill in the **bracketed** parts and paste this to your agent:

```
Create a fresh set of FD ("Ask AC") test PNR data in the [CRT] environment, and verify it
with the checkpoint script.

Set:
- Dataset: [the full 239-case catalog  |  the 91 eligible + 44 SIT sets]
- Contact: email [lahiru@ae-qa1-aircanada.mailinator.com], phone [+94712534323]
- DOB 1986-04-23
- Unique passenger names: [YES — set CRT_UNIQ_NAMES=1  |  NO]

Follow the recipe in cct-crt-kb/HOWTO_CREATE_PNR_DATA.md and the memory
[[fd-crt-test-data-creation-rule-engine]] + [[fd-creation-checkpoints]]:

1. Confirm WARP is Connected and I am logged in (aws sso login --profile ac-cct-crt);
   ask me to log in if SSO is expired. Finalize needs SSO; publish does not.
2. SCAN trip-tracer for a FREE ticket prefix (empty 000001-000300 band) — do NOT reuse a
   consumed prefix. Use fresh locators (a new seed) and a fresh output index path.
3. Build with scripts/crt_fd_build239.py phases: index → clone → publish → checkcascade →
   finalize (env: CRT_EMAIL, CRT_PHONE, CRT239_OUT, CRT239_TPREFIX, CRT239_SEED,
   CRT239_WORK; add CRT_UNIQ_NAMES=1 if unique names requested). Run the long phases
   (publish ~22min, finalize ~28min) in the background.
4. Apply the gotchas BEFORE finalize: OAL cases AC-ified (automatic), the 3 PENDING DDS
   flight dates re-dated to within ±72h of today, forced TC063 = EL-400 shell (automatic).
5. VERIFY with:
     AWS_PROFILE=ac-cct-crt python3 scripts/fd_checkpoints.py <index.json> --env crt
   It MUST print PASS ✅ across ALL areas. If any area fails (e.g. one eds straggler),
   fix it (version-bump republish that PNR + re-finalize) and re-run checkpoints until
   full PASS. Do not claim done until PASS.
6. Produce an HTML + CSV report in ~/Downloads and give me: the ticket series used, the
   status mix, and the checkpoint result.
```

---

## 11. Quick reference — where things live

- Builders / verifier / helper: `cct-crt-kb/scripts/`
- Canonical scenarios + DDS templates: `cct-crt-kb/scenarios/fd-sit/` (+ `_dds-templates/`)
- Per-set index JSONs: `cct-crt-kb/scenarios/fd-sit/_FD_*_index.json`
- Reports: `~/Downloads/FD_*.{html,csv}`
- Recipe memories: `fd-crt-test-data-creation-rule-engine`, `fd-int-e2e-data-creation`,
  `fd-bat-test-data-creation`, `fd-creation-checkpoints`, `fd-group-booking-context`,
  `fd-multibound-pnr`, `sit-equals-crt-environment`.
