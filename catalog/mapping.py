"""Gap-doc test-case catalog: parse an FD SIT/UAT *PNR-mapping* markdown table into a Catalog of
UseCases keyed by the REAL test-case id (FD-SIT-###, FD_TC_###).

The mapping doc is the operational form of the gap-analysis doc — each row binds a test-case id to a
PNR, last name, route, scenario, and the expected verdict/amount, grouped under a section header that
names the verdict class ("Eligible - Travel Completed", "Not Eligible", "No Determination & Pending",
...). This is the source of truth for the pipeline: parse -> seed per case -> run per case -> report,
all keyed by the test-case id (so a report is `FD-SIT-001.evidence.html`, not a synthetic locator).

Reuses catalog.fixtures.parse_amount for the free-text Expected column.
"""
from __future__ import annotations

import re
from pathlib import Path

from catalog.fixtures import parse_amount
from catalog.model import Catalog, SeedSpec, UseCase

_ROW_RE = re.compile(r"^\|\s*(FD[-_][A-Z]+[-_]\d+|FD_TC_\d+)\s*\|(.+)\|\s*$", re.IGNORECASE)
_SECTION_RE = re.compile(r"^##\s+(.+?)\s*(?:\(\d+\))?\s*$")

# section-header keyword -> verdict class. ORDER MATTERS: the negative/no-determination keywords are
# checked before "eligible" because "eligible" is a substring of "not eligible".
_SECTION_VERDICT = (
    ("not eligible", "NOT_ELIGIBLE"),
    ("no determination", "NO_DETERMINATION"),
    ("pending", "PENDING"),
    ("no travel", "ELIGIBLE"),
    ("mixed regime", "ELIGIBLE"),
    ("eligible", "ELIGIBLE"),          # "Eligible - Travel Completed"
)


def _verdict_for(section: str, expected: str) -> str:
    low_sec = (section or "").lower()
    for needle, verdict in _SECTION_VERDICT:
        if needle in low_sec:
            return verdict
    # functional sections (auth, payment, fraud, ...) — infer from the Expected text
    low_exp = (expected or "").lower()
    if "not eligible" in low_exp:
        return "NOT_ELIGIBLE"
    if "no determination" in low_exp:
        return "NO_DETERMINATION"
    if "pending" in low_exp:
        return "PENDING"
    if parse_amount(expected):
        return "ELIGIBLE"
    return "UNKNOWN"


def _regime_for(scenario: str, route: str, amount) -> str:
    s = (scenario or "").upper()
    if "ASL" in s or "TLV" in (route or ""):
        return "ASL"
    if "UK" in s or "GBP" in s:
        return "UK"
    if "EU" in s or (amount or {}).get("currency") in ("EUR", "GBP"):
        return "EU"
    return "APPR"


def usecase_from_row(sit_id: str, cells: list[str], section: str) -> UseCase:
    # columns after the id: PNR | Last Name | Route | Scenario | Expected
    pnr = cells[0].strip() if len(cells) > 0 else ""
    last = cells[1].strip() if len(cells) > 1 else ""
    route = (cells[2].strip() if len(cells) > 2 else "").replace("→", "-").replace(" ", "")
    scenario = cells[3].strip() if len(cells) > 3 else ""
    expected = cells[4].strip() if len(cells) > 4 else ""
    amount = parse_amount(expected)
    verdict = _verdict_for(section, expected)
    regime = _regime_for(scenario, route, amount)
    seed = SeedSpec(pnr=pnr, pnr_id="", passenger=last, route=route, ticket="",
                    status=verdict, system_code="", amount=amount,
                    currency=(amount or {}).get("currency", ""), flags="",
                    extras={"scenario": scenario, "expected_note": expected, "section": section,
                            "last_name": last})
    intent = f"I want to file a flight-disruption compensation claim. {scenario}".strip()
    return UseCase(id=sit_id.upper().replace("_", "-") if sit_id.upper().startswith("FD-") else sit_id,
                   regime=regime, verdict=verdict, system_code="", title=f"{scenario} — {expected}",
                   third_party=("third" in section.lower()), checkpoint_vector=[],
                   customer_intent=intent, expected_transcript=[], seed=seed, seed_pending=False)


def parse_mapping(md_path, feed_id: str = "fd", only=None) -> Catalog:
    """Parse the mapping markdown into a Catalog. `only` restricts to a set of test-case ids."""
    section = ""
    cases = []
    for line in Path(md_path).read_text(encoding="utf-8").splitlines():
        sec = _SECTION_RE.match(line.strip())
        if sec:
            section = sec.group(1)
            continue
        m = _ROW_RE.match(line.strip())
        if not m:
            continue
        sit_id = m.group(1)
        cells = [c.strip() for c in m.group(2).split("|")]
        uc = usecase_from_row(sit_id, cells, section)
        if only and uc.id not in only:
            continue
        cases.append(uc)
    return Catalog(feed_id=feed_id, checkpoints=[], cases=cases, uncovered=[])
