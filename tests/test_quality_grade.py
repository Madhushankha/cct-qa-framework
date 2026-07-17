import sys

from core.result import validate_result
from quality.grade import quality_report


def _base_result(transcript):
    return {
        "schema_version": "1.0",
        "scenario_id": "bravo.crt.fd.FD_TC_089",
        "run": {"product": "bravo", "env": "crt", "feed": "fd", "date": "2026-07-14",
                "run_id": "r1", "started": "2026-07-14T00:00:00Z", "duration_s": 42.1},
        "case": {"test_case": "FD_TC_089", "pnr": "GQWKRH", "pnr_id": "GQWKRH-2026-06-15",
                 "passenger": "OONA BROOKINGDALE", "regime": "EU", "expected_status": "ELIGIBLE",
                 "expected_system_code": "FD-EU-EL-27",
                 "expected_amount": {"currency": "GBP", "value": 520},
                 "flags": [], "third_party": False},
        "seed": {"verified": True, "checkpoints": [{"area": "eds_contact_email", "pass": True}],
                 "dds": {"status": "ELIGIBLE", "system_code": "FD-EU-EL-27",
                         "amount": {"currency": "GBP", "value": 520}, "trace_s3": "s3://x"}},
        "auth": {"otp_fetched": True, "contact_id": "c1"},
        "verdict": {"decision": "ESCALATED", "amount": None, "reached_determination": False,
                    "matches_expected": False,
                    "checks": [{"name": "Eligibility", "expected": "ELIGIBLE",
                                "actual": "ESCALATED", "pass": False}],
                    "reasoning": "bot escalated"},
        "harness": {"error": None, "error_bucket": None},
        "transcript": transcript,
        "evidence": {"chat_html": None, "evidence_html": None},
    }


def test_base_result_fixture_is_schema_valid():
    result = _base_result([{"role": "customer", "text": "hi", "ts": "t", "note": None}])
    validate_result(result)  # no raise


def test_clean_transcript_scores_high_with_no_llm_call(monkeypatch):
    def _boom(*a, **k):
        raise AssertionError("llm_judge must not be called when use_llm=False")

    monkeypatch.setattr("quality.rubric.llm_judge", _boom)

    transcript = [
        {"role": "customer", "text": "Hi, checking my delay compensation.", "ts": "t1", "note": None},
        {"role": "bot", "text": "Sure, could you share your booking reference?", "ts": "t2", "note": None},
        {"role": "customer", "text": "ABC123", "ts": "t3", "note": None},
        {"role": "bot", "text": "You're eligible for $400 CAD.", "ts": "t4", "note": None},
    ]
    result = _base_result(transcript)
    report = quality_report(result, use_llm=False)

    assert report["llm"] is None
    assert report["deterministic"] == []
    assert report["score"] >= 90
    assert report["scenario_id"] == "bravo.crt.fd.FD_TC_089"


def test_defective_transcript_scores_lower():
    dup_text = "Hello! How can I help you today?"
    transcript = [
        {"role": "customer", "text": "hi", "ts": "t1", "note": None},
        {"role": "bot", "text": dup_text, "ts": "t2", "note": None},
        {"role": "customer", "text": "help", "ts": "t3", "note": None},
        {"role": "bot", "text": dup_text, "ts": "t4", "note": None},
        {"role": "bot", "text": "Your system code is FD-APPR-EL-400.", "ts": "t5", "note": None},
    ]
    result = _base_result(transcript)
    report = quality_report(result, use_llm=False)

    assert len(report["deterministic"]) >= 2
    assert report["score"] < 90


def test_quality_report_use_llm_false_never_imports_boto3(monkeypatch):
    monkeypatch.delitem(sys.modules, "boto3", raising=False)
    result = _base_result([{"role": "bot", "text": "hi", "ts": "t", "note": None}])

    quality_report(result, use_llm=False)

    assert "boto3" not in sys.modules


def test_report_shape_has_required_keys():
    result = _base_result([{"role": "bot", "text": "hi", "ts": "t", "note": None}])
    report = quality_report(result, use_llm=False)
    assert set(["scenario_id", "deterministic", "llm", "score", "summary"]) <= set(report.keys())
