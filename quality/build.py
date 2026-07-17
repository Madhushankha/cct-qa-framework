"""Build the quality package for a run: load every ``*.result.json`` in ``run_dir``,
validate each against the canonical Result schema (P0), grade it for response QUALITY
(deterministic + optional LLM judge), and write ``<test_case>.quality.html`` +
``quality-index.html`` into ``out_dir``. (``index.html`` belongs exclusively to the
evidence Expected-vs-Actual report.)
"""
from __future__ import annotations

import json
from pathlib import Path

from core.result import validate_result

from quality.grade import quality_report
from quality.render import render_quality, render_quality_index


def build_quality(run_dir: str | Path, out_dir: str | Path, use_llm: bool = False) -> None:
    run_dir = Path(run_dir)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    reports = []
    for result_path in sorted(run_dir.glob("*.result.json")):
        doc = json.loads(result_path.read_text(encoding="utf-8"))
        validate_result(doc)
        report = quality_report(doc, use_llm=use_llm)
        reports.append(report)

        test_case = report.get("test_case") or doc["case"]["test_case"]
        out_path = out_dir / f"{test_case}.quality.html"
        out_path.write_text(render_quality(report), encoding="utf-8")

    (out_dir / "quality-index.html").write_text(render_quality_index(reports), encoding="utf-8")
