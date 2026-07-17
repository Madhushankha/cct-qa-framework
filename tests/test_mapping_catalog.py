"""Tests for catalog/mapping.py — gap/SIT mapping markdown -> test cases keyed by test-case id."""
from catalog.mapping import parse_mapping, usecase_from_row


def test_row_eligible():
    uc = usecase_from_row("FD-SIT-001", ["ZFD001", "THOMPSON", "YYZ→YVR", "APPR 3-6hr delay",
                                         "CAD 400 cash"], "Eligible - Travel Completed (16)")
    assert uc.id == "FD-SIT-001" and uc.seed.pnr == "ZFD001"
    assert uc.seed.passenger == "THOMPSON" and uc.regime == "APPR"
    assert uc.verdict == "ELIGIBLE" and uc.seed.amount == {"currency": "CAD", "value": 400.0}
    assert uc.seed.route == "YYZ-YVR"


def test_not_eligible_section_not_confused_with_eligible():
    uc = usecase_from_row("FD-SIT-024", ["ZFD024", "GREEN", "YYZ→YVR", "Below threshold",
                                         "Not eligible"], "Not Eligible (11)")
    assert uc.verdict == "NOT_ELIGIBLE"


def test_regime_from_currency():
    uk = usecase_from_row("FD-SIT-008", ["ZFD008", "MARTIN", "LHR→YYZ", "EU/UK 261 UK", "GBP 260"], "Eligible")
    assert uk.regime == "UK" and uk.seed.amount["currency"] == "GBP"
    asl = usecase_from_row("FD-SIT-014", ["ZFD014", "WHITE", "TLV→YYZ", "ASL Israel", "ILS 3,580"], "Eligible")
    assert asl.regime == "ASL"


def test_parse_mapping_tmp(tmp_path):
    md = tmp_path / "m.md"
    md.write_text("## Eligible - Travel Completed (2)\n"
                  "| SIT ID | PNR | Last Name | Route | Scenario | Expected |\n"
                  "|---|---|---|---|---|---|\n"
                  "| FD-SIT-001 | ZFD001 | THOMPSON | YYZ→YVR | APPR | CAD 400 cash |\n"
                  "## Not Eligible (1)\n"
                  "| FD-SIT-024 | ZFD024 | GREEN | YYZ→YVR | Below | Not eligible |\n", encoding="utf-8")
    cat = parse_mapping(md)
    assert [c.id for c in cat.cases] == ["FD-SIT-001", "FD-SIT-024"]
    assert cat.cases[0].verdict == "ELIGIBLE" and cat.cases[1].verdict == "NOT_ELIGIBLE"
