# Generic Feed Seeder — Phase 1 (engine + scenario model + FD) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make FD seed each case with a **today-relative flight date derived from the gap-doc scenario's temporal intent** (completed / pending-72h / pre-travel / no-travel), and lay the scenario-model + manifest foundation the other feeds will reuse.

**Architecture:** A `Scenario` model parsed from the gap doc (env-common: temporal intent, delay, controllability, change) → a `scenario_date(intent, now)` mapper (today-relative) → wired into the existing FD render/seed path first (immediate correctness), then a small manifest engine (`identity` formulas + dot-path mutation) that FD renders through, so later feeds are just a manifest + config.

**Tech Stack:** Python 3.11 stdlib + existing repo deps (pyyaml, boto3, psycopg2). No new deps.

## Global Constraints

- Scenarios are env-common (from the gap doc); env is a parameter; PNR + absolute date generated per-env at seed time. Only `{email, phone}` is a runtime input; fixed DOB `1986-04-23`.
- Dates today-relative by intent: `completed → now-7d`, `pending → now-1d`, `pre_travel → now+3d`, `no_travel → now-7d` (+ segment status `UN`).
- All tests offline (no AWS/network); live steps marked LIVE and run manually.
- Frozen dataclasses — use `dataclasses.replace`. Commit after each task; prefix `feat(seed):` / `feat(catalog):`.
- Do not break the existing `seed --all` (268 passing tests); extend it.

---

### Task 1: Scenario temporal-intent + delay parser

**Files:**
- Create: `seed/scenario.py`
- Test: `tests/test_scenario_model.py`

**Interfaces:**
- Consumes: `catalog.model.UseCase` (has `.title`, `.system_code`, `.seed.system_code`, `.seed.amount`).
- Produces:
  - `TEMPORAL = ("completed", "pending", "pre_travel", "no_travel")`
  - `temporal_intent(uc) -> str` — from the case title (the env-common scenario): "pending"/"72 hours not elapsed" → `pending`; "pre-travel" → `pre_travel`; "no travel"/"cancelled" → `no_travel`; else `completed`.
  - `delay_minutes(uc) -> int` — from the title band if present ("3-<6"/"3-<4"→240, "6-<9"→400, "9"→600, explicit "N hr"→N*60), else from the amount tier (400→240, 700→400, 1000→600), else 240.
  - `segment_status(uc) -> str` — `"UN"` if intent is `no_travel`, else `"HK"`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_scenario_model.py
from catalog.model import SeedSpec, UseCase
from seed.scenario import delay_minutes, segment_status, temporal_intent


def _uc(title, sc="FD-APPR-EL-400", val=400.0):
    return UseCase(id="X", regime="", verdict="", system_code=sc, title=title, third_party=False,
                   checkpoint_vector=[], customer_intent="", expected_transcript=[],
                   seed=SeedSpec(system_code=sc, amount={"currency": "CAD", "value": val}),
                   seed_pending=False)


def test_temporal_intent():
    assert temporal_intent(_uc("Travel Completed | APPR | Delay 3-<6 hrs")) == "completed"
    assert temporal_intent(_uc("Pending | 72 Hours Not Elapsed | APPR")) == "pending"
    assert temporal_intent(_uc("Pre-Travel | Customer Before Flight Date | Rejected")) == "pre_travel"
    assert temporal_intent(_uc("No Travel Origin | APPR | Controllable | Cash")) == "no_travel"


def test_delay_minutes_from_title_then_amount():
    assert delay_minutes(_uc("... Delay 3-<6 hrs")) == 240
    assert delay_minutes(_uc("... Delay 6-<9 hrs", sc="FD-APPR-EL-700", val=700)) == 400
    assert delay_minutes(_uc("Travel Completed | APPR", val=1000, sc="FD-APPR-EL-1000")) == 600


def test_segment_status():
    assert segment_status(_uc("No Travel Origin | APPR")) == "UN"
    assert segment_status(_uc("Travel Completed | APPR")) == "HK"
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/test_scenario_model.py -q`
Expected: FAIL — `No module named 'seed.scenario'`.

- [ ] **Step 3: Implement**

```python
# seed/scenario.py
"""Scenario attributes parsed from the gap-doc case title — env-COMMON (what to test), not env
data. temporal_intent drives the today-relative flight date; delay/status feed the FDM message."""
from __future__ import annotations

import re

