"""extract_verdict must surface the real verdict for NEGATIVE scenarios (NOT_ELIGIBLE /
NO_DETERMINATION / PENDING), not just ELIGIBLE — so the DDS checkpoints pass for those cases."""
import json

from seed.dds_pin import extract_verdict


def _body(regimes):
    return json.dumps({"compensationEligibility": [
        {"regime": reg, "passengerEligibility": [pe]} for reg, pe in regimes]})


def test_eligible():
    body = _body([("APPR", {"eligibilityStatus": "ELIGIBLE", "systemCode": "FD-APPR-EL-01",
                            "reason": "eligible", "compensationDetails": {"amount": 400}}),
                  ("EU", {"eligibilityStatus": "NOT_ELIGIBLE", "systemCode": "FD-EU-NA-01"})])
    v = extract_verdict(body, 200)
    assert v["eligible"] and v["system_code"] == "FD-APPR-EL-01" and v["amount"] == 400


def test_not_eligible_surfaces_code_amount_reason():
    body = _body([("APPR", {"eligibilityStatus": "NOT_ELIGIBLE", "systemCode": "FD-APPR-NE-02",
                            "reason": "Not eligible for compensation.",
                            "compensationDetails": {"amount": 0}}),
                  ("EU", {"eligibilityStatus": "NOT_ELIGIBLE", "systemCode": "FD-EU-NA-01"})])
    v = extract_verdict(body, 200)
    assert v["eligible"] is False
    assert v["system_code"] == "FD-APPR-NE-02"   # the real negative verdict, not none
    assert v["amount"] == 0 and v["reason"]      # amount 0 + a reason -> checkpoints pass


def test_no_determination():
    body = _body([("APPR", {"eligibilityStatus": "NO_DETERMINATION", "systemCode": "FD-APPR-ND-02",
                            "reason": "no determination", "compensationDetails": {"amount": 0}})])
    v = extract_verdict(body, 200)
    assert v["system_code"] == "FD-APPR-ND-02" and v["reason"] and v["eligible"] is False


def test_only_na_regimes_yields_nothing():
    body = _body([("EU", {"eligibilityStatus": "NOT_ELIGIBLE", "systemCode": "FD-EU-NA-01"})])
    v = extract_verdict(body, 200)
    assert v["system_code"] is None  # all not-applicable -> no real verdict surfaced
