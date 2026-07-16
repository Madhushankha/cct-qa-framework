"""Tests for analysis.build.analyze: run_dir of canonical Results -> the analysis JSON
contract, and the `cctqa analyze` CLI subcommand that wraps it."""
from __future__ import annotations

import json

from core.cli import main as cli_main
from core.result import validate_result

from analysis.build import analyze


def _result(test_case, decision, matches_expected, error=None, error_bucket=None,
            expected_status="ELIGIBLE", dds_status="ELIGIBLE", date="2026-07-14"):
    doc = {
        "schema_version": "1.0",
        "scenario_id": f"brove.crt.fd.{test_case}",
        "run": {"product": "brove", "env": "crt", "feed": "fd", "date": date,
                "run_id": "r1", "started": f"{date}T00:00:00Z", "duration_s": 12.5},
        "case": {"test_case": test_case, "pnr": "GQWKRH", "pnr_id": "GQWKRH-2026-06-15",
                 "passenger": "OONA BROOKINGDALE", "regime": "EU",
                 "expected_status": expected_status, "expected_system_code": "FD-EU-EL-27",
                 "expected_amount": {"currency": "GBP", "value": 520},
                 "flags": [], "third_party": False},
        "seed": {"verified": True, "checkpoints": [{"area": "eds_contact_email", "pass": True}],
                 "dds": {"status": dds_status, "system_code": "FD-EU-EL-27",
                         "amount": {"currency": "GBP", "value": 520}, "trace_s3": "s3://x"}
                 if dds_status else None},
        "auth": {"otp_fetched": True, "contact_id": "c1"},
        "verdict": {"decision": decision, "amount": None, "reached_determination": matches_expected,
                    "matches_expected": matches_expected,
                    "checks": [{"name": "Eligibility", "expected": expected_status,
                                "actual": decision, "pass": matches_expected}],
                    "reasoning": "bot reasoning text"},
        "harness": {"error": error, "error_bucket": error_bucket},
        "transcript": [{"role": "customer", "text": "hi", "ts": "t1", "note": None}],
        "evidence": {"chat_html": None, "evidence_html": None},
    }
    validate_result(doc)
    return doc


def _write_run_dir(tmp_path, name, results):
    run_dir = tmp_path / name
    run_dir.mkdir()
    for r in results:
        tc = r["case"]["test_case"]
        (run_dir / f"{tc}.result.json").write_text(json.dumps(r), encoding="utf-8")
    return run_dir


def test_analyze_assembles_the_json_contract(tmp_path):
    run_dir = _write_run_dir(tmp_path, "run", [
        _result("FD_TC_001", "ELIGIBLE", True),
        _result("FD_TC_002", "NOT_ELIGIBLE", False, expected_status="ELIGIBLE", dds_status=None),
    ])

    doc = analyze(run_dir)

    for key in ("summary", "grades", "findings", "clusters"):
        assert key in doc
    assert "diff" not in doc
    assert doc["summary"]["totals"]["total"] == 2
    assert len(doc["grades"]) == 2


def test_analyze_with_prev_dir_adds_diff(tmp_path):
    prev_dir = _write_run_dir(tmp_path, "prev", [_result("FD_TC_001", "ELIGIBLE", True)])
    curr_dir = _write_run_dir(tmp_path, "curr", [_result("FD_TC_001", "NOT_ELIGIBLE", False,
                                                          dds_status=None)])

    doc = analyze(curr_dir, prev_dir=prev_dir)

    assert doc["diff"]["newly_failing"] == ["brove.crt.fd.FD_TC_001"]


def test_analyze_raises_systemexit_when_no_results(tmp_path):
    run_dir = tmp_path / "empty"
    run_dir.mkdir()

    try:
        analyze(run_dir)
        assert False, "expected SystemExit"
    except SystemExit:
        pass


def test_cli_analyze_subcommand_writes_default_output(tmp_path):
    run_dir = _write_run_dir(tmp_path, "run", [_result("FD_TC_001", "ELIGIBLE", True)])

    rc = cli_main(["analyze", str(run_dir)])

    assert rc == 0
    out_path = run_dir / "analysis" / "analysis.json"
    assert out_path.exists()
    doc = json.loads(out_path.read_text(encoding="utf-8"))
    assert doc["summary"]["totals"]["total"] == 1


def test_cli_analyze_subcommand_with_prev_and_custom_out(tmp_path):
    prev_dir = _write_run_dir(tmp_path, "prev", [_result("FD_TC_001", "ELIGIBLE", True)])
    curr_dir = _write_run_dir(tmp_path, "curr", [_result("FD_TC_001", "NOT_ELIGIBLE", False,
                                                          dds_status=None)])
    out_file = tmp_path / "out" / "custom.json"

    rc = cli_main(["analyze", str(curr_dir), "--prev", str(prev_dir), "--out", str(out_file)])

    assert rc == 0
    doc = json.loads(out_file.read_text(encoding="utf-8"))
    assert doc["diff"]["newly_failing"] == ["brove.crt.fd.FD_TC_001"]


def test_cli_analyze_subcommand_returns_nonzero_on_no_results(tmp_path):
    run_dir = tmp_path / "empty"
    run_dir.mkdir()

    rc = cli_main(["analyze", str(run_dir)])

    assert rc != 0
