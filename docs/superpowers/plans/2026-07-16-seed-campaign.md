# Seed Campaign (all 239 FD cases → INT) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Seed every seedable FD gap-doc case onto INT, each provably mapped to its `FD_TC_###` id in a committed ledger, gate-verified via the existing checkpoint auditor, with honest `UNSEEDABLE` reporting for cases the tooling cannot faithfully materialize.

**Architecture:** Fix the dataset join so all 239 cases carry bound `SeedSpec`s → extend the cloner to rewrite passenger names → match each case to a structurally compatible source fixture → harvest real DDS determinations from INT for the non-eligible-APPR families → run a batched, resumable campaign (clone → Kafka → settle → DDS pin → verify → ledger) → audit coverage (catalog × ledger × live re-verify).

**Tech Stack:** Python 3.11 stdlib + existing repo deps (pyyaml, boto3, psycopg2, kafka client already used by `seed/`). No new dependencies.

## Global Constraints

- All tests offline (no AWS/network in pytest) — repo convention; live steps are explicitly marked "LIVE" and run manually.
- Every artifact keyed on `(product, env, feed, date)`; the ledger is committed to git.
- The campaign never fabricates data: unmatchable cases are reported `UNSEEDABLE(<reason>)`, never silently mis-seeded.
- Contact is always the env's mailinator contact (`kafka_seed.mailinator_contact(env)`); fixed DOB stays `1986-04-23`.
- Frozen dataclasses in `catalog/model.py` are immutable — use `dataclasses.replace`.
- Commit after each task; message prefix `feat(seed):`, `feat(catalog):`, etc. as shown.

---

### Task 1: Dataset join binds ALL cases

**Files:**
- Modify: `catalog/parser.py:253-289` (`join_dataset`)
- Test: `tests/test_catalog_join_all.py` (new)

**Interfaces:**
- Consumes: `catalog.parser.join_dataset(catalog, dataset_html, feed) -> Catalog` (existing).
- Produces: same signature, new behavior — every `UseCase` whose id matches a dataset row (by `_norm_id`) gets `seed=_build_seed(pairs, feed)`, `seed_pending=False`. Cases without a matching row keep their current seed/seed_pending. Existing 39-pending behavior becomes a subset of this.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_catalog_join_all.py
"""join_dataset must bind dataset rows to EVERY matching case, not just seed_pending ones."""
from pathlib import Path

from catalog.parser import join_dataset, parse_gap_doc
from core.registry import load_feed

FEED = load_feed("fd")


def test_join_binds_all_cases():
    cat = parse_gap_doc(FEED.gap_doc, FEED)
    joined = join_dataset(cat, FEED.dataset, FEED)
    bound = [c for c in joined.cases if c.seed.pnr and c.seed.passenger]
    assert len(bound) == len(joined.cases) == 239  # every case gets dataset data
    assert not any(c.seed_pending for c in bound)


def test_join_preserves_case_identity():
    cat = parse_gap_doc(FEED.gap_doc, FEED)
    joined = join_dataset(cat, FEED.dataset, FEED)
    tc1 = joined.by_id("FD_TC_001")
    assert tc1 is not None and tc1.seed.pnr  # e.g. "MHGQHS" in v15
    assert tc1.seed.system_code.startswith("FD-")
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/test_catalog_join_all.py -q`
Expected: FAIL — `len(bound)` is far below 239 (only pending cases bound today).

- [ ] **Step 3: Implement**

In `catalog/parser.py`, replace the per-case loop body of `join_dataset` (lines 274-286):

```python
    new_cases = []
    for uc in catalog.cases:
        pairs = by_norm_id.get(_norm_id(uc.id))
        if pairs is None:
            pairs = by_syscode.get(uc.system_code) if uc.system_code else None
        if pairs is None:
            new_cases.append(uc)  # no dataset row: keep as-is (incl. seed_pending)
            continue
        seed, third_party = _build_seed(pairs, feed)
        new_cases.append(dataclasses.replace(uc, seed=seed, third_party=third_party,
                                             seed_pending=False))
```

(Only change: drop the `if not uc.seed_pending: append; continue` short-circuit.)

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_catalog_join_all.py tests/test_fixtures_catalog.py tests/test_mapping_catalog.py -q` → all PASS.
Then full suite: `python -m pytest -q` → no new failures (the diff tests use gap-doc-only catalogs; if a diff test asserted pending counts post-join, update it to match the new all-bound behavior).

- [ ] **Step 5: Commit**

```bash
git add catalog/parser.py tests/test_catalog_join_all.py
git commit -m "feat(catalog): join_dataset binds dataset rows to every matching case"
```

---

### Task 2: Scenario generator — realistic identities (REVISED per CCT_Agent_New 3 reference)

> **Supersedes the original "cloner passenger rewrite" task.** Reference implementation:
> `../cct-qa-1/CCT_Agent_New 3/CCT_Agent_New/scripts/generate_fd_uat_scenarios.py` (READ IT FIRST —
> it generated 243 realistic FD UAT PNRs with the mapping doc `FD_UAT_PNR_MAPPING.md` that
> `catalog/mapping.py` already parses). Port its data model into the framework:
>
> - **Locator minting:** `ZFU` + case number — `FD_TC_001 → ZFU001`, `FD_TC_3P_01 → ZFU3P01`
>   (realistic 6-char locators that encode the case; NOT synthetic ZQ0001).
> - **Passenger bank:** port the reference's (first, last, gender, DOB) bank (~200 names) to
>   `data/passenger-bank.json`; assign per case index (`idx % len`), consecutive names for
>   multi-pax cases. Every seeded PNR gets a realistic, distinct passenger.
> - **Route banks per regime:** APPR domestic (YYZ-YVR, YUL-YYZ, …), EU261 (CDG-YUL, FRA-YYZ, …),
>   EU261_UK (LHR-YYZ, …), Guadeloupe (PTP-YUL), ASL (TLV-YYZ), OAL (YYZ-JFK) — origin/currency/
>   country per the reference's `ROUTES` table; widebody aircraft (77W) for longhaul.
> - **Dates:** flight date via existing `in_window_date()` (FD window >72h past, <14d); booking
>   date ~3 weeks earlier; segment status `UN` for cancelled/no-travel cases; delay minutes from
>   the case's tier (systemCode amount → APPR_TIERS: 400→240m, 700→420m, 1000→600m).
> - **Output:** a per-case `ScenarioSpec` consumed by Task 2b (fixture synthesis), plus an
>   auto-emitted `FD_UAT_PNR_MAPPING.md`-style table committed beside the ledger (parseable by
>   `catalog/mapping.py` — the human-readable twin of the YAML ledger).