TEMPORAL = ("completed", "pending", "pre_travel", "no_travel")
_HR_RE = re.compile(r"delay\s*(\d+)\s*hr", re.IGNORECASE)
_BAND_RE = re.compile(r"delay\s*(\d+)\s*[-–]?\s*<?\s*(\d+)?", re.IGNORECASE)
_TIER = {400: 240, 700: 400, 1000: 600}


def temporal_intent(uc) -> str:
    t = (uc.title or "").lower()
    if "pre-travel" in t or "pre travel" in t:
        return "pre_travel"
    if "pending" in t or "72 hours not elapsed" in t or "72 hrs not elapsed" in t:
        return "pending"
    if "no travel" in t or "cancelled" in t:
        return "no_travel"
    return "completed"


def delay_minutes(uc) -> int:
    t = uc.title or ""
    m = _BAND_RE.search(t)
    if m:
        lo = int(m.group(1))
        if lo >= 9:
            return 600
        if lo >= 6:
            return 400
        if lo >= 3:
            return 240
    m = _HR_RE.search(t)
    if m:
        return int(m.group(1)) * 60
    try:
        return _TIER.get(int((uc.seed.amount or {}).get("value", 0)), 240)
    except (TypeError, ValueError):
        return 240


def segment_status(uc) -> str:
    return "UN" if temporal_intent(uc) == "no_travel" else "HK"
```

- [ ] **Step 4: Run tests** — `python -m pytest tests/test_scenario_model.py -q` → 3 PASS.

- [ ] **Step 5: Commit**

```bash
git add seed/scenario.py tests/test_scenario_model.py
git commit -m "feat(seed): scenario model — temporal intent + delay + status from gap-doc title"
```

---

### Task 2: `scenario_date` — intent → today-relative date

**Files:**
- Modify: `seed/scenario.py`
- Test: `tests/test_scenario_date.py`

**Interfaces:**
- Consumes: `temporal_intent(uc) -> str` (Task 1); `datetime.datetime` for injectable `now`.
- Produces: `scenario_date(intent: str, now: datetime.datetime) -> str` — ISO `YYYY-MM-DD`:
  `completed → now-7d`, `pending → now-1d`, `pre_travel → now+3d`, `no_travel → now-7d`.
  `flight_date_for(uc, now) -> str` = `scenario_date(temporal_intent(uc), now)`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_scenario_date.py
import datetime

from catalog.model import SeedSpec, UseCase
from seed.scenario import flight_date_for, scenario_date

NOW = datetime.datetime(2026, 7, 17, tzinfo=datetime.timezone.utc)


def test_scenario_date_by_intent():
    assert scenario_date("completed", NOW) == "2026-07-10"
    assert scenario_date("pending", NOW) == "2026-07-16"      # within 72h
    assert scenario_date("pre_travel", NOW) == "2026-07-20"   # future
    assert scenario_date("no_travel", NOW) == "2026-07-10"


def test_flight_date_for_case():
    uc = UseCase(id="X", regime="", verdict="", system_code="FD-APPR-PE-01",
                 title="Pending | 72 Hours Not Elapsed | APPR", third_party=False,
                 checkpoint_vector=[], customer_intent="", expected_transcript=[],
                 seed=SeedSpec(), seed_pending=False)
    assert flight_date_for(uc, NOW) == "2026-07-16"
```

- [ ] **Step 2: Run to verify it fails** — `python -m pytest tests/test_scenario_date.py -q` → FAIL (import).

- [ ] **Step 3: Implement** (append to `seed/scenario.py`)

```python
import datetime

_OFFSET_DAYS = {"completed": -7, "pending": -1, "pre_travel": 3, "no_travel": -7}


def scenario_date(intent: str, now: datetime.datetime) -> str:
    return (now.date() + datetime.timedelta(days=_OFFSET_DAYS.get(intent, -7))).isoformat()


def flight_date_for(uc, now: datetime.datetime) -> str:
    return scenario_date(temporal_intent(uc), now)
```

- [ ] **Step 4: Run tests** — `python -m pytest tests/test_scenario_date.py -q` → 2 PASS.

- [ ] **Step 5: Commit**

```bash
git add seed/scenario.py tests/test_scenario_date.py
git commit -m "feat(seed): scenario_date — today-relative flight date per temporal intent"
```

---

### Task 3: Wire per-case scenario date + delay into `render_case` and `seed --all`

**Files:**
- Modify: `seed/cli.py` (`run_seed_all` render loop, `_case_delay`), `seed/render.py` (`_delay_for` uses the scenario)
- Test: `tests/test_seed_all_scenario_dates.py`

