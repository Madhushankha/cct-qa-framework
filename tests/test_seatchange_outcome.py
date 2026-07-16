"""Offline tests for seed/feeds/seatchange_outcome.py: unit tests against inline card HTML (fast,
no file I/O) plus a smoke test against the REAL seatchange gap doc (skips gracefully if not checked
out)."""
from pathlib import Path

import pytest

from seed.feeds import seatchange_outcome

REAL = (Path(__file__).resolve().parents[1] / "data" / "gap-docs" / "seatchange"
        / "Seat_Change_Miro_Gap_Analysis.html")


def _card(case_id, category, title, checks):
    items = "".join(f'<label class="citem"><input type="checkbox"><span>{c}</span></label>' for c in checks)
    return (
        f'<section class="card" id="{case_id}" data-feat="{category}">'
        f'<span class="tcname">{title}</span>'
        f'<div class="checks">{items}</div>'
        f'</section>'
    )


def test_classify_text_seat_changed_from_sc03a_wording():
    lines = ["single-pax seat change", 'Display SC-03a: "Your seat has been changed."', "End"]
    assert seatchange_outcome.classify_text("Happy Path", lines) == "SEAT_CHANGED"


def test_classify_text_declined_wins_over_earlier_happy_path_default():
    lines = ["User declines payment and abandons seat change entirely", "End",
             "No seat change should be recorded", "The original seat should remain unchanged"]
    assert seatchange_outcome.classify_text("Happy Path", lines) == "DECLINED"


def test_classify_text_live_agent():
    lines = ["Full flow stopped after all OTP codes exhausted", "Prompt to retry IDV",
             "Transition to Live Agent Handoff (LAH)"]
    assert seatchange_outcome.classify_text("Auth Failure", lines) == "LIVE_AGENT"


def test_classify_text_payment_required():
    lines = ["expired credit card", 'Display "Your card has expired."',
             "Remain on the payment screen", "Selection should be preserved"]
    assert seatchange_outcome.classify_text("Payment", lines) == "PAYMENT_REQUIRED"


def test_classify_text_falls_back_to_category_default_with_no_signal():
    assert seatchange_outcome.classify_text("Happy Path", ["no signal here"]) == "SEAT_CHANGED"
    assert seatchange_outcome.classify_text("Eligibility Block", ["no signal here"]) == "DECLINED"
    assert seatchange_outcome.classify_text("Seat Map", ["no signal here"]) == "NO_DETERMINATION"
    assert seatchange_outcome.classify_text("Payment", ["no signal here"]) == "PAYMENT_REQUIRED"
    assert seatchange_outcome.classify_text("Disruption", ["no signal here"]) == "LIVE_AGENT"
    assert seatchange_outcome.classify_text("Edge Cases", ["no signal here"]) == "UNKNOWN"
    assert seatchange_outcome.classify_text("Not A Real Category", ["x"]) == "UNKNOWN"


def test_outcomes_by_id_reads_inline_cards(tmp_path):
    html = "<html><body>" + "".join([
        _card("SeatChange_TC001", "Happy Path", "seat change via web",
              ['Display SC-03a: "Your seat has been changed."', "End"]),
        _card("SeatChange_TC013", "Eligibility Block", "blocked at ACV booking source",
              ['Display "Contact Air Canada Vacations"', "End"]),
        _card("SeatChange_TC028", "Auth Failure", "OTP codes exhausted",
              ["Prompt to retry IDV", "Transition to Live Agent Handoff (LAH)"]),
    ]) + "</body></html>"
    p = tmp_path / "seatchange.html"
    p.write_text(html, encoding="utf-8")

    out = seatchange_outcome.outcomes_by_id(p)
    assert out == {
        "SeatChange_TC001": "SEAT_CHANGED",
        "SeatChange_TC013": "DECLINED",
        "SeatChange_TC028": "LIVE_AGENT",
    }


def test_outcome_for_looks_up_precomputed_map():
    class UC:
        id = "SeatChange_TC001"

    assert seatchange_outcome.outcome_for(UC(), {"SeatChange_TC001": "SEAT_CHANGED"}) == "SEAT_CHANGED"
    assert seatchange_outcome.outcome_for(UC(), {}) == "UNKNOWN"


@pytest.mark.skipif(not REAL.exists(), reason="real seatchange gap doc not present")
def test_outcomes_by_id_against_real_doc():
    out = seatchange_outcome.outcomes_by_id(REAL)
    assert len(out) == 67
    assert set(out.values()) <= set(seatchange_outcome.VERDICTS)
    # a handful of cases whose card text is unambiguous even by eye.
    assert out["SeatChange_TC001"] == "SEAT_CHANGED"  # web + credit card, ends "seat has been changed"
    assert out["SeatChange_TC013"] == "DECLINED"  # ACV booking source blocked
    assert out["SeatChange_TC028"] == "LIVE_AGENT"  # OTP exhausted -> LAH
    assert out["SeatChange_TC036"] == "PAYMENT_REQUIRED"  # expired card, remain on payment screen
    from collections import Counter
    counts = Counter(out.values())
    assert counts["SEAT_CHANGED"] > 0 and counts["DECLINED"] > 0 and counts["LIVE_AGENT"] > 0
