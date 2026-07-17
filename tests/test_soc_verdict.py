"""Offline tests for seed/feeds/soc_verdict.py (no boto3 / no live rule-engine)."""
import json
from pathlib import Path

import pytest

from seed.feeds.soc_verdict import canonicalize_soc_verdict, parse_soc_system_code

_TEMPLATE_PATH = Path("data/seed-templates/soc/base/dds_soc_appr.json")


def _template() -> dict:
    return json.loads(_TEMPLATE_PATH.read_text(encoding="utf-8"))


def test_parse_soc_system_code_regime_class():
    assert parse_soc_system_code("SoC-APPR-EL-07") == ("APPR", "EL")
    assert parse_soc_system_code("SoC-EU-NE-06") == ("EU", "NE")
    assert parse_soc_system_code("") == ("APPR", "EL")


def test_parse_soc_system_code_override_family():
    assert parse_soc_system_code("SoC-Override-Pending") == ("OVERRIDE", "PENDING")
    assert parse_soc_system_code("SoC-Override-Pay") == ("OVERRIDE", "PAY")


def test_canonicalize_soc_verdict_eligible_appr():
    out = canonicalize_soc_verdict(
        _template(), system_code="SoC-APPR-EL-07", delay_category="DELAY_GE_2_HOURS",
        delay_minutes=120, expense_categories=["MEALS", "HOTEL"], expiry_date="2027-07-16")

    appr = next(e for e in out["socFlightEligibility"] if e["regime"] == "APPR")
    pe = appr["passengerEligibility"][0]
    assert pe["eligibilityStatus"] == "ELIGIBLE"
    assert pe["systemCode"] == "SoC-APPR-EL-07"
    assert pe["expenseCategories"] == ["MEALS", "HOTEL"]
    assert pe["expiryDate"] == "2027-07-16"
    assert appr["delayCategory"] == "DELAY_GE_2_HOURS"
    assert appr["delayMinutes"] == 120

    # other regimes marked not-applicable
    eu = next(e for e in out["socFlightEligibility"] if e["regime"] == "EU")
    pe_eu = eu["passengerEligibility"][0]
    assert pe_eu["eligibilityStatus"] == "NOT_ELIGIBLE"
    assert pe_eu["systemCode"] == "SoC-EU-NA-01"
    assert pe_eu["expenseCategories"] == []


def test_canonicalize_soc_verdict_not_eligible_has_no_expenses():
    out = canonicalize_soc_verdict(
        _template(), system_code="SoC-APPR-NE-01", delay_category="DELAY_LT_2_HOURS")
    appr = next(e for e in out["socFlightEligibility"] if e["regime"] == "APPR")
    pe = appr["passengerEligibility"][0]
    assert pe["eligibilityStatus"] == "NOT_ELIGIBLE"
    assert pe["systemCode"] == "SoC-APPR-NE-01"
    assert pe["expenseCategories"] == []
    assert pe["expiryDate"] == ""


def test_canonicalize_soc_verdict_no_determination_and_pending():
    nd = canonicalize_soc_verdict(_template(), system_code="SoC-APPR-ND-03",
                                  delay_category="DELAY_LT_2_HOURS")
    pe_nd = next(e for e in nd["socFlightEligibility"] if e["regime"] == "APPR")["passengerEligibility"][0]
    assert pe_nd["eligibilityStatus"] == "NO_DETERMINATION"

    pe = canonicalize_soc_verdict(_template(), system_code="SoC-APPR-PE-01",
                                  delay_category="DELAY_LT_2_HOURS")
    pe_pe = next(e for e in pe["socFlightEligibility"] if e["regime"] == "APPR")["passengerEligibility"][0]
    assert pe_pe["eligibilityStatus"] == "PENDING"


def test_canonicalize_soc_verdict_override_raises():
    with pytest.raises(ValueError):
        canonicalize_soc_verdict(_template(), system_code="SoC-Override-Pending",
                                 delay_category="DELAY_LT_2_HOURS")


def test_canonicalize_soc_verdict_does_not_mutate_input_by_reference_elsewhere():
    # the function mutates `response` in place (documented behavior, mirrors dds_pin.canonicalize_verdict) --
    # confirm the return value IS the same object, and a fresh load is unaffected.
    t = _template()
    out = canonicalize_soc_verdict(t, system_code="SoC-APPR-EL-07", delay_category="DELAY_GE_2_HOURS")
    assert out is t
    fresh = _template()
    fresh_appr = next(e for e in fresh["socFlightEligibility"] if e["regime"] == "APPR")
    assert fresh_appr["passengerEligibility"][0]["eligibilityStatus"] == "NO_DETERMINATION"