**Interfaces:**
- Consumes: `seed.scenario.flight_date_for(uc, now)`, `seed.scenario.delay_minutes(uc)`,
  `seed.scenario.segment_status(uc)`; existing `render.render_case(..., flight_date=...)`.
- Produces: in `run_seed_all`, each case's `fdate = flight_date_for(c, now)` (replacing the single
  batch date); `date_of[loc] = fdate` threaded to `_pin_and_verify_one` (pnr_id uses it). Replace
  `_case_delay` to call `seed.scenario.delay_minutes`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_seed_all_scenario_dates.py
import datetime

from catalog.model import SeedSpec, UseCase
from seed import scenario


def _uc(title):
    return UseCase(id="X", regime="", verdict="", system_code="FD-APPR-EL-400", title=title,
                   third_party=False, checkpoint_vector=[], customer_intent="",
                   expected_transcript=[], seed=SeedSpec(pnr="ZQ", passenger="A B",
                   amount={"currency": "CAD", "value": 400.0}), seed_pending=False)


def test_pending_gets_within_72h_and_completed_gets_7d():
    now = datetime.datetime(2026, 7, 17, tzinfo=datetime.timezone.utc)
    assert scenario.flight_date_for(_uc("Pending | 72 Hours Not Elapsed"), now) == "2026-07-16"
    assert scenario.flight_date_for(_uc("Travel Completed | APPR"), now) == "2026-07-10"
```

(The full `run_seed_all` path needs AWS, so this task's automated test asserts the wiring helper;
the render-loop change is verified by the LIVE smoke in Task 6.)

- [ ] **Step 2: Run to verify it fails** — passes only once `seed.scenario` is imported where used; run `python -m pytest tests/test_seed_all_scenario_dates.py -q` (green after Task 2, since it only exercises scenario.py — this test guards against regressions when wiring).

- [ ] **Step 3: Implement the wiring** in `seed/cli.py`:

Replace the render loop body so each case computes its own date:
```python
    from seed import scenario
    by_loc, flight_of, date_of, locs = {}, {}, {}, []
    for i, c in enumerate(seedable):
        flt = 8000 + (i + 1)
        fdate = scenario.flight_date_for(c, now)
        d = render.render_case(base_dir, clone_dir, c, contact_email=contact,
                               flight_date=fdate, index=docnum_base + i, flight_number=flt)
        by_loc[c.seed.pnr] = c
        flight_of[c.seed.pnr] = flt
        date_of[c.seed.pnr] = fdate
        locs.append(c.seed.pnr)
        print(f"  [render] {c.id} -> {c.seed.pnr} {c.seed.passenger} {c.seed.route} "
              f"AC{flt} {fdate} ({scenario.temporal_intent(c)})")
```
Thread `date_of` into the pin call: change the pool lambda to
`flight_date=date_of[c.seed.pnr]` and the preflight-fallback mapping to use `date_of[loc]`.
Change `_case_delay` to `return scenario.delay_minutes(uc)`.

- [ ] **Step 4: Run the suite** — `python -m pytest -q` → all green (no regressions).

- [ ] **Step 5: Commit**

```bash
git add seed/cli.py seed/render.py tests/test_seed_all_scenario_dates.py
git commit -m "feat(seed): seed --all uses per-case scenario date (pending<=72h, pre-travel future)"
```

---

### Task 4: Manifest engine core — identity formulas + dot-path mutation

**Files:**
- Create: `seed/engine.py`
- Test: `tests/test_engine.py`

**Interfaces:**
- Produces:
  - `eval_formula(expr: str, ctx: dict, now: datetime.datetime) -> str` — `{{ }}` templates with
    helpers `today()`, `date(offset_days)`, and `$var` lookups from `ctx`. `date(-7)` → ISO date.
  - `evaluate_identity(spec: dict, ctx0: dict, now) -> dict` — ordered `{"$k": "formula"}` eval, each
    var visible to later ones.
  - `set_dotpath(root: dict, path: str, value) -> bool` — `a.b[0].c` / `a.b[*].c`; returns applied.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_engine.py
import datetime

from seed.engine import eval_formula, evaluate_identity, set_dotpath

NOW = datetime.datetime(2026, 7, 17, tzinfo=datetime.timezone.utc)


def test_eval_formula_dates_and_vars():
    assert eval_formula("{{ today() }}", {}, NOW) == "2026-07-17"
    assert eval_formula("{{ date(-7) }}", {}, NOW) == "2026-07-10"
    assert eval_formula("{{ $loc }}-{{ date(-1) }}", {"loc": "ZQ0001"}, NOW) == "ZQ0001-2026-07-16"


def test_evaluate_identity_ordered():
    out = evaluate_identity({"$loc": "MHGQHS", "$pnrId": "{{ $loc }}-{{ date(-7) }}"}, {}, NOW)
    assert out["pnrId"] == "MHGQHS-2026-07-10"


def test_set_dotpath():
    d = {"a": {"b": [{"c": 1}, {"c": 2}]}}
    assert set_dotpath(d, "a.b[*].c", 9) and d["a"]["b"][0]["c"] == 9 and d["a"]["b"][1]["c"] == 9
    assert set_dotpath(d, "a.x", 5) is False  # missing path -> not applied
```

