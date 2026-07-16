"""Tests for the `cctqa jira` CLI subcommand (jira.cli.run_jira wired into core.cli.main).
Dry-run only — filing must NEVER happen by default, and these tests must never touch the
network (poisoned urlopen would raise instead of silently succeeding if they did)."""
from __future__ import annotations

import json

import pytest

from core.cli import main as cli_main
from tests.test_jira_select import determination_gap_result, harness_fail_result, pass_result


def _write_run_dir(tmp_path, results):
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    for r in results:
        tc = r["case"]["test_case"]
        (run_dir / f"{tc}.result.json").write_text(json.dumps(r), encoding="utf-8")
    return run_dir


@pytest.fixture(autouse=True)
def _poison_network(monkeypatch):
    import urllib.request

    def _boom(*args, **kwargs):
        raise AssertionError("cctqa jira must never touch the network without --file")

    monkeypatch.setattr(urllib.request, "urlopen", _boom)


def test_cli_jira_dry_run_writes_review_and_no_ledger(tmp_path):
    run_dir = _write_run_dir(tmp_path, [determination_gap_result(), pass_result(), harness_fail_result()])

    rc = cli_main(["jira", str(run_dir)])

    assert rc == 0
    review = run_dir / "jira" / "review.html"
    assert review.exists()
    assert "ESCALATED" in review.read_text(encoding="utf-8")
    assert not (run_dir / "jira" / "jira_created.json").exists()


def test_cli_jira_custom_out_path(tmp_path):
    run_dir = _write_run_dir(tmp_path, [determination_gap_result()])
    out_file = tmp_path / "custom" / "review.html"

    rc = cli_main(["jira", str(run_dir), "--out", str(out_file)])

    assert rc == 0
    assert out_file.exists()


def test_cli_jira_only_selects_valid_fail_defects(tmp_path):
    run_dir = _write_run_dir(tmp_path, [pass_result(), harness_fail_result()])

    rc = cli_main(["jira", str(run_dir)])

    assert rc == 0
    review_html = (run_dir / "jira" / "review.html").read_text(encoding="utf-8")
    assert "No defects selected" in review_html


def test_cli_jira_returns_nonzero_on_no_results(tmp_path):
    run_dir = tmp_path / "empty"
    run_dir.mkdir()

    rc = cli_main(["jira", str(run_dir)])

    assert rc != 0
