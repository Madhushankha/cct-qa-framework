from catalog.model import SeedSpec, UseCase
from seed.scenario import change


def _uc(case_id, title):
    return UseCase(id=case_id, regime="", verdict="", system_code="", title=title,
                   third_party=False, checkpoint_vector=[], customer_intent="",
                   expected_transcript=[], seed=SeedSpec(), seed_pending=True)


def test_change_kind_from_feed_hint():
    uc = _uc("NameCorrection_TC001", "Window 1 — Single pax, 0 documents, nickname correction")
    assert change(uc, feed="nc") == {"kind": "name", "from": None, "to": None}

    uc = _uc("SeatChange_TC001", "Single-pax single-leg seat change via web")
    assert change(uc, feed="seatchange") == {"kind": "seat", "from": None, "to": None}


def test_change_kind_from_id_prefix_when_no_feed_hint():
    uc = _uc("NameCorrection_TC012", "Invalid PNR during identification")
    assert change(uc) == {"kind": "name", "from": None, "to": None}

    uc = _uc("SeatChange_TC020", "Full flow blocked because flight departs in less than 1 hour")
    assert change(uc) == {"kind": "seat", "from": None, "to": None}


def test_change_feed_hint_overrides_mislabeled_id():
    # Real data quirk: this nc gap-doc card is mislabeled `SeatChange_TC049` upstream but is an NC
    # (name) case ("Name with slight misspelling passes identification and completes flow"). The
    # feed hint sidesteps the id-prefix ambiguity.
    uc = _uc("SeatChange_TC049", "Name with slight misspelling passes identification and completes flow")
    assert change(uc, feed="nc") == {"kind": "name", "from": None, "to": None}
    assert change(uc) == {"kind": "seat", "from": None, "to": None}  # no hint: id prefix wins


def test_change_none_for_non_update_case():
    uc = _uc("FD_TC001", "Travel Completed | APPR | Delay 3-<6 hrs")
    assert change(uc) is None
    assert change(uc, feed="fd") is None


def test_change_from_to_are_none_until_parser_captures_gherkin_steps():
    """Documents the current gap: the gap docs carry no datagrid/transcript field with the
    concrete old->new name or seat value, so from/to stay None (see change()'s docstring)."""
    uc = _uc("NameCorrection_TC001", "Window 1 — Single pax, 0 documents, nickname correction")
    result = change(uc, feed="nc")
    assert result["from"] is None
    assert result["to"] is None
