"""canonicalize_verdict produces the bot's assess_eligibility shape for ANY FD verdict/regime from
one base template — the mechanism that makes all 239 cases (not just APPR-CAD-eligible) seedable."""
import json
from pathlib import Path

from seed.dds_pin import canonicalize_verdict, parse_system_code

TEMPLATE = json.loads(Path("data/dds-templates/appr_cad_400.json").read_text(encoding="utf-8"))


def _fresh():
    return json.loads(json.dumps(TEMPLATE))


def _target_pe(resp, regime):
    for c in resp["compensationEligibility"]:
        if (c.get("regime") or "").upper() == regime:
            return c["passengerEligibility"][0]
    raise AssertionError(f"regime {regime} not in template")


def test_parse_system_code():
    assert parse_system_code("FD-APPR-EL-400") == ("APPR", "EL")
    assert parse_system_code("FD-EU-NE-01") == ("EU", "NE")
    assert parse_system_code("FD-ASL-ND-03") == ("ASL", "ND")


def test_appr_eligible():
    r = canonicalize_verdict(_fresh(), system_code="FD-APPR-EL-700", amount=700, currency="CAD",
                             delay_minutes=400, expiry_date="2026-09-01")
    pe = _target_pe(r, "APPR")
    assert pe["eligibilityStatus"] == "ELIGIBLE" and pe["systemCode"] == "FD-APPR-EL-700"
    assert pe["compensationDetails"] == {"amount": 700, "currency": "CAD",
                                         "delayBand": "DELAY_6_TO_LT_9_HOURS",
                                         "expiryDate": "2026-09-01"}


def test_not_eligible_zero_comp():
    r = canonicalize_verdict(_fresh(), system_code="FD-APPR-NE-05", currency="CAD",
                             expiry_date="2026-09-01")
    pe = _target_pe(r, "APPR")
    assert pe["eligibilityStatus"] == "NOT_ELIGIBLE" and pe["systemCode"] == "FD-APPR-NE-05"
    assert pe["compensationDetails"]["amount"] == 0


def test_no_determination():
    r = canonicalize_verdict(_fresh(), system_code="FD-APPR-ND-02", expiry_date="2026-09-01")
    assert _target_pe(r, "APPR")["eligibilityStatus"] == "NO_DETERMINATION"


def test_pending():
    r = canonicalize_verdict(_fresh(), system_code="FD-APPR-PE-01", expiry_date="2026-09-01")
    assert _target_pe(r, "APPR")["eligibilityStatus"] == "PENDING"


def test_eu_eligible_targets_eu_regime():
    r = canonicalize_verdict(_fresh(), system_code="FD-EU-EL-600", amount=600, currency="EUR",
                             delay_minutes=600, expiry_date="2026-09-01")
    assert _target_pe(r, "EU")["eligibilityStatus"] == "ELIGIBLE"
    assert _target_pe(r, "EU")["compensationDetails"]["currency"] == "EUR"
    # APPR (non-target) must be NOT_ELIGIBLE
    assert _target_pe(r, "APPR")["eligibilityStatus"] == "NOT_ELIGIBLE"


def test_asl_eligible_targets_asl_regime():
    r = canonicalize_verdict(_fresh(), system_code="FD-ASL-EL-3580", amount=3580, currency="ILS",
                             delay_minutes=480, expiry_date="2026-09-01")
    assert _target_pe(r, "ASL")["eligibilityStatus"] == "ELIGIBLE"
    assert _target_pe(r, "APPR")["eligibilityStatus"] == "NOT_ELIGIBLE"
