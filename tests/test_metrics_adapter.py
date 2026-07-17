"""Tests for metrics.adapter.result_to_record: canonical Result (P0) -> evalkit's
normalized EvalRecord dict.
"""
from __future__ import annotations

from core.result import validate_result
from metrics.adapter import result_to_record


def _base(test_case, system_code, regime, expected_status, expected_amount,
          decision, matches_expected, actual_amount=None, error=None,
          checks=None, product="bravo", env="crt", contact_id="c1"):
    return {
        "schema_version": "1.0",
        "scenario_id": f"{product}.{env}.fd.{test_case}",
        "run": {"product": product, "env": env, "feed": "fd", "date": "2026-07-14",
                "run_id": "r1", "started": "2026-07-14T00:00:00Z", "duration_s": 12.5},
        "case": {"test_case": test_case, "pnr": "GQWKRH", "pnr_id": "GQWKRH-2026-06-15",
                 "passenger": "OONA BROOKINGDALE", "regime": regime,
                 "expected_status": expected_status,
                 "expected_system_code": system_code,
                 "expected_amount": expected_amount,
                 "flags": [], "third_party": False},
        "seed": {"verified": True,
                 "checkpoints": [{"area": "eds_contact_email", "pass": True}],
                 "dds": None},
        "auth": {"otp_fetched": True, "contact_id": contact_id},
        "verdict": {"decision": decision, "amount": actual_amount,
                    "reached_determination": matches_expected,
                    "matches_expected": matches_expected,
                    "checks": checks if checks is not None else
                    [{"name": "Eligibility status", "expected": expected_status,
                      "actual": decision, "pass": matches_expected}],
                    "reasoning": "bot reasoning text"},
        "harness": {"error": error, "error_bucket": None},
        "transcript": [{"role": "customer", "text": "hi", "ts": "t1", "note": None}],
        "evidence": {"chat_html": None, "evidence_html": None},
    }


def eligible_result():
    r = _base("FD_TC_001", "FD-EU-EL-27", "EU", "ELIGIBLE",
               {"currency": "GBP", "value": 520.0},
               "ELIGIBLE", True,
               actual_amount={"currency": "GBP", "value": 520.0})
    validate_result(r)
    return r


def not_eligible_result():
    r = _base("FD_TC_ED_014", "FD-APPR-NE-03", "APPR", "NOT_ELIGIBLE", None,
               "ESCALATED", False,
               error="No bot reply received within 30s",
               checks=[{"name": "Eligibility status", "expected": "NOT_ELIGIBLE",
                        "actual": "ESCALATED", "pass": False},
                       {"name": "Compensation amount", "expected": "none",
                        "actual": "none", "pass": True}])
    validate_result(r)
    return r


def test_result_to_record_maps_eligible_case():
    rec = result_to_record(eligible_result())

    assert rec["agent"] == "bravo"
    assert rec["env"] == "crt"
    assert rec["test_id"] == "FD_TC_001"
    assert rec["family"] == "CORE"
    assert rec["regime"] == "EU"
    assert rec["decision_class"] == "EL"
    assert rec["expected_status"] == "ELIGIBLE"
    assert rec["expected_amount"] == ("GBP", 520.0)
    assert rec["expected_system_code"] == "FD-EU-EL-27"
    assert rec["actual_status"] == "ELIGIBLE"
    assert rec["actual_amount_raw"] == "GBP 520.0"
    assert rec["overall_pass"] is True
    assert rec["run_error"] is None
    assert rec["contact_id"] == "c1"
    assert rec["duration_s"] == 12.5
    assert rec["started"] == "2026-07-14T00:00:00Z"
    assert rec["turns"] == 1  # derived from the inline transcript (1 turn in the fixture)
    assert rec["transcript_path"] is None
    assert "🧑 CUSTOMER" in rec["transcript_text"] and "hi" in rec["transcript_text"]
    assert len(rec["checks"]) == 1
    assert rec["checks"][0] == {"raw_name": "Eligibility status", "canonical": "eligibility_status",
                                 "passed": True}


def test_result_to_record_maps_not_eligible_ed_case_with_error_and_no_amount():
    rec = result_to_record(not_eligible_result())

    assert rec["family"] == "ED"
    assert rec["regime"] == "APPR"
    assert rec["decision_class"] == "NE"
    assert rec["expected_status"] == "NOT_ELIGIBLE"
    assert rec["expected_amount"] is None
    assert rec["actual_status"] == "ESCALATED"
    assert rec["actual_amount_raw"] == "none"
    assert rec["overall_pass"] is False
    assert rec["run_error"] == "No bot reply received within 30s"
    assert len(rec["checks"]) == 2
    canonicals = {c["canonical"] for c in rec["checks"]}
    assert "eligibility_status" in canonicals
    assert "compensation_amount" in canonicals


def test_result_to_record_regime_falls_back_when_system_code_has_no_regime_segment():
    r = _base("FD_TC_PAY_002", "", "MIXED", "PENDING", None, "PENDING", False)
    validate_result(r)
    rec = result_to_record(r)

    assert rec["family"] == "PAY"
    assert rec["regime"] == "MIXED"
    assert rec["decision_class"] == "UNKNOWN"
    assert rec["expected_system_code"] == ""
