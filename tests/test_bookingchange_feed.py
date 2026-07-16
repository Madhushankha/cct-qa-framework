"""bookingchange registry + two-doc gap-doc merge (INVOL + VOL -> one Catalog).

Uses small synthetic INVOL/VOL gap docs (not the real ~8.5k-line HTML) so the merge mechanics
(catalog.parser.load_catalog with Feed.gap_docs) are exercised offline and fast; a separate smoke
test below parses the REAL committed docs and asserts the exact case count the task validated.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from catalog.parser import load_catalog
from core.descriptors import Feed
from core.registry import load_feed
from core.validate import validate_feed

_CARD = """
<section class="card" id="{id}" data-feat="{feat}" data-gaps="0">
<header class="ch">
<span class="tcid">{id}</span>
<span class="badge req">{prio}</span>
<span class="tcname">{title}</span>
</header>
<div class="stagerow">
<span class="stage sc-cov" title="Conversation Entry">GLOB-01</span>
</div>
<div class="intbub">My booking changed</div>
</section>
"""

_SPINE = """
<details class="spine" open><summary>spine</summary><div class="spwrap">
<div class="spx"><span class="spid">GLOB-01</span><span class="spl">Conversation Entry</span><span class="spm m-a">core</span><span class="spn">2</span></div>
</div></details>
"""


def _doc(cards: list[str]) -> str:
    return f"<!DOCTYPE html><html><body>{_SPINE}{''.join(cards)}</body></html>"


@pytest.fixture
def two_doc_feed(tmp_path: Path) -> Feed:
    invol = tmp_path / "Booking_Change_INVOL_Miro_Gap_Analysis.html"
    vol = tmp_path / "Booking_Change_VOL_Miro_Gap_Analysis.html"
    invol.write_text(_doc([
        _CARD.format(id="InVOL_TC001", feat="Eligible", prio="P1", title="Accepts proposed itinerary"),
        _CARD.format(id="InVOL_TC002", feat="Ineligible", prio="P2", title="Rejects proposal"),
    ]), encoding="utf-8")
    vol.write_text(_doc([
        _CARD.format(id="VOL_TC001", feat="Eligible", prio="P1", title="Higher fare change"),
    ]), encoding="utf-8")
    return Feed(
        id="bctest", label="BC test", gap_doc="",
        columns={k: k for k in ("pnr", "pnr_id", "passenger", "route", "ticket",
                                 "status", "system_code", "amount", "currency", "flags")},
        persona={"default": "hi"}, judge={"verdict_enum": ["ELIGIBLE"]},
        checkpoints={"auditor": "bctest"}, gap_docs=(str(invol), str(vol)),
    )


def test_two_doc_merge_concatenates_cases(two_doc_feed):
    cat = load_catalog(two_doc_feed)
    assert len(cat.cases) == 3
    assert {c.id for c in cat.cases} == {"InVOL_TC001", "InVOL_TC002", "VOL_TC001"}


def test_two_doc_merge_dedupes_shared_checkpoints(two_doc_feed):
    cat = load_catalog(two_doc_feed)
    assert [cp.id for cp in cat.checkpoints] == ["GLOB-01"]


def test_two_doc_merge_tags_source_doc(two_doc_feed):
    cat = load_catalog(two_doc_feed)
    assert cat.by_id("InVOL_TC001").seed.extras["source_doc"] == "Booking_Change_INVOL_Miro_Gap_Analysis"
    assert cat.by_id("VOL_TC001").seed.extras["source_doc"] == "Booking_Change_VOL_Miro_Gap_Analysis"


def test_single_doc_feed_unaffected(tmp_path):
    """A feed with only `gap_doc` (no gap_docs) still works exactly as before."""
    doc = tmp_path / "one.html"
    doc.write_text(_doc([_CARD.format(id="X-001", feat="Eligible", prio="P1", title="one")]),
                    encoding="utf-8")
    f = Feed(id="one", label="one", gap_doc=str(doc),
             columns={k: k for k in ("pnr", "pnr_id", "passenger", "route", "ticket",
                                      "status", "system_code", "amount", "currency", "flags")},
             persona={"default": "hi"}, judge={"verdict_enum": ["ELIGIBLE"]},
             checkpoints={"auditor": "one"})
    cat = load_catalog(f)
    assert len(cat.cases) == 1
    assert cat.cases[0].seed.extras == {}  # no source_doc tag on the single-doc path


# --- the real registry entry ------------------------------------------------------------------

def test_bookingchange_feed_registers_and_validates():
    f = load_feed("bookingchange")
    validate_feed(f)  # no raise
    assert len(f.gap_docs) == 2


REAL_INVOL = (Path(__file__).resolve().parents[1] / "data" / "gap-docs" / "bookingchange" /
              "Booking_Change_INVOL_Miro_Gap_Analysis.html")
REAL_VOL = (Path(__file__).resolve().parents[1] / "data" / "gap-docs" / "bookingchange" /
            "Booking_Change_VOL_Miro_Gap_Analysis.html")


@pytest.mark.skipif(not (REAL_INVOL.exists() and REAL_VOL.exists()),
                     reason="real bookingchange gap docs not present")
def test_parses_real_bookingchange_gap_docs():
    cat = load_catalog(load_feed("bookingchange"))
    assert len(cat.cases) == 109  # 58 INVOL + 51 VOL
    assert all(c.seed_pending for c in cat.cases)  # neither doc embeds a per-case datagrid
