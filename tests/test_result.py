import json
from pathlib import Path
import pytest
from core.result import validate_result, write_result, ResultError, RESULT_SCHEMA_VERSION


def _good_result():
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
        "transcript": [{"role": "customer", "text": "hi", "ts": "t", "note": None}],
        "evidence": {"chat_html": None, "evidence_html": None},
    }


def test_schema_version_constant():
    assert RESULT_SCHEMA_VERSION == "1.0"


def test_good_result_validates():
    validate_result(_good_result())  # no raise


def test_missing_required_top_key_fails():
    d = _good_result()
    del d["verdict"]
    with pytest.raises(ResultError) as exc:
        validate_result(d)
    assert "verdict" in str(exc.value)


def test_wrong_schema_version_fails():
    d = _good_result()
    d["schema_version"] = "9.9"
    with pytest.raises(ResultError):
        validate_result(d)


def test_write_result_roundtrip(tmp_path):
    out = tmp_path / "r.json"
    write_result(_good_result(), out)
    reloaded = json.loads(out.read_text(encoding="utf-8"))
    assert reloaded["scenario_id"] == "bravo.crt.fd.FD_TC_089"
