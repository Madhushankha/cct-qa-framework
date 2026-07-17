"""Fixtures -> Catalog adapter: build a Catalog of UseCases directly from a directory of preseed
fixture folders (each with a `meta.json`), for envs whose dataset IS the seeded fixture set rather
than a gap-doc HTML table (e.g. the INT FD preseed corpus).

Each `<locator>/meta.json` yields one UseCase: the locator is the case id and PNR, the passenger
name comes from first+surname, and the expected verdict/amount are parsed from the free-text
`expected` note (best-effort — the raw note is preserved in seed.extras for the judge). This keeps
the runner and judge fed with the same UseCase shape the gap-doc parser produces.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from catalog.model import Catalog, SeedSpec, UseCase

_CUR_RE = re.compile(r"\b(CAD|USD|EUR|GBP|ILS)\b")
_NUM_RE = re.compile(r"(\d[\d,]*(?:\.\d+)?)")
# duration / range tokens that are NOT money: '3-4h', '4h+', '480m+', '240m', '72h'
_DURATION_RE = re.compile(r"\d[\d,]*\s*-\s*\d[\d,]*\s*h|\d[\d,]*\s*[hm]\b\+?", re.IGNORECASE)

# Keyword -> verdict, checked in order against the lowercased expected note. Amount-bearing notes
# short-circuit to ELIGIBLE before this runs.
_VERDICT_HINTS = (
    ("not eligible", "NOT_ELIGIBLE"),
    ("ne (", "NOT_ELIGIBLE"),
    (" ne ", "NOT_ELIGIBLE"),
    ("below threshold", "NOT_ELIGIBLE"),
    ("no determination", "NO_DETERMINATION"),
    ("pending", "PENDING"),
    ("escalat", "ESCALATED"),
    ("agent", "ESCALATED"),
)


def parse_amount(expected: str):
    """Parse a currency+value out of a free-text expected note, or None. Requires BOTH a known
    currency code and a number so notes like 'GBP (UK 3-4h)' (no real amount) return None."""
    cur = _CUR_RE.search(expected or "")
    if not cur:
        return None
    # search for the number AFTER the currency code, with duration/range tokens ('3-4h', '480m+')
    # blanked out first so they aren't mistaken for money
    tail = _DURATION_RE.sub(" ", expected[cur.end():])
    num = _NUM_RE.search(tail)
    if not num:
        return None
    try:
        value = float(num.group(1).replace(",", ""))
    except ValueError:
        return None
    return {"currency": cur.group(1), "value": value}


def derive_verdict(expected: str, amount) -> str:
    """Best-effort expected decision. A parsed amount implies ELIGIBLE; otherwise scan keyword
    hints; default UNKNOWN (the judge still records what the bot actually did)."""
    if amount:
        return "ELIGIBLE"
    low = (expected or "").lower()
    for needle, verdict in _VERDICT_HINTS:
        if needle in low:
            return verdict
    return "UNKNOWN"


def usecase_from_meta(meta: dict) -> UseCase:
    """Build one UseCase from a fixture meta.json.

    The UseCase id is the gap-doc TEST CASE id (`case_id`, e.g. FD_TC_018) when the fixture carries
    one — that id is the single key that links every pipeline artifact (preseed row -> result.json
    -> evidence.html -> quality.html) back to the gap-doc scenario. The PNR/locator (e.g. AFSRET) is
    the booking and stays on `seed.pnr`. Legacy fixtures without `case_id` fall back to the locator."""
    loc = meta.get("locator") or meta.get("pnr_id", "").split("-", 1)[0]
    case_id = meta.get("case_id") or loc
    passenger = " ".join(x for x in (meta.get("first"), meta.get("surname")) if x).strip()
    expected = str(meta.get("expected") or "")
    # Prefer the REAL per-case amount render_case carried from the catalog (meta.amount/currency); only
    # fall back to parsing the free-text note when it's absent (legacy fixtures). The note is the base
    # template's flat "CAD 400 cash", which mislabels every 700/1000/EU-600 tier as 400.
    if meta.get("amount") is not None:
        try:
            amount = {"currency": meta.get("currency") or "", "value": float(meta["amount"])}
        except (TypeError, ValueError):
            amount = parse_amount(expected)
    else:
        amount = parse_amount(expected)
    # Prefer the verdict encoded in the gap-doc systemCode class (FD-<regime>-<CLASS>-n): EL/NE/ND/PE
    # -> ELIGIBLE/NOT_ELIGIBLE/NO_DETERMINATION/PENDING. The free-text `expected` note defaults to
    # ELIGIBLE, which mislabels every negative case; the systemCode is the reliable per-case truth.
    sc_parts = str(meta.get("system_code") or "").upper().split("-")
    sc_cls = sc_parts[2] if len(sc_parts) > 2 else ""
    verdict = {"EL": "ELIGIBLE", "NE": "NOT_ELIGIBLE", "ND": "NO_DETERMINATION",
               "PE": "PENDING", "DB": "ELIGIBLE"}.get(sc_cls) or derive_verdict(expected, amount)
    # Only an ELIGIBLE verdict has a compensation amount. The base template's leftover free-text note
    # ("CAD 400 cash") parses to CAD 400 for every case, which mislabels the EXPECTED amount on
    # not-eligible / no-determination / pending cases (FD_TC_121 is NOT_ELIGIBLE with no payout, yet the
    # report showed expected 400). Gate the amount on the verdict so the report matches the gap doc.
    if verdict != "ELIGIBLE":
        amount = None
    extras = {
        "disruption": meta.get("fdm_spec") or "",
        "expected_note": expected,
        "pax": meta.get("pax") or "",
        "carrier": meta.get("carrier") or "",
        "flight": meta.get("flight"),
        "date": meta.get("date") or "",
        "minor_or_pax": meta.get("pax") or "",
        # persona/outcome type carried from the gap-doc card through render_case's meta.json
        "scenario": meta.get("scenario") or "",
        "group": meta.get("group") or "",
    }
    # third_party: the gap-doc card's data-arch="thirdparty" (or an explicit meta flag) selects the
    # "filing on behalf of someone else" persona branch in runner.build.build_persona.
    third_party = bool(meta.get("third_party")) or (str(meta.get("scenario") or "").lower() == "thirdparty")
    seed = SeedSpec(
        pnr=loc,
        pnr_id=meta.get("pnr_id", ""),
        passenger=passenger,
        route=meta.get("route", ""),
        ticket=meta.get("ticket", ""),
        status=verdict,
        system_code=meta.get("system_code", ""),  # render_case writes the gap-doc systemCode here
        amount=amount,
        currency=(amount or {}).get("currency", ""),
        flags="",
        extras=extras,
    )
    regime = _regime_from(loc, meta.get("route", ""))
    intent = (f"My flight {meta.get('carrier','')}{meta.get('flight','')} {meta.get('route','')} on "
              f"{meta.get('date','')} was disrupted ({meta.get('fdm_spec','')}). I want to know what "
              f"compensation I'm owed.")
    return UseCase(
        id=case_id, regime=regime, verdict=verdict, system_code=meta.get("system_code", ""),
        title=expected or case_id, third_party=third_party, checkpoint_vector=[],
        customer_intent=intent, expected_transcript=[], seed=seed, seed_pending=False,
        content_hash="",
    )


def _regime_from(loc: str, route: str) -> str:
    """Coarse regime guess from the locator prefix / route (APPR is the AC default; EU/UK/ASL are
    signalled by the fixture naming)."""
    u = loc.upper()
    if u.startswith("FDEU") or u.startswith("FDGUAD"):
        return "EU"
    if u.startswith("FDUK"):
        return "UK"
    if u.startswith("FDASL") or "TLV" in (route or ""):
        return "ASL"
    return "APPR"


def load_fixture_catalog(fixtures_dir, feed_id: str = "fd", only=None) -> Catalog:
    """Scan `fixtures_dir` for `<locator>/meta.json` files and build a Catalog. `only` optionally
    restricts to a set/list of locators (order preserved as given, else sorted)."""
    root = Path(fixtures_dir)
    if only:
        locs = list(only)
    else:
        locs = sorted(p.name for p in root.iterdir()
                      if p.is_dir() and (p / "meta.json").exists())
    cases = []
    for loc in locs:
        mp = root / loc / "meta.json"
        if not mp.exists():
            continue
        meta = json.loads(mp.read_text(encoding="utf-8"))
        cases.append(usecase_from_meta(meta))
    return Catalog(feed_id=feed_id, checkpoints=[], cases=cases, uncovered=[])
