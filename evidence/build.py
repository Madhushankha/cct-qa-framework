"""Build the evidence HTML package for a run: load every ``*.result.json`` in
``run_dir``, validate each against the canonical Result schema (P0), and write
``<test_case>.evidence.html`` + ``index.html`` + ``bot-issues.html`` into ``out_dir``.
"""
from __future__ import annotations

import json
from pathlib import Path

from core.result import validate_result

from evidence.render import render_bot_issues, render_case, render_index


def build_evidence(run_dir: str | Path, out_dir: str | Path) -> None:
    run_dir = Path(run_dir)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    results = []
    for result_path in sorted(run_dir.glob("*.result.json")):
        doc = json.loads(result_path.read_text(encoding="utf-8"))
        validate_result(doc)
        results.append(doc)

    for doc in results:
        test_case = doc["case"]["test_case"]
        out_path = out_dir / f"{test_case}.evidence.html"
        out_path.write_text(render_case(doc), encoding="utf-8")

    (out_dir / "index.html").write_text(render_index(results), encoding="utf-8")
    (out_dir / "bot-issues.html").write_text(render_bot_issues(results), encoding="utf-8")
