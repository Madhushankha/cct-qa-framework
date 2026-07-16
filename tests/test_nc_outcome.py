"""Offline tests for seed/feeds/nc_outcome.py: unit tests against inline card HTML (fast, no file
I/O) plus a smoke test against the REAL nc gap doc (skips gracefully if not checked out)."""
from pathlib import Path

import pytest

from seed.feeds import nc_outcome

REAL = Path(__file__).resolve().parents[1] / "data" / "gap-docs" / "nc" / "Name_Correction_Miro_Gap_Analysis.html"


def _card(case_id, category, title, checks):
    items = "".join(f'<label class="citem"><input type="checkbox"><span>{c}</span></label>' for c in checks)
    return (
        f'<section class="card" id="{case_id}" data-feat="{category}">'
        f'<span class="tcname">{title}</span>'
        f'<div class="checks">{items}</div>'
        f'</section>'
    )


def test_classify_text_picks_last_signal_not_first():
    # "1 document required" comes first, "successfully corrected" comes later -- the LATER signal
    # (the actual terminal outcome) must win, not the first phrase encountered.
    lines = ["some title", 'Bedrock should return "1 document required"',
             "the name was successfully corrected"]
    assert nc_outcome.classify_text("Happy Path", lines) == "CORRECTED"


def test_classify_text_live_agent_wins_over_earlier_ineligible_wording():
    lines = ["Young Passenger booking blocked", "Display specialized assistance messaging",
             "Live agent handoff should be initiated"]
    assert nc_outcome.classify_text("Ineligible", lines) == "LIVE_AGENT"


def test_classify_text_falls_back_to_category_default_with_no_signal():
    assert nc_outcome.classify_text("Happy Path", ["a title with no signal phrase"]) == "CORRECTED"
    assert nc_outcome.classify_text("Ineligible", ["a title with no signal phrase"]) == "NOT_ELIGIBLE"
    assert nc_outcome.classify_text("Failure Handling", ["nothing informative"]) == "NO_DETERMINATION"
    assert nc_outcome.classify_text("Edge Case", ["nothing informative"]) == "UNKNOWN"
    assert nc_outcome.classify_text("Some Unknown Category", ["x"]) == "UNKNOWN"


def test_classify_text_docs_required():
    lines = ["a title", 'Display "please upload a copy of your passport or government issued ID"']
    assert nc_outcome.classify_text("Happy Path", lines) == "DOCS_REQUIRED"


def test_outcomes_by_id_reads_inline_cards(tmp_path):
    html = "<html><body>" + "".join([
        _card("NameCorrection_TC001", "Happy Path", "nickname correction",
              ["the name was successfully corrected", "Proceed to End Flow"]),
        _card("NameCorrection_TC006", "Ineligible", "Previous correction already exists",
              ["not permitted", "Terminate"]),
        _card("NameCorrection_TC007", "Ineligible", "YP booking blocked",
              ["Display specialized assistance messaging", "Live agent handoff should be initiated"]),
    ]) + "</body></html>"
    p = tmp_path / "nc.html"
    p.write_text(html, encoding="utf-8")

    out = nc_outcome.outcomes_by_id(p)
    assert out == {
        "NameCorrection_TC001": "CORRECTED",
        "NameCorrection_TC006": "NOT_ELIGIBLE",
        "NameCorrection_TC007": "LIVE_AGENT",
    }


def test_outcome_for_looks_up_precomputed_map():
    class UC:
        id = "NameCorrection_TC001"

    assert nc_outcome.outcome_for(UC(), {"NameCorrection_TC001": "CORRECTED"}) == "CORRECTED"
    assert nc_outcome.outcome_for(UC(), {}) == "UNKNOWN"


@pytest.mark.skipif(not REAL.exists(), reason="real NC gap doc not present")
def test_outcomes_by_id_against_real_doc():
    out = nc_outcome.outcomes_by_id(REAL)
    assert len(out) == 67
    assert set(out.values()) <= set(nc_outcome.VERDICTS)
    # a handful of cases whose card text is unambiguous even by eye.
    assert out["NameCorrection_TC001"] == "CORRECTED"  # "successfully corrected", 0 docs
    assert out["NameCorrection_TC006"] == "NOT_ELIGIBLE"  # previous correction already exists
    assert out["NameCorrection_TC007"] == "LIVE_AGENT"  # YP booking -> live agent handoff
    assert out["NameCorrection_TC029"] == "LIVE_AGENT"  # ACV booking -> ACV live agent
    # every verdict bucket is populated -- the heuristic isn't collapsing everything to one value.
    from collections import Counter
    counts = Counter(out.values())
    assert counts["CORRECTED"] > 0 and counts["LIVE_AGENT"] > 0 and counts["NOT_ELIGIBLE"] > 0
