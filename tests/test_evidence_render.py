"""RED-first tests for evidence.render: per-case HTML, expected-vs-actual index,
and grouped bot-issue cards, all built directly from the canonical Result schema.
"""
from __future__ import annotations

import re

from core.result import validate_result
from evidence.render import render_bot_issues, render_case, render_index


def _base(scenario_id, test_case, passenger, pnr, decision, matches_expected,
          dds=None, transcript=None, contact_id="c1", checks=None):
    return {
        "schema_version": "1.0",
        "scenario_id": scenario_id,
        "run": {"product": "brove", "env": "crt", "feed": "fd", "date": "2026-07-14",
                "run_id": "r1", "started": "2026-07-14T00:00:00Z", "duration_s": 12.0},
        "case": {"test_case": test_case, "pnr": pnr, "pnr_id": f"{pnr}-2026-06-15",
                 "passenger": passenger, "regime": "EU", "expected_status": "ELIGIBLE",
                 "expected_system_code": "FD-EU-EL-27",
                 "expected_amount": {"currency": "GBP", "value": 520},
                 "flags": [], "third_party": False},
        "seed": {"verified": True,
                 "checkpoints": [{"area": "eds_contact_email", "pass": True},
                                  {"area": "dds_pnr_output", "pass": dds is not None}],
                 "dds": dds},
        "auth": {"otp_fetched": True, "contact_id": contact_id},
        "verdict": {"decision": decision, "amount": {"currency": "GBP", "value": 520} if matches_expected else None,
                    "reached_determination": matches_expected,
                    "matches_expected": matches_expected,
                    "checks": checks if checks is not None else
                    [{"name": "Eligibility", "expected": "ELIGIBLE", "actual": decision,
                      "pass": matches_expected}],
                    "reasoning": "bot reasoning text"},
        "harness": {"error": None, "error_bucket": None},
        "transcript": transcript if transcript is not None else
        [{"role": "customer", "text": "hi", "ts": "t1", "note": None}],
        "evidence": {"chat_html": None, "evidence_html": None},
    }


def result_pass():
    r = _base("brove.crt.fd.FD_TC_001", "FD_TC_001", "OONA BROOKINGDALE", "GQWKRH",
               "ELIGIBLE", True,
               transcript=[
                   {"role": "customer", "text": "Hi, my flight was delayed.", "ts": "t1", "note": None},
                   {"role": "bot", "text": "You are eligible for compensation.", "ts": "t2", "note": None},
               ])
    validate_result(r)
    return r


def result_fail():
    r = _base("brove.crt.fd.FD_TC_002", "FD_TC_002", "MARCUS FENN", "HQNVYV",
               "ESCALATED", False,
               transcript=[
                   {"role": "customer", "text": "My verification code is 483920, please confirm.",
                    "ts": "t1", "note": None},
                   {"role": "bot", "text": "Routing you to an agent. Reference 654321.",
                    "ts": "t2", "note": None},
               ])
    validate_result(r)
    return r


def result_dds():
    r = _base("brove.crt.fd.FD_TC_003", "FD_TC_003", "IVY CALLOWAY", "ZFPQRS",
               "ELIGIBLE", True,
               dds={"status": "ELIGIBLE", "system_code": "FD-EU-EL-27",
                    "amount": {"currency": "GBP", "value": 520}, "trace_s3": "s3://bucket/trace.json"})
    validate_result(r)
    return r


# ---------------------------------------------------------------------------
# render_case
# ---------------------------------------------------------------------------

def test_render_case_contains_passenger_name():
    html_out = render_case(result_pass())
    assert "OONA BROOKINGDALE" in html_out


def test_render_case_masks_standalone_six_digit_otp_in_customer_turn():
    html_out = render_case(result_fail())
    assert "483920" not in html_out
    assert "••••••" in html_out


def test_render_case_does_not_mask_six_digit_number_in_bot_turn():
    html_out = render_case(result_fail())
    # Only customer turns get OTP-masked; the bot's reference number stays intact.
    assert "654321" in html_out


def test_render_case_shows_dds_system_code_as_proof():
    html_out = render_case(result_dds())
    assert "FD-EU-EL-27" in html_out
    assert "s3://bucket/trace.json" in html_out


def test_render_case_shows_verdict_and_checks_table():
    html_out = render_case(result_fail())
    assert "ESCALATED" in html_out
    assert "Eligibility" in html_out


def test_render_case_shows_seed_checkpoint_vector():
    html_out = render_case(result_pass())
    assert "eds_contact_email" in html_out


def test_render_case_is_self_contained_html():
    html_out = render_case(result_pass())
    assert "<style>" in html_out
    assert "prefers-color-scheme" in html_out
    assert "<!doctype html>" in html_out.lower()


# ---------------------------------------------------------------------------
# render_index
# ---------------------------------------------------------------------------

def test_render_index_has_exactly_one_row_per_case():
    results = [result_pass(), result_fail(), result_dds()]
    html_out = render_index(results)
    for tc in ("FD_TC_001", "FD_TC_002", "FD_TC_003"):
        assert len(re.findall(re.escape(tc), html_out)) >= 1


def test_render_index_marks_pass_and_fail_correctly():
    html_out = render_index([result_pass(), result_fail()])
    rows = html_out.split("<tr>")
    pass_row = next(r for r in rows if "FD_TC_001" in r)
    fail_row = next(r for r in rows if "FD_TC_002" in r)
    assert "PASS" in pass_row
    assert "FAIL" in fail_row
    assert "FAIL" not in pass_row
    assert "PASS" not in fail_row


def test_render_index_shows_checkpoint_pass_count():
    html_out = render_index([result_dds()])
    # 2 checkpoints seeded in _base, both pass for the dds fixture.
    assert "2/2" in html_out


# ---------------------------------------------------------------------------
# render_bot_issues
# ---------------------------------------------------------------------------

def test_render_bot_issues_groups_fails_by_decision():
    a = result_fail()
    b = _base("brove.crt.fd.FD_TC_004", "FD_TC_004", "RENA OKAFOR", "ABCDEF",
               "ESCALATED", False)
    validate_result(b)
    html_out = render_bot_issues([result_pass(), a, b])
    assert "ESCALATED" in html_out
    assert "FD_TC_002" in html_out
    assert "FD_TC_004" in html_out
    # the passing case must not appear among the failure groupings
    assert "FD_TC_001" not in html_out


def test_render_bot_issues_includes_contact_ids():
    a = result_fail()
    html_out = render_bot_issues([a])
    assert "c1" in html_out
