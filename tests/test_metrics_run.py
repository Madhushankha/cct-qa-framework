"""Tests for metrics.run.build_metrics: canonical Result set (P0) in a run dir ->
evalkit metrics.json + report.html, via the metrics/adapter.py integration seam.
"""
from __future__ import annotations

import json

from core.cli import main as cli_main
from core.result import validate_result
from metrics.run import build_metrics


def _base(test_case, system_code, regime, expected_status, expected_amount,
          decision, matches_expected, actual_amount=None, error=None):
    return {
        "schema_version": "1.0",
        "scenario_id": f"brove.crt.fd.{test_case}",
        "run": {"product": "brove", "env": "crt", "feed": "fd", "date": "2026-07-14",
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
        "auth": {"otp_fetched": True, "contact_id": "c1"},
        "verdict": {"decision": decision, "amount": actual_amount,
                    "reached_determination": matches_expected,
                    "matches_expected": matches_expected,
                    "checks": [{"name": "Eligibility status", "expected": expected_status,
                                "actual": decision, "pass": matches_expected}],
                    "reasoning": "bot reasoning text"},
        "harness": {"error": error, "error_bucket": None},
        "transcript": [{"role": "customer", "text": "hi", "ts": "t1", "note": None}],
        "evidence": {"chat_html": None, "evidence_html": None},
    }


def result_pass():
    r = _base("FD_TC_001", "FD-EU-EL-27", "EU", "ELIGIBLE",
               {"currency": "GBP", "value": 520.0}, "ELIGIBLE", True,
               actual_amount={"currency": "GBP", "value": 520.0})
    validate_result(r)
    return r


def result_fail():
    r = _base("FD_TC_002", "FD-APPR-NE-03", "APPR", "NOT_ELIGIBLE", None,
               "ESCALATED", False, error="No bot reply received within 30s")
    validate_result(r)
    return r


def _write_run_dir(tmp_path, results):
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    for r in results:
        tc = r["case"]["test_case"]
        (run_dir / f"{tc}.result.json").write_text(json.dumps(r), encoding="utf-8")
    return run_dir


def test_build_metrics_writes_metrics_json_and_report_html(tmp_path):
    run_dir = _write_run_dir(tmp_path, [result_pass(), result_fail()])
    out_dir = tmp_path / "out"

    metrics_path = build_metrics(run_dir, out_dir)

    assert metrics_path == out_dir / "metrics.json"
    assert metrics_path.exists()
    assert (out_dir / "report.html").exists()


def test_build_metrics_json_has_schema_version_and_headline_metrics(tmp_path):
    run_dir = _write_run_dir(tmp_path, [result_pass(), result_fail()])
    out_dir = tmp_path / "out"

    build_metrics(run_dir, out_dir)
    m = json.loads((out_dir / "metrics.json").read_text(encoding="utf-8"))

    assert m["schema_version"]
    assert m["n_cases"] == 2
    assert m["agent"] == "brove"
    assert m["env"] == "crt"
    for top_key in ("headline", "confusion", "checks", "slices", "trajectory", "ops", "cases"):
        assert top_key in m

    headline = m["headline"]
    for key in ("goal_success_rate", "rescored_success_rate", "judge_agreement",
                "clean_run_rate", "terminal_decision_rate", "decision_accuracy",
                "amount_accuracy", "intent_recognition_rate", "trajectory_match_mean"):
        assert key in headline

    assert headline["goal_success_rate"]["num"] == 1
    assert headline["goal_success_rate"]["den"] == 2
    assert headline["decision_accuracy"]["num"] == 1


def test_build_metrics_report_html_is_self_contained(tmp_path):
    run_dir = _write_run_dir(tmp_path, [result_pass()])
    out_dir = tmp_path / "out"

    build_metrics(run_dir, out_dir)
    html = (out_dir / "report.html").read_text(encoding="utf-8")

    assert "<!doctype html>" in html.lower()
    assert "FD_TC_001" in html


def test_build_metrics_raises_systemexit_when_no_results(tmp_path):
    run_dir = tmp_path / "empty"
    run_dir.mkdir()
    out_dir = tmp_path / "out"

    try:
        build_metrics(run_dir, out_dir)
        assert False, "expected SystemExit"
    except SystemExit:
        pass


def test_cli_metrics_subcommand_writes_files(tmp_path):
    run_dir = _write_run_dir(tmp_path, [result_pass(), result_fail()])
    out_dir = tmp_path / "out"

    rc = cli_main(["metrics", str(run_dir), "--out", str(out_dir)])

    assert rc == 0
    assert (out_dir / "metrics.json").exists()
    assert (out_dir / "report.html").exists()


def test_cli_metrics_subcommand_defaults_out_to_run_dir_metrics(tmp_path):
    run_dir = _write_run_dir(tmp_path, [result_pass()])

    rc = cli_main(["metrics", str(run_dir)])

    assert rc == 0
    assert (run_dir / "metrics" / "metrics.json").exists()


def test_cli_metrics_subcommand_returns_nonzero_on_no_results(tmp_path):
    run_dir = tmp_path / "empty"
    run_dir.mkdir()

    rc = cli_main(["metrics", str(run_dir)])

    assert rc != 0
