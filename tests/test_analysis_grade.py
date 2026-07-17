"""Tests for analysis.grade: canonical Result -> {grade, status, confidence, findings}."""
from __future__ import annotations

from core.result import validate_result

from analysis.grade import grade


def _base(*, matches_expected=True, seed_verified=True, checks=None,
          harness_error=None, harness_bucket=None, decision="ELIGIBLE",
          dds_status="ELIGIBLE", expected_status="ELIGIBLE"):
    checks = checks if checks is not None else [
        {"name": "Eligibility", "expected": expected_status, "actual": decision, "pass": matches_expected}
    ]
    doc = {
        "schema_version": "1.0",
        "scenario_id": "bravo.crt.fd.FD_TC_001",
        "run": {"product": "bravo", "env": "crt", "feed": "fd", "date": "2026-07-14",
                "run_id": "r1", "started": "2026-07-14T00:00:00Z", "duration_s": 12.5},
        "case": {"test_case": "FD_TC_001", "pnr": "GQWKRH", "pnr_id": "GQWKRH-2026-06-15",
                 "passenger": "OONA BROOKINGDALE", "regime": "EU",
                 "expected_status": expected_status, "expected_system_code": "FD-EU-EL-27",
                 "expected_amount": {"currency": "GBP", "value": 520},
                 "flags": [], "third_party": False},
        "seed": {"verified": seed_verified,
                 "checkpoints": [{"area": "eds_contact_email", "pass": True}],
                 "dds": {"status": dds_status, "system_code": "FD-EU-EL-27",
                         "amount": {"currency": "GBP", "value": 520}, "trace_s3": "s3://x"}
                 if dds_status is not None else None},
        "auth": {"otp_fetched": True, "contact_id": "c1"},
        "verdict": {"decision": decision, "amount": None, "reached_determination": matches_expected,
                    "matches_expected": matches_expected, "checks": checks,
                    "reasoning": "bot reasoning text"},
        "harness": {"error": harness_error, "error_bucket": harness_bucket},
        "transcript": [{"role": "customer", "text": "hi", "ts": "t1", "note": None}],
        "evidence": {"chat_html": None, "evidence_html": None},
    }
    validate_result(doc)
    return doc


def test_clean_pass_is_strong_pass_confidence_95():
    doc = _base(matches_expected=True, seed_verified=True, decision="ELIGIBLE", dds_status="ELIGIBLE")
    g = grade(doc)
    assert g["grade"] == "Strong PASS"
    assert g["status"] == "PASS"
    assert g["confidence"] == 95
    assert g["findings"] == []


def test_pass_with_failed_check_is_invalid_pass():
    doc = _base(matches_expected=True, seed_verified=True,
                 checks=[{"name": "Amount", "expected": "520", "actual": "520", "pass": True},
                         {"name": "Eligibility", "expected": "ELIGIBLE", "actual": "ELIGIBLE", "pass": False}])
    g = grade(doc)
    assert g["grade"] == "Invalid PASS"
    assert g["status"] == "INVALID"
    codes = [f["code"] for f in g["findings"]]
    assert "PASS_WITH_FAILED_ASSERTION" in codes


def test_pass_without_seed_verification_is_weak_pass():
    doc = _base(matches_expected=True, seed_verified=False)
    g = grade(doc)
    assert g["grade"] == "Weak PASS"
    assert g["status"] == "WARN"
    codes = [f["code"] for f in g["findings"]]
    assert "PASS_WITHOUT_SEED_VERIFICATION" in codes


def test_harness_error_is_harness_fail():
    doc = _base(harness_error="reached max_turns", harness_bucket="max_turns_exhausted",
                matches_expected=False)
    g = grade(doc)
    assert g["grade"] == "Harness FAIL"
    assert g["status"] == "FAIL"


def test_timeout_bucket_is_environment_error():
    doc = _base(harness_error="No bot reply received within 30s",
                harness_bucket="bot_reply_timeout", matches_expected=False)
    g = grade(doc)
    assert g["grade"] == "Environment ERROR"
    assert g["status"] == "FAIL"
    codes = [f["code"] for f in g["findings"]]
    assert "ENVIRONMENT_ERROR" in codes


def test_plain_mismatch_is_valid_fail():
    doc = _base(matches_expected=False, decision="NOT_ELIGIBLE", expected_status="ELIGIBLE",
                dds_status=None,
                checks=[{"name": "Eligibility", "expected": "ELIGIBLE", "actual": "NOT_ELIGIBLE", "pass": False}])
    g = grade(doc)
    assert g["grade"] == "Valid FAIL"
    assert g["status"] == "FAIL"


def test_determination_gap_finding_on_valid_fail():
    doc = _base(matches_expected=False, decision="ESCALATED", expected_status="ELIGIBLE",
                dds_status="ELIGIBLE",
                checks=[{"name": "Eligibility", "expected": "ELIGIBLE", "actual": "ESCALATED", "pass": False}])
    g = grade(doc)
    assert g["grade"] == "Valid FAIL"
    codes = [f["code"] for f in g["findings"]]
    assert "DETERMINATION_IN_DDS_BUT_ESCALATED" in codes


def test_confidence_decreases_with_more_findings():
    clean = _base(matches_expected=True, seed_verified=True)
    weak = _base(matches_expected=True, seed_verified=False)
    assert grade(weak)["confidence"] < grade(clean)["confidence"]


def test_finding_shape():
    doc = _base(matches_expected=True, seed_verified=False)
    g = grade(doc)
    for f in g["findings"]:
        assert set(f.keys()) == {"level", "code", "message", "severity"}