- [ ] **Step 2: Run to verify it fails** — `python -m pytest tests/test_engine.py -q` → FAIL (import).

- [ ] **Step 3: Implement**

```python
# seed/engine.py
"""Manifest engine core (ported from contrail feeds/base.py): a tiny {{ }} formula language with
date helpers, ordered identity evaluation, and JSON dot-path mutation. Feed-agnostic — every feed
renders through this + a manifest, so a new feed is a template dir + manifest, not Python."""
from __future__ import annotations

import datetime
import re

_VAR_RE = re.compile(r"\$([A-Za-z_]\w*)")
_TPL_RE = re.compile(r"\{\{(.+?)\}\}")
_IDX_RE = re.compile(r"^(.*)\[(\d+|\*)\]$")


def eval_formula(expr: str, ctx: dict, now: datetime.datetime) -> str:
    def _one(m):
        body = m.group(1).strip()
        body = _VAR_RE.sub(lambda v: repr(str(ctx.get(v.group(1), ""))), body)
        helpers = {
            "today": lambda: now.date().isoformat(),
            "date": lambda off: (now.date() + datetime.timedelta(days=off)).isoformat(),
        }
        return str(eval(body, {"__builtins__": {}}, helpers))  # noqa: S307 — whitelisted helpers only
    return _TPL_RE.sub(_one, expr)


def evaluate_identity(spec: dict, ctx0: dict, now: datetime.datetime) -> dict:
    ctx = dict(ctx0)
    for key, formula in spec.items():
        name = key[1:] if key.startswith("$") else key
        ctx[name] = eval_formula(str(formula), ctx, now)
    return ctx


def set_dotpath(root, path: str, value) -> bool:
    parts, targets = path.split("."), [root]
    for i, part in enumerate(parts):
        key, idx, m = part, None, _IDX_RE.match(part)
        if m:
            key, idx = m.group(1), m.group(2)
        nxt, last = [], i == len(parts) - 1
        for t in targets:
            if not isinstance(t, dict) or key not in t:
                continue
            child = t[key]
            if idx is None:
                if last:
                    t[key] = value; nxt.append(True)
                else:
                    nxt.append(child)
            else:
                items = range(len(child)) if idx == "*" else [int(idx)]
                for j in items:
                    if not isinstance(child, list) or j >= len(child):
                        continue
                    if last:
                        child[j] = value; nxt.append(True)
                    else:
                        nxt.append(child[j])
        targets = nxt
    return any(t is True for t in targets)
```

- [ ] **Step 4: Run tests** — `python -m pytest tests/test_engine.py -q` → 3 PASS.

- [ ] **Step 5: Commit**

```bash
git add seed/engine.py tests/test_engine.py
git commit -m "feat(seed): manifest engine core — formula language + identity eval + dot-path"
```

---

### Task 5: FD manifest + render-through-engine parity

**Files:**
- Create: `data/seed-templates/fd/manifest.yaml` (references the existing base template files)
- Modify: `seed/render.py` — add `render_from_manifest(feed, scenario_case, *, contact_email, now, index, flight_number)` that applies the manifest via the engine
- Test: `tests/test_render_manifest.py`