New module `seed/scenario_gen.py`, test `tests/test_scenario_gen.py`: assert locator minting,
name-bank rotation, regime→route selection, tier→delay mapping, `UN` status for cancelled, and
mapping-doc emission. Follow the reference's logic faithfully; keep functions pure (no I/O except
the bank JSON) so tests stay offline.

### Task 2b: Fixture synthesis from ScenarioSpec

`clone_fixture` grows into `synthesize_fixture(donor_dir, out_root, spec)` in `seed/clone.py`:
donor = a structurally matching fixture (Task 4's matcher, unchanged); rewrites = locator, ticket
docnum, dates (existing) **plus** passenger names (first/surname across 01_pnr, 02_ticket*, FDM
XML, meta), route airports (origin/destination codes), flight number, and delay minutes in the FDM
XML. Same `_retext` text-replacement machinery, one guarded replace per field, meta updated to
match. Test `tests/test_clone_passenger.py` extends to route/flight/delay rewrites (donor
synthesized in-test as today). The original passenger-rewrite steps below remain valid as the
first increment of this task.

#### Original passenger-rewrite steps (increment 1 of Task 2b)

**Files:**
- Modify: `seed/clone.py:25-84` (`clone_fixture`), `seed/clone.py:97-107` (`clone_batch`)
- Test: `tests/test_clone_passenger.py` (new; model on existing `tests/test_clone.py` fixtures)

**Interfaces:**
- Consumes: existing `clone_fixture(src_dir, out_root, new_locator, *, contact_email, new_docnum=None, index=1, pnr_version=None, new_date=None) -> Path`.
- Produces: same plus keyword `new_passenger: str | None = None` — `"FIRST LAST"` (dataset format). When given, every occurrence of the source first name and surname (uppercase, from `meta["first"]`/`meta["surname"]`) is replaced across `01_pnr.json`, `02_ticket*.json`, `*.xml`, and `meta.json` gets `first`/`surname` updated. `clone_batch` gains `passengers: dict[str, str] | None = None` mapping new_locator → passenger.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_clone_passenger.py
"""clone_fixture(new_passenger=...) rewrites the passenger name across all fixture files."""
import json
from pathlib import Path

from seed.clone import clone_fixture
from tests.test_clone import make_src_fixture  # reuse the existing synthetic-fixture helper


def test_passenger_rewrite(tmp_path):
    src = make_src_fixture(tmp_path / "src", locator="FDAP36",
                           first="MARA", surname="OKONKWO")
    d = clone_fixture(src, tmp_path / "out", "ZQ0001", contact_email="x@m.com",
                      new_passenger="YANNICK THORNENLOW")
    pnr = (d / "01_pnr.json").read_text(encoding="utf-8")
    assert "OKONKWO" not in pnr and "MARA" not in pnr
    assert "THORNENLOW" in pnr and "YANNICK" in pnr
    meta = json.loads((d / "meta.json").read_text(encoding="utf-8"))
    assert meta["first"] == "YANNICK" and meta["surname"] == "THORNENLOW"


def test_no_rewrite_when_none(tmp_path):
    src = make_src_fixture(tmp_path / "src", locator="FDAP36",
                           first="MARA", surname="OKONKWO")
    d = clone_fixture(src, tmp_path / "out", "ZQ0002", contact_email="x@m.com")
    assert "OKONKWO" in (d / "01_pnr.json").read_text(encoding="utf-8")
```

(If `tests/test_clone.py` has no reusable `make_src_fixture` helper, extract its inline fixture-building code into one at the top of that file and import it — do not duplicate it.)

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/test_clone_passenger.py -q`
Expected: FAIL — `clone_fixture() got an unexpected keyword argument 'new_passenger'`.

- [ ] **Step 3: Implement**

In `seed/clone.py`:

```python
def _split_passenger(full: str) -> tuple[str, str]:
    """'YANNICK THORNENLOW' -> ('YANNICK', 'THORNENLOW'); multi-token firsts keep last token as surname."""
    toks = (full or "").strip().upper().split()
    return (" ".join(toks[:-1]), toks[-1]) if len(toks) >= 2 else ("", full.strip().upper())
```

Add `new_passenger: str | None = None` to `clone_fixture`'s signature. Inside, after reading `meta`:

```python
    src_first = str(meta.get("first") or "").upper()
    src_sur = str(meta.get("surname") or "").upper()
    new_first = new_sur = None
    if new_passenger:
        new_first, new_sur = _split_passenger(new_passenger)
```

Extend `_retext`:

```python
    def _retext(text: str) -> str:
        text = text.replace(src_loc, new_locator)
        if src_docnum:
            text = text.replace(src_docnum, new_docnum)
        if new_date and src_date:
            text = text.replace(src_date, new_date)
        if new_sur and len(src_sur) >= 3:
            text = text.replace(src_sur, new_sur)
        if new_first and len(src_first) >= 3:
            text = text.replace(src_first, new_first)
        return text
```

(The `len >= 3` guard prevents short-name collisions with unrelated substrings.)
And in the meta block before writing:

```python
    if new_sur:
        new_meta["first"], new_meta["surname"] = new_first, new_sur
```

In `clone_batch`, add `passengers: dict[str, str] | None = None` and pass
`new_passenger=(passengers or {}).get(new_loc)` through.

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_clone_passenger.py tests/test_clone.py -q` → PASS.

- [ ] **Step 5: Commit**

```bash
git add seed/clone.py tests/test_clone_passenger.py tests/test_clone.py
git commit -m "feat(seed): clone_fixture rewrites passenger name (dataset-driven identities)"
```

---

### Task 3: Seed ledger

**Files:**
- Create: `seed/ledger.py`, `data/seed-ledger/fd.yaml` (created on first write)
- Test: `tests/test_ledger.py` (new)

**Interfaces:**
- Produces:
  - `Ledger.load(path: str | Path) -> Ledger` (missing file → empty ledger)
  - `Ledger.record(case_id: str, *, env: str, pnr: str, pnr_id: str, source: str, passenger: str, seeded_at: str, gate: str) -> None` — upserts on `(case_id, env)`; previous value appended to that entry's `history` list.
  - `Ledger.get(case_id: str, env: str) -> dict | None`
  - `Ledger.entries(env: str | None = None) -> list[dict]`
  - `Ledger.save(path=None) -> Path` (YAML, sorted by case_id, stable for git diffs)
  - `Ledger.problems(known_ids: set[str]) -> list[str]` — duplicate `(case_id, env)` pairs and case ids not in `known_ids` (warnings, never raises).
- YAML shape: `{schema_version: 1, entries: [{case_id, env, pnr, pnr_id, source, passenger, seeded_at, gate, history: [...]}]}`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_ledger.py
from seed.ledger import Ledger


def _rec(led, case, pnr, env="int"):
    led.record(case, env=env, pnr=pnr, pnr_id=f"{pnr}-2026-07-09", source="FDAP36",
               passenger="YANNICK THORNENLOW", seeded_at="2026-07-16T20:00:00Z", gate="all-pass")


def test_roundtrip(tmp_path):
    p = tmp_path / "fd.yaml"
    led = Ledger.load(p)
    _rec(led, "FD_TC_001", "ZQ0001")
    led.save(p)
    led2 = Ledger.load(p)
    assert led2.get("FD_TC_001", "int")["pnr"] == "ZQ0001"
    assert led2.entries("int")[0]["case_id"] == "FD_TC_001"


def test_reseed_keeps_history(tmp_path):
    led = Ledger.load(tmp_path / "fd.yaml")
    _rec(led, "FD_TC_001", "ZQ0001")
    _rec(led, "FD_TC_001", "ZQ0099")
    e = led.get("FD_TC_001", "int")
    assert e["pnr"] == "ZQ0099" and e["history"][0]["pnr"] == "ZQ0001"


def test_problems(tmp_path):
    led = Ledger.load(tmp_path / "fd.yaml")
    _rec(led, "FD_TC_001", "ZQ0001")
    _rec(led, "NOT_A_CASE", "ZQ0002")
    probs = led.problems({"FD_TC_001"})
    assert any("NOT_A_CASE" in p for p in probs)


def test_missing_file_is_empty(tmp_path):
    assert Ledger.load(tmp_path / "nope.yaml").entries() == []
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/test_ledger.py -q` → FAIL (`No module named 'seed.ledger'`).

- [ ] **Step 3: Implement**

```python
# seed/ledger.py
"""Committed seed ledger: the durable case_id -> seeded-PNR mapping per env (spec Component 3).
YAML on disk, upsert-with-history in memory, fail-soft validation (humans edit this file)."""
from __future__ import annotations

from pathlib import Path

import yaml


class Ledger:
    def __init__(self, path: Path | None = None, entries: list[dict] | None = None):
        self.path = Path(path) if path else None
        self._entries: list[dict] = entries or []

    @classmethod
    def load(cls, path) -> "Ledger":
        p = Path(path)
        if not p.exists():
            return cls(p, [])
        doc = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        return cls(p, list(doc.get("entries") or []))

    def record(self, case_id: str, *, env: str, pnr: str, pnr_id: str, source: str,
               passenger: str, seeded_at: str, gate: str) -> None:
        new = {"case_id": case_id, "env": env, "pnr": pnr, "pnr_id": pnr_id,
               "source": source, "passenger": passenger, "seeded_at": seeded_at,
               "gate": gate, "history": []}
        old = self.get(case_id, env)
        if old is not None:
            new["history"] = list(old.get("history") or [])
            new["history"].insert(0, {k: old[k] for k in
                                      ("pnr", "pnr_id", "source", "seeded_at", "gate")})
            self._entries.remove(old)
        self._entries.append(new)

    def get(self, case_id: str, env: str) -> dict | None:
        for e in self._entries:
            if e.get("case_id") == case_id and e.get("env") == env:
                return e
        return None

    def entries(self, env: str | None = None) -> list[dict]:
        out = [e for e in self._entries if env is None or e.get("env") == env]
        return sorted(out, key=lambda e: (str(e.get("case_id")), str(e.get("env"))))

    def problems(self, known_ids: set[str]) -> list[str]:
        probs, seen = [], set()
        for e in self._entries:
            key = (e.get("case_id"), e.get("env"))
            if key in seen:
                probs.append(f"duplicate entry {key}")
            seen.add(key)
            if e.get("case_id") not in known_ids:
                probs.append(f"unknown case_id {e.get('case_id')!r} (ORPHAN)")
        return probs

    def save(self, path=None) -> Path:
        p = Path(path) if path else self.path
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(yaml.safe_dump({"schema_version": 1, "entries": self.entries()},
                                    sort_keys=False, allow_unicode=True), encoding="utf-8")
        return p
```

- [ ] **Step 4: Run tests** — `python -m pytest tests/test_ledger.py -q` → 4 PASS.

- [ ] **Step 5: Commit**

```bash
git add seed/ledger.py tests/test_ledger.py
git commit -m "feat(seed): committed seed ledger (case_id -> PNR per env, upsert w/ history)"
```

---

### Task 4: Source-fixture matcher

**Files:**
- Create: `seed/match.py`
- Test: `tests/test_match.py` (new)

**Interfaces:**
- Consumes: `catalog.model.UseCase` (dataset-bound, from Task 1); the fixture catalog via `catalog.fixtures.load_fixture_catalog(fixtures_dir, feed_id)`.
- Produces: `match_source(uc: UseCase, sources: list[UseCase]) -> tuple[str | None, str]` returning `(source_locator, reason)`. Selection order: ① same systemCode family prefix (`FD-APPR-EL` etc., matched against the source's `system_code` or its verdict+regime equivalent) → ② same `(regime, verdict)` → ③ `(None, "no_source")`. Never crosses regime. Structural flags: a case whose `seed.flags`/title marks GROUP / INFANT / MULTI-PAX only matches a source with the same marker (substring check on the source id/title/flags).
- Family derivation helper: `family_of(uc) -> str` = `uc.seed.system_code.rsplit("-", 1)[0]` when set, else `f"FD-{uc.regime or 'APPR'}-{_V2CODE.get(uc.verdict, 'EL')}"` with `_V2CODE = {"ELIGIBLE": "EL", "NOT_ELIGIBLE": "NE", "NO_DETERMINATION": "ND", "PENDING": "PE"}`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_match.py
from catalog.model import SeedSpec, UseCase
from seed.match import family_of, match_source


def _uc(id, regime="APPR", verdict="ELIGIBLE", syscode="", title="", flags=""):
    return UseCase(id=id, regime=regime, verdict=verdict, system_code=syscode, title=title,
                   third_party=False, checkpoint_vector=[], customer_intent="",
                   expected_transcript=[], seed=SeedSpec(system_code=syscode, flags=flags),
                   seed_pending=False)


SOURCES = [_uc("FDAP36", "APPR", "ELIGIBLE", "FD-APPR-EL-400"),
           _uc("FDEU34", "EU", "ELIGIBLE", "FD-EU-EL-250"),
           _uc("FDBLOW", "APPR", "NOT_ELIGIBLE", "FD-APPR-NE-BT"),
           _uc("FDGRP1", "APPR", "ELIGIBLE", "FD-APPR-EL-400", title="GROUP booking")]


def test_exact_family_match():
    loc, why = match_source(_uc("FD_TC_001", syscode="FD-APPR-EL-400"), SOURCES)
    assert loc == "FDAP36" and why == "family"


def test_regime_verdict_fallback():
    loc, why = match_source(_uc("FD_TC_050", "APPR", "NOT_ELIGIBLE", "FD-APPR-NE-DUP"), SOURCES)
    assert loc == "FDBLOW" and why == "regime_verdict"


def test_never_cross_regime():
    loc, why = match_source(_uc("FD_TC_090", "ASL", "ELIGIBLE", "FD-ASL-EL-1"), SOURCES)
    assert loc is None and why == "no_source"


def test_group_needs_group_source():
    loc, _ = match_source(_uc("FD_TC_120", syscode="FD-APPR-EL-400", flags="GROUP"), SOURCES)
    assert loc == "FDGRP1"


def test_family_of_fallback():
    assert family_of(_uc("X", "EU", "NOT_ELIGIBLE")) == "FD-EU-NE"
```

- [ ] **Step 2: Run to verify it fails** — `python -m pytest tests/test_match.py -q` → FAIL (no module).

- [ ] **Step 3: Implement**

```python
# seed/match.py
"""Pick the clone SOURCE fixture for a gap-doc case: exact systemCode family first, then same
(regime, verdict), never across regimes; structural flags (GROUP/INFANT/MULTI) must agree.
Returns (None, 'no_source') rather than mis-seeding (spec Component 6.3)."""
from __future__ import annotations

_V2CODE = {"ELIGIBLE": "EL", "NOT_ELIGIBLE": "NE", "NO_DETERMINATION": "ND", "PENDING": "PE"}
_STRUCT = ("GROUP", "INFANT", "MULTI")


def family_of(uc) -> str:
    sc = (uc.seed.system_code or uc.system_code or "").strip()
    if sc:
        return sc.rsplit("-", 1)[0]
    return f"FD-{(uc.regime or 'APPR').upper()}-{_V2CODE.get((uc.verdict or '').upper(), 'EL')}"


def _markers(uc) -> set:
    blob = f"{uc.id} {uc.title} {uc.seed.flags}".upper()
    return {m for m in _STRUCT if m in blob}


def match_source(uc, sources) -> tuple[str | None, str]:
    fam, marks = family_of(uc), _markers(uc)
    compatible = [s for s in sources if _markers(s) == marks or (_markers(s) and not marks)]
    pool = [s for s in (compatible or sources) if _markers(s) == marks] or \
           [s for s in compatible if not _markers(s) ^ marks]
    pool = pool or [s for s in sources if _markers(s) == marks]
    for s in pool:
        if family_of(s) == fam:
            return s.id, "family"
    for s in pool:
        if (s.regime or "").upper() == (uc.regime or "").upper() and \
           (s.verdict or "").upper() == (uc.verdict or "").upper():
            return s.id, "regime_verdict"
    return None, "no_source"
```

(If the pool logic above proves awkward during implementation, simplify to: `pool = [s for s in sources if _markers(s) == marks]` — a case with no structural markers only matches unmarked sources, a GROUP case only GROUP sources. The tests define the contract.)

- [ ] **Step 4: Run tests** — `python -m pytest tests/test_match.py -q` → 5 PASS.

- [ ] **Step 5: Commit**

```bash
git add seed/match.py tests/test_match.py
git commit -m "feat(seed): case -> source-fixture matcher (family, regime+verdict, structural flags)"
```

---

### Task 5: DDS template harvester

**Files:**
- Create: `seed/harvest.py`
- Modify: `core/registry/envs/int.yaml` (add harvested families under `seed_targets.dds.templates`)
- Test: `tests/test_harvest.py` (new)

**Interfaces:**
- Consumes: `seed.dds_pin.verify_by_pnr(env, pnr_id) -> {status_code, eligible, amount, system_code, raw}`; fixture catalog for candidate PNRs.
- Produces: `harvest_templates(env, candidates: list[dict], out_dir: str, fetch=None) -> dict[str, str]` — `candidates` are `{"pnr_id": ..., "family": ...}`; for each family not yet in `out_dir`, GET the by-pnr determination (via injectable `fetch(pnr_id)` defaulting to `verify_by_pnr(env, pnr_id)["raw"]`), save it as `<out_dir>/<family_lower>.json`, and return `{family: path}`. Skips families whose file already exists (idempotent). A 404/error records nothing (family stays unharvested).
- CLI: `cctqa dds-harvest <product> <env> <feed>` added in Task 7's CLI wiring.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_harvest.py
import json

from seed.harvest import harvest_templates


def test_harvest_writes_one_file_per_family(tmp_path):
    dets = {"FDBLOW-2026-07-01": {"decision": {"systemCode": "FD-APPR-NE-BT"}},
            "FDNODX-2026-07-01": {"decision": {"systemCode": "FD-APPR-ND-1"}}}
    cands = [{"pnr_id": "FDBLOW-2026-07-01", "family": "FD-APPR-NE"},
             {"pnr_id": "FDNODX-2026-07-01", "family": "FD-APPR-ND"},
             {"pnr_id": "MISSING-2026-07-01", "family": "FD-EU-NE"}]
    got = harvest_templates(None, cands, tmp_path,
                            fetch=lambda pid: dets.get(pid) or (_ for _ in ()).throw(KeyError(pid)))
    assert set(got) == {"FD-APPR-NE", "FD-APPR-ND"}  # missing one skipped, not raised
    saved = json.loads((tmp_path / "fd-appr-ne.json").read_text(encoding="utf-8"))
    assert saved["decision"]["systemCode"] == "FD-APPR-NE-BT"


def test_harvest_idempotent(tmp_path):
    (tmp_path / "fd-appr-ne.json").write_text("{}", encoding="utf-8")
    got = harvest_templates(None, [{"pnr_id": "X", "family": "FD-APPR-NE"}], tmp_path,
                            fetch=lambda pid: (_ for _ in ()).throw(AssertionError("must not fetch")))
    assert got == {}
```

- [ ] **Step 2: Run to verify it fails** — `python -m pytest tests/test_harvest.py -q` → FAIL (no module).

- [ ] **Step 3: Implement**

```python
# seed/harvest.py
"""Harvest real DDS determinations from an env's by-pnr endpoint as pin templates, one JSON per
systemCode family (spec Component 6.4). Idempotent; fetch errors skip the family, never raise."""
from __future__ import annotations

import json
from pathlib import Path


def harvest_templates(env, candidates, out_dir, fetch=None) -> dict:
    if fetch is None:
        from seed.dds_pin import verify_by_pnr
        fetch = lambda pnr_id: verify_by_pnr(env, pnr_id)["raw"]
    out, saved = Path(out_dir), {}
    out.mkdir(parents=True, exist_ok=True)
    for c in candidates:
        fam = c["family"]
        dst = out / f"{fam.lower()}.json"
        if dst.exists() or fam in saved:
            continue
        try:
            det = fetch(c["pnr_id"])
        except Exception:
            continue
        if not det:
            continue
        dst.write_text(json.dumps(det, ensure_ascii=False, indent=1), encoding="utf-8")
        saved[fam] = str(dst)
    return saved
```

- [ ] **Step 4: Run tests** — `python -m pytest tests/test_harvest.py -q` → 2 PASS.

- [ ] **Step 5 (LIVE, manual — requires int-sso session):** run the harvest against INT using the preseed fixtures whose verdicts cover NE/ND (e.g. `FDBLOW`, `FDNODX`, `FDNTEU`, `FDASL1`, `FDEU34`, `FDUK34`), then register every harvested file in `core/registry/envs/int.yaml` under `seed_targets.dds.templates` as `<FAMILY>: data/dds-templates/<family>.json`. Families with no harvestable sample stay unregistered — the campaign will mark their cases `UNSEEDABLE(no_template)`.

- [ ] **Step 6: Commit**

```bash
git add seed/harvest.py tests/test_harvest.py core/registry/envs/int.yaml data/dds-templates/
git commit -m "feat(seed): DDS template harvester + registered harvested families for INT"
```

---

### Task 6: Campaign orchestrator

**Files:**
- Create: `seed/campaign.py`
- Test: `tests/test_campaign.py` (new)

**Interfaces:**
- Consumes: Tasks 1-5 (`join_dataset`-bound catalog via `catalog.parser.load_catalog(feed)`; `match_source`; `clone_batch(..., passengers=...)`; `Ledger`; registered DDS templates; existing `kafka_seed.seed`, `dds_pin.pin_case`, `dds_pin.verify_by_pnr`, `seed.cli._trip_landed`, `seed.cli._audit_checkpoints`, `seed.cli.in_window_date`, `_family_for`-style family → template resolution via env descriptor).
- Produces:
  - `plan_campaign(catalog, sources, ledger, env_id: str, templates: set[str]) -> dict` with keys `todo: list[{case, source, family}]`, `skipped_healthy: list[str]`, `unseedable: list[{case_id, reason}]` (`no_source` / `no_template` / `seed_pending`).
  - `run_campaign(product, env, feed, *, batch_size=25, limit=None, dry_run=False) -> dict` (the LIVE driver; returns the final tally; writes ledger after each verified case; prints running `HEALTHY x/239`).
  - Locator minting: `mint_locator(case_id: str) -> str` — `ZFU` + case number per Task 2
    (`FD_TC_001 → ZFU001`, `FD_TC_3P_01 → ZFU3P01`); deterministic from the case id so re-runs
    mint the same locator (idempotent with the ledger). The campaign consumes Task 2's
    `ScenarioSpec` (realistic passenger/route/dates) and Task 2b's `synthesize_fixture` instead of
    plain cloning; `plan_campaign`'s bucket logic is unchanged.
- CLI: `cctqa seed-campaign <product> <env> <feed> [--batch-size 25] [--limit N] [--dry-run]` (wired in Task 7).

- [ ] **Step 1: Write the failing test (offline planner only)**

```python
# tests/test_campaign.py
from catalog.model import Catalog, SeedSpec, UseCase
from seed.campaign import mint_locator, plan_campaign
from seed.ledger import Ledger


def _uc(id, verdict="ELIGIBLE", syscode="FD-APPR-EL-400", pending=False):
    return UseCase(id=id, regime="APPR", verdict=verdict, system_code=syscode, title="",
                   third_party=False, checkpoint_vector=[], customer_intent="",
                   expected_transcript=[], seed=SeedSpec(pnr="X", passenger="A B",
                   system_code=syscode), seed_pending=pending)


def _cat(cases):
    return Catalog(feed_id="fd", checkpoints=[], cases=cases, uncovered=[])


SOURCES = [_uc("FDAP36"), _uc("FDBLOW", "NOT_ELIGIBLE", "FD-APPR-NE-BT")]


def test_plan_buckets(tmp_path):
    led = Ledger.load(tmp_path / "fd.yaml")
    led.record("FD_TC_001", env="int", pnr="ZQ0001", pnr_id="x", source="FDAP36",
               passenger="A B", seeded_at="t", gate="all-pass")
    cat = _cat([_uc("FD_TC_001"),                                  # already healthy -> skip
                _uc("FD_TC_002"),                                  # todo (family FD-APPR-EL ok)
                _uc("FD_TC_003", "NOT_ELIGIBLE", "FD-APPR-NE-X"),  # todo (NE template exists)
                _uc("FD_TC_004", "PENDING", "FD-APPR-PE-1"),       # no template -> unseedable
                _uc("FD_TC_005", pending=True)])                   # seed_pending -> unseedable
    plan = plan_campaign(cat, SOURCES, led, "int",
                         templates={"FD-APPR-EL", "FD-APPR-NE"})
    assert [t["case"].id for t in plan["todo"]] == ["FD_TC_002", "FD_TC_003"]
    assert plan["skipped_healthy"] == ["FD_TC_001"]
    assert {u["case_id"]: u["reason"] for u in plan["unseedable"]} == {
        "FD_TC_004": "no_template", "FD_TC_005": "seed_pending"}


def test_mint_locator():
    assert mint_locator("FD_TC_001") == "ZFU001"
    assert mint_locator("FD_TC_239") == "ZFU239"
    assert mint_locator("FD_TC_3P_01") == "ZFU3P01"
```

- [ ] **Step 2: Run to verify it fails** — `python -m pytest tests/test_campaign.py -q` → FAIL (no module).

- [ ] **Step 3: Implement planner + driver**

```python
# seed/campaign.py
"""Full-corpus seed campaign (spec Component 6): plan (offline) + run (LIVE, batched, resumable).
plan_campaign decides todo/skip/unseedable per case; run_campaign drives clone -> Kafka -> settle ->
DDS pin -> checkpoint gate -> ledger, in batches, printing the running coverage tally."""
from __future__ import annotations

import datetime
import json
from pathlib import Path

from seed.match import family_of, match_source


def mint_locator(case_id: str) -> str:
    """FD_TC_001 -> ZFU001; FD_TC_3P_01 -> ZFU3P01 (reference: generate_fd_uat_scenarios.py)."""
    if case_id.startswith("FD_TC_3P_"):
        return f"ZFU3P{case_id.removeprefix('FD_TC_3P_')}"
    return f"ZFU{case_id.removeprefix('FD_TC_')}"


def plan_campaign(catalog, sources, ledger, env_id: str, templates: set) -> dict:
    todo, skipped, unseedable = [], [], []
    for uc in catalog.cases:
        if uc.seed_pending or not uc.seed.pnr:
            unseedable.append({"case_id": uc.id, "reason": "seed_pending"})
            continue
        if ledger.get(uc.id, env_id) and ledger.get(uc.id, env_id).get("gate") == "all-pass":
            skipped.append(uc.id)
            continue
        fam = family_of(uc)
        if fam not in templates:
            unseedable.append({"case_id": uc.id, "reason": "no_template"})
            continue
        src, why = match_source(uc, sources)
        if src is None:
            unseedable.append({"case_id": uc.id, "reason": "no_source"})
            continue
        todo.append({"case": uc, "source": src, "family": fam})
    return {"todo": todo, "skipped_healthy": skipped, "unseedable": unseedable}
```

The LIVE driver `run_campaign` (same file) reuses the proven single-batch flow of
`seed.cli.run_seed`, parameterized per case (source, new locator, passenger, family). Implement it
by refactoring — move the body of `run_seed`'s per-batch work into a helper
`_seed_batch(ctx, batch, clone_dir, *, passengers, families, verify=True) -> list[dict]` in
`seed/cli.py` that `run_seed` (unchanged behavior) and `run_campaign` both call; `run_campaign`
then loops batches, records ledger entries for every case whose checkpoint vector is all-pass
(`gate="all-pass"`), writes `campaign-report.json` (todo/succeeded/failed/unseedable) under the
clone dir, and prints `HEALTHY {n}/{total}` after each batch. Family resolution per case: the
campaign passes the case's exact family template key; `dds_pin.pin_case(family=...)` resolves it
via `env.seed_targets["dds"]["templates"]`. `--dry-run` prints the plan and exits without cloning.

- [ ] **Step 4: Run tests** — `python -m pytest tests/test_campaign.py tests/test_runner_orchestrator.py -q` → PASS (the `run_seed` refactor must not change its behavior — the existing seed CLI tests cover it).

- [ ] **Step 5: Commit**

```bash
git add seed/campaign.py seed/cli.py tests/test_campaign.py
git commit -m "feat(seed): seed-campaign planner + batched resumable driver over run_seed core"
```

---

### Task 7: CLI wiring (`seed-campaign`, `dds-harvest`, `ledger`)

**Files:**
- Modify: `seed/cli.py` (argparse: keep `cctqa seed` as-is; the umbrella CLI gains subcommands) and the umbrella dispatcher that routes `cctqa <cmd>` (see `pyproject.toml [project.scripts]` → follow the existing routing pattern used for `catalog`/`dashboard`/`quality`)
- Test: `tests/test_campaign_cli.py` (new)

**Interfaces:**
- Produces: `cctqa seed-campaign <product> <env> <feed> [--batch-size N] [--limit N] [--dry-run]`; `cctqa dds-harvest <product> <env> <feed>`; `cctqa ledger <feed> [--env int]` (prints coverage summary from ledger × catalog, offline).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_campaign_cli.py
from seed.campaign_cli import main


def test_dry_run_prints_plan(capsys, tmp_path, monkeypatch):
    rc = main(["brove", "int", "fd", "--dry-run"])
    out = capsys.readouterr().out
    assert rc == 0 and "todo" in out and "unseedable" in out
```

- [ ] **Step 2: Run to verify it fails** — FAIL (no module `seed.campaign_cli`).

- [ ] **Step 3: Implement** `seed/campaign_cli.py`: argparse mirroring `seed/cli.py`'s style; `--dry-run` path loads catalog (`load_catalog(load_feed(feed))`), fixture sources, ledger (`data/seed-ledger/<feed>.yaml`), template registry keys from the env descriptor, prints `json.dumps` of the plan summary (counts + unseedable reasons), exits 0. Non-dry path calls `run_campaign`. Register the routes in the umbrella dispatcher exactly like `catalog`/`quality` are registered.

- [ ] **Step 4: Run tests** — `python -m pytest tests/test_campaign_cli.py -q` → PASS.

- [ ] **Step 5: Commit**

```bash
git add seed/campaign_cli.py seed/cli.py pyproject.toml tests/test_campaign_cli.py
git commit -m "feat(seed): cctqa seed-campaign / dds-harvest / ledger CLI"
```

---

### Task 8: Corpus audit (`cctqa audit`)

**Files:**
- Create: `seed/audit.py`
- Test: `tests/test_audit.py` (new)

**Interfaces:**
- Consumes: catalog, `Ledger`, `seed.verify.verify_case` (injectable as `verifier(uc, entry) -> VerifyReport | None` for offline mode).
- Produces: `audit(catalog, ledger, env_id, verifier=None) -> dict` — every case in exactly one bucket: `HEALTHY` (ledgered, live re-verify all_ok), `BROKEN` (ledgered, verify has failures), `MISSING` (no ledger entry), `SEED_PENDING`, `ORPHAN` (ledger ids unknown to catalog), `UNCHECKED` (ledgered, verifier=None or raised). Report dict: `{schema_version: 1, env, feed, counts: {...}, buckets: {name: [case ids]}}`. Writer: `write_audit(report, out_dir) -> Path` (JSON; HTML deferred to the dashboard's pipeline-strip increment).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_audit.py
from catalog.model import Catalog, SeedSpec, UseCase
from seed.audit import audit
from seed.ledger import Ledger
from seed.model import CheckpointResult, VerifyReport


def _uc(id, pending=False):
    return UseCase(id=id, regime="APPR", verdict="ELIGIBLE", system_code="", title="",
                   third_party=False, checkpoint_vector=[], customer_intent="",
                   expected_transcript=[], seed=SeedSpec(pnr="Z"), seed_pending=pending)


def _led(tmp_path, *case_ids):
    led = Ledger.load(tmp_path / "fd.yaml")
    for cid in case_ids:
        led.record(cid, env="int", pnr="ZQ0001", pnr_id="x", source="s", passenger="p",
                   seeded_at="t", gate="all-pass")
    return led


def test_all_six_buckets(tmp_path):
    cat = Catalog("fd", [], [_uc("A"), _uc("B"), _uc("C"), _uc("D", pending=True)], [])
    led = _led(tmp_path, "A", "B", "GHOST")
    ok = VerifyReport("A", "Z", [CheckpointResult("trip_active", True)])
    bad = VerifyReport("B", "Z", [CheckpointResult("trip_active", False, "no trip")])
    rep = audit(cat, led, "int",
                verifier=lambda uc, e: {"A": ok, "B": bad}.get(uc.id))
    b = rep["buckets"]
    assert b["HEALTHY"] == ["A"] and b["BROKEN"] == ["B"] and b["MISSING"] == ["C"]
    assert b["SEED_PENDING"] == ["D"] and b["ORPHAN"] == ["GHOST"]


def test_offline_is_unchecked(tmp_path):
    cat = Catalog("fd", [], [_uc("A")], [])
    rep = audit(cat, _led(tmp_path, "A"), "int", verifier=None)
    assert rep["buckets"]["UNCHECKED"] == ["A"]
```

- [ ] **Step 2: Run to verify it fails** — FAIL (no module).

- [ ] **Step 3: Implement**

```python
# seed/audit.py
"""Corpus audit (spec Component 4): catalog x ledger x live re-verify -> six exclusive buckets.
Offline (verifier=None) marks ledgered cases UNCHECKED instead of guessing. JSON report only;
the dashboard renders it later via the pipeline strip."""
from __future__ import annotations

import json
from pathlib import Path


def audit(catalog, ledger, env_id: str, verifier=None) -> dict:
    buckets = {k: [] for k in ("HEALTHY", "BROKEN", "MISSING", "SEED_PENDING", "ORPHAN", "UNCHECKED")}
    known = {uc.id for uc in catalog.cases}
    for uc in catalog.cases:
        entry = ledger.get(uc.id, env_id)
        if uc.seed_pending:
            buckets["SEED_PENDING"].append(uc.id)
        elif entry is None:
            buckets["MISSING"].append(uc.id)
        elif verifier is None:
            buckets["UNCHECKED"].append(uc.id)
        else:
            try:
                rep = verifier(uc, entry)
            except Exception:
                rep = None
            if rep is None:
                buckets["UNCHECKED"].append(uc.id)
            elif rep.all_ok:
                buckets["HEALTHY"].append(uc.id)
            else:
                buckets["BROKEN"].append(uc.id)
    for e in ledger.entries(env_id):
        if e["case_id"] not in known:
            buckets["ORPHAN"].append(e["case_id"])
    return {"schema_version": 1, "env": env_id, "feed": catalog.feed_id,
            "counts": {k: len(v) for k, v in buckets.items()}, "buckets": buckets}


def write_audit(report: dict, out_dir) -> Path:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    p = out / "audit-report.json"
    p.write_text(json.dumps(report, indent=1), encoding="utf-8")
    return p
```

Wire `cctqa audit <product> <env> <feed> [--offline]` into the CLI beside `seed-campaign` (offline → `verifier=None`; live → a closure over `seed.source.connect(env)` + `verify_case` + `dds_pin.verify_by_pnr`, and the ledger entry's `pnr`/`pnr_id` substituted into the case's SeedSpec via `dataclasses.replace` before verifying, since the live PNR is the minted one, not the dataset's CRT-era locator).

- [ ] **Step 4: Run tests** — `python -m pytest tests/test_audit.py -q` → 2 PASS; full suite green.

- [ ] **Step 5: Commit**

```bash
git add seed/audit.py tests/test_audit.py seed/campaign_cli.py
git commit -m "feat(seed): corpus audit — six-bucket coverage report over catalog x ledger x live verify"
```

---

### Task 9: LIVE campaign execution (manual, staged — requires int-sso)

**Files:** none (operational task; produces `data/seed-ledger/fd.yaml` growth + `campaign-report.json` + audit reports)

- [ ] **Step 1:** `aws sts get-caller-identity --profile int-sso` → session valid.
- [ ] **Step 2:** `cctqa dds-harvest brove int fd` → then register harvested families in `int.yaml` (Task 5 Step 5 if not yet done); commit.
- [ ] **Step 3:** `cctqa seed-campaign brove int fd --dry-run` → review todo/unseedable counts; sanity-check a few case→source pairings by hand.
- [ ] **Step 4 (pilot):** `cctqa seed-campaign brove int fd --limit 10` → expect 10/10 gate-pass; inspect `campaign-report.json`; commit the ledger.
- [ ] **Step 5 (full):** `cctqa seed-campaign brove int fd --batch-size 25` → resumable; re-run on any interruption (ledgered HEALTHY cases skip). Commit the ledger after each session.
- [ ] **Step 6:** `cctqa audit brove int fd` → final coverage report; expected shape: `HEALTHY ≈ todo count`, `SEED_PENDING` + `UNSEEDABLE`-derived `MISSING` for the remainder, `BROKEN = 0`. Commit the audit JSON under `results/<date>/`.

---

## Self-Review

- **Spec coverage:** Component 1 (StageReport) intentionally deferred — the campaign records gate results via the existing `VerifyReport`/checkpoint vectors and the ledger `gate` field; the uniform StageReport shape lands with the chat-gate phase. Components 2 (gate checks exist inline in `run_seed`/`_seed_batch` — formal `seed/gate.py` extraction also deferred to the monitors phase), 3 (Task 3), 4 (Task 8), 6 (Tasks 1,2,4,5,6,7,9) covered. Backfill of the 48 legacy fixtures is intentionally dropped: the campaign mints fresh ledgered PNRs for every case, which supersedes backfilling.
- **Placeholder scan:** none — every code step is complete; Task 6's `run_campaign` refactor names the exact helper and call sites.
- **Type consistency:** `Ledger.record/get/entries/problems`, `match_source -> (str|None, str)`, `family_of -> str`, `plan_campaign` bucket keys, and `VerifyReport.all_ok` usages are consistent across Tasks 3-8.
