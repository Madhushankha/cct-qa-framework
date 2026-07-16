"""Shared test fixtures for the P1 catalog test suite.

Defines a small synthetic ``Feed`` descriptor (independent of the real fd/soc registry
entries, whose real gap-doc HTML files are not present in this repo) wired to the
tests/fixtures/*.html files, so parser/diff/cli tests are fully offline and self-contained.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from core.descriptors import Feed

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"
GAP_MIN = FIXTURES_DIR / "gap_min.html"
GAP_MIN_V2 = FIXTURES_DIR / "gap_min_v2.html"
DATASET_MIN = FIXTURES_DIR / "dataset_min.html"

CATALOG_TEST_COLUMNS = {
    "pnr": "PNR",
    "pnr_id": "pnrId",
    "passenger": "Passenger",
    "route": "Route",
    "ticket": "Ticket",
    "status": "Status",
    "system_code": "SysCode",
    "amount": "Amount",
    "currency": "Currency",
    "flags": "Flags",
    "third_party": ["ThirdParty"],
}


def make_feed(gap_doc: Path = GAP_MIN, dataset: Path | None = DATASET_MIN) -> Feed:
    return Feed(
        id="gapmin",
        label="Gap Min Test Feed",
        gap_doc=str(gap_doc),
        columns=dict(CATALOG_TEST_COLUMNS),
        persona={"default": "test persona", "branches": {}},
        judge={"verdict_enum": ["Eligible", "Not Eligible", "Pending", "No Determination"],
               "match_on": ["status", "system_code"]},
        checkpoints={"auditor": "soc", "areas": []},
        dataset=str(dataset) if dataset else "",
    )


@pytest.fixture
def feed() -> Feed:
    return make_feed()


@pytest.fixture
def feed_no_dataset() -> Feed:
    return make_feed(dataset=None)