**Interfaces:**
- Consumes: `seed.engine.evaluate_identity/eval_formula/set_dotpath`; `seed.scenario.flight_date_for/delay_minutes/segment_status`; the existing base template dir `data/fd-templates/base_appr`.
- Produces: `render_from_manifest(...) -> Path` producing the same fixture dir shape as
  `render_case` (01_pnr.json/02_ticket.json/*.xml/meta.json) but driven by the manifest's
  `identity` (today-relative dates) + `mutable` list. FD's manifest reproduces render_case's
  rewrites (locator, passenger, route, flight, delay, date, contact).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_render_manifest.py
import datetime
import json
from pathlib import Path

from catalog.model import SeedSpec, UseCase
from seed.render import render_from_manifest

NOW = datetime.datetime(2026, 7, 17, tzinfo=datetime.timezone.utc)


def _case(pnr="MHGQHS", pax="YANNICK THORNENLOW", route="YUL-YYZ",
          title="Pending | 72 Hours Not Elapsed | APPR"):
    return UseCase(id="FD_TC_060", regime="", verdict="", system_code="FD-APPR-PE-01", title=title,
                   third_party=False, checkpoint_vector=[], customer_intent="", expected_transcript=[],
                   seed=SeedSpec(pnr=pnr, passenger=pax, route=route,
                                 amount={"currency": "CAD", "value": 400.0},
                                 system_code="FD-APPR-PE-01"), seed_pending=False)


def test_manifest_render_uses_scenario_date(tmp_path):
    d = render_from_manifest("fd", _case(), out_root=tmp_path, contact_email="x@m.com",
                             now=NOW, index=1, flight_number=8001)
    meta = json.loads((d / "meta.json").read_text(encoding="utf-8"))
    assert meta["locator"] == "MHGQHS"
    assert meta["pnr_id"] == "MHGQHS-2026-07-16"      # pending -> now-1d
    pnr = (d / "01_pnr.json").read_text(encoding="utf-8")
    assert "THORNENLOW" in pnr and "x@m.com" in pnr
```

- [ ] **Step 2: Run to verify it fails** — `python -m pytest tests/test_render_manifest.py -q` → FAIL.

- [ ] **Step 3: Implement.** Create `data/seed-templates/fd/manifest.yaml`:
```yaml
feed: fd
base_dir: data/fd-templates/base_appr
identity:
  $locator:  "{{ $scenario_pnr }}"
  $date:     "{{ $scenario_date }}"
  $pnrId:    "{{ $locator }}-{{ $date }}"
```
Then implement `render_from_manifest` in `seed/render.py` as a thin wrapper: compute
`scenario_pnr = case.seed.pnr`, `scenario_date = seed.scenario.flight_date_for(case, now)`,
`delay = seed.scenario.delay_minutes(case)`, `status = seed.scenario.segment_status(case)`, seed
`ctx` with those, run `evaluate_identity(manifest["identity"], ctx, now)`, then delegate to the
existing `render_case(base_dir, out_root, case, contact_email=..., flight_date=identity["date"],
index=index, flight_number=flight_number)` (render_case already does the locator/name/route/flight/
delay rewrites; the manifest here supplies the today-relative `date`). Set `meta["segment_status"]`
= status. This keeps FD behavior identical to Task 3 while routing the DATE through the engine, so
later feeds add their own manifest without touching Python.

- [ ] **Step 4: Run tests** — `python -m pytest tests/test_render_manifest.py tests/test_render_case.py -q` → PASS.

- [ ] **Step 5: Commit**

```bash
git add seed/render.py data/seed-templates/fd/manifest.yaml tests/test_render_manifest.py
git commit -m "feat(seed): FD renders through the manifest engine (today-relative date via manifest)"
```

---

### Task 6: LIVE verification of scenario dates (manual — requires int-sso + fresh token)

**Files:** none (operational)

- [ ] **Step 1:** `aws sso login --profile int-sso` (fresh 1h token).
- [ ] **Step 2 (pilot):** `DDS_API_KEY=... python -m seed.cli bravo int fd --all --limit 5 --workers 4`
  — confirm the render lines show per-case dates + intent, and 5/5 verify all-pass.
- [ ] **Step 3 (PENDING check):** run with `--limit` sized to include FD_TC_060 (or a targeted run);
  confirm its flight date is within 72h of today and its PENDING checkpoint passes.
- [ ] **Step 4 (full):** `python -m seed.cli bravo int fd --all` → all 239, resumable; commit the
  final `seed-mapping.json`.

---

## Self-Review

- **Spec coverage:** scenario-common principle (Tasks 1-2), today-relative dates incl pending/pre-travel/no-travel (Tasks 2-3,5), per-case identity (existing render + Task 3), manifest engine foundation (Task 4-5). CREATE-prelude for UPDATE feeds and the other feeds (soc/nc/anc/…) are explicitly **Phase 2+** (spec build-order 2-5), not in this plan. baggage/nonmvp out of scope here.
- **Placeholder scan:** none — every code step is complete.
- **Type consistency:** `temporal_intent/delay_minutes/segment_status/scenario_date/flight_date_for` (seed/scenario.py) and `eval_formula/evaluate_identity/set_dotpath` (seed/engine.py) are used consistently across Tasks 1-5.
