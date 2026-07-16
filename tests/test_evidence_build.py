"""RED-first tests for evidence.build: load every *.result.json in a run dir,
validate each against the canonical Result schema, and write the 3 evidence files.
"""
from __future__ import annotations

import json

import pytest

from core.cli import main as cli_main
from core.result import ResultError
from evidence.build import build_evidence
from tests.test_evidence_render import result_dds, result_fail, result_pass


def _write_run_dir(tmp_path, results):
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    for r in results:
        tc = r["case"]["test_case"]
        (run_dir / f"{tc}.result.json").write_text(json.dumps(r), encoding="utf-8")
    return run_dir


def test_build_evidence_writes_per_case_index_and_bot_issues(tmp_path):
    results = [result_pass(), result_fail(), result_dds()]
    run_dir = _write_run_dir(tmp_path, results)
    out_dir = tmp_path / "out"

    build_evidence(run_dir, out_dir)

    assert (out_dir / "FD_TC_001.evidence.html").exists()
    assert (out_dir / "FD_TC_002.evidence.html").exists()
    assert (out_dir / "FD_TC_003.evidence.html").exists()
    assert (out_dir / "index.html").exists()
    assert (out_dir / "bot-issues.html").exists()


def test_build_evidence_index_lists_all_three_cases(tmp_path):
    results = [result_pass(), result_fail(), result_dds()]
    run_dir = _write_run_dir(tmp_path, results)
    out_dir = tmp_path / "out"

    build_evidence(run_dir, out_dir)

    index_html = (out_dir / "index.html").read_text(encoding="utf-8")
    for tc in ("FD_TC_001", "FD_TC_002", "FD_TC_003"):
        assert tc in index_html


def test_build_evidence_ignores_non_result_files(tmp_path):
    results = [result_pass()]
    run_dir = _write_run_dir(tmp_path, results)
    (run_dir / "notes.txt").write_text("not a result", encoding="utf-8")
    out_dir = tmp_path / "out"

    build_evidence(run_dir, out_dir)  # must not raise

    assert (out_dir / "FD_TC_001.evidence.html").exists()


def test_build_evidence_validates_each_result_and_raises_on_invalid(tmp_path):
    bad = result_pass()
    del bad["verdict"]
    run_dir = _write_run_dir(tmp_path, [bad])
    out_dir = tmp_path / "out"

    with pytest.raises(ResultError):
        build_evidence(run_dir, out_dir)


def test_cli_evidence_subcommand_writes_files(tmp_path):
    run_dir = _write_run_dir(tmp_path, [result_pass()])
    out_dir = tmp_path / "out"

    rc = cli_main(["evidence", str(run_dir), "--out", str(out_dir)])

    assert rc == 0
    assert (out_dir / "index.html").exists()
    assert (out_dir / "FD_TC_001.evidence.html").exists()
