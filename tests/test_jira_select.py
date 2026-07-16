"""Tests for jira.select: keep only 'Valid FAIL' (real bot-side product defects) out of a
graded batch, excluding any PASS and excluding Harness FAIL / Environment ERROR (infra noise).

Also defines the shared Result builders reused by test_jira_payload.py and test_jira_file.py,
mirroring the existing tests/test_evidence_render.py -> tests/test_evidence_build.py convention.
"""
from __future__ import annotations

from core.result import validate_result

from analysis.grade import grade
from jira.select import select_defects


def _base(scenario_id, test_case, pnr, decision, matches_expected, *,
          expected_status="ELIGIBLE", dds_status="ELIGIBLE", contact_id="c1",
          harness_error=None, harness_bucket=None, checks=None):
    checks = checks if checks is not None else [
        {"name": "Eligibility", "expected": expected_status, "actual": decision, "pass": matches_expected}
    ]
    doc = {
        "schema_version": "1.0",
        "scenario_id": scenario_id,
        "run": {"product": "brove", "env": "crt", "feed": "fd", "date": "2026-07-14",
                "run_id": "r1", "started": "2026-07-14T00:00:00Z", "duration_s": 12.5},
        "case": {"test_case": test_case, "pnr": pnr, "pnr_id": f"{pnr}-2026-06-15",
                 "passenger": "OONA BROOKINGDALE", "regime": "EU",
                 "expected_status": expected_status, "expected_system_code": "FD-EU-EL-27",
                 "expected_amount": {"currency": "GBP", "value": 520},
                 "flags": [], "third_party": False},
        "seed": {"verified": True, "checkpoints": [{"area": "eds_contact_email", "pass": True}],
                 "dds": {"status": dds_status, "system_code": "FD-EU-EL-27",
                         "amount": {"currency": "GBP", "value": 520}, "trace_s3": "s3://bucket/trace.json"}
                 if dds_status is not None else None},
        "auth": {"otp_fetched": True, "contact_id": contact_id},
        "verdict": {"decision": decision, "amount": None, "reached_determination": matches_expected,
                    "matches_expected": matches_expected, "checks": checks,
                    "reasoning": "bot reasoning text"},
        "harness": {"error": harness_error, "error_bucket": harness_bucket},
        "transcript": [
            {"role": "customer", "text": "My flight was delayed, my code is 483920.", "ts": "t1", "note": None},
            {"role": "bot", "text": f"Result: {decision}", "ts": "t2", "note": None},
        ],
        "evidence": {"chat_html": None, "evidence_html": None},
    }
    validate_result(doc)
    return doc


def determination_gap_result():
    """A Valid FAIL where DDS already reached an eligible-shaped verdict but the bot
    escalated — the recurring determination-gap defect this package exists to file."""
    return _base("brove.crt.fd.FD_TC_002", "FD_TC_002", "HQNVYV", "ESCALATED", False,
                 expected_status="ELIGIBLE", dds_status="ELIGIBLE")


def pass_result():
    return _base("brove.crt.fd.FD_TC_001", "FD_TC_001", "GQWKRH", "ELIGIBLE", True,
                 expected_status="ELIGIBLE", dds_status="ELIGIBLE")


def harness_fail_result():
    return _base("brove.crt.fd.FD_TC_003", "FD_TC_003", "ABCDEF", "NO_DETERMINATION", False,
                 expected_status="ELIGIBLE", dds_status=None,
                 harness_error="reached max_turns", harness_bucket="max_turns_exhausted")


def environment_error_result():
    return _base("brove.crt.fd.FD_TC_004", "FD_TC_004", "ZFPQRS", "NO_DETERMINATION", False,
                 expected_status="ELIGIBLE", dds_status=None,
                 harness_error="No bot reply received within 30s", harness_bucket="bot_reply_timeout")


def _graded(result):
    return {"result": result, "grade": grade(result)}


def test_select_keeps_valid_fail_determination_gap_result():
    item = _graded(determination_gap_result())

    selected = select_defects([item])

    assert selected == [item]
    assert selected[0]["grade"]["grade"] == "Valid FAIL"


def test_select_drops_pass():
    item = _graded(pass_result())

    selected = select_defects([item])

    assert selected == []


def test_select_drops_harness_fail():
    item = _graded(harness_fail_result())

    assert item["grade"]["grade"] == "Harness FAIL"
    selected = select_defects([item])

    assert selected == []


def test_select_drops_environment_error():
    item = _graded(environment_error_result())

    assert item["grade"]["grade"] == "Environment ERROR"
    selected = select_defects([item])

    assert selected == []


def test_select_keeps_only_the_valid_fail_out_of_a_mixed_batch():
    gap = _graded(determination_gap_result())
    items = [_graded(pass_result()), gap, _graded(harness_fail_result()),
             _graded(environment_error_result())]

    selected = select_defects(items)

    assert selected == [gap]


def test_select_returns_empty_list_for_empty_input():
    assert select_defects([]) == []
