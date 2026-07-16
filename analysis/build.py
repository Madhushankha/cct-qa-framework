"""analyze(): canonical Result set (P0) in a run dir -> the analysis JSON contract that the
UI (P7) renders: {summary, grades, findings, clusters, diff}.

    from analysis.build import analyze
    doc = analyze("out/some_run")
    doc = analyze("out/some_run", prev_dir="out/prev_run")   # adds run-over-run diff

Loads every ``*.result.json`` in run_dir, validates each against the canonical Result schema
(P0), grades it (analysis.grade), then rolls up / clusters / counts findings across the batch.
When prev_dir is given, the previous run is loaded + graded the same way and diffed
(analysis.diff) against the current one.
"""
from __future__ import annotations

import json
from pathlib import Path

from core.result import validate_result

from analysis.cluster import finding_counts, reason_clusters
from analysis.diff import run_diff
from analysis.grade import grade
from analysis.rollup import rollup


def _one_line_reason(doc: dict, graded: dict) -> str:
    """A stable, coarse one-liner used for clustering — deliberately not free-text
    reasoning (which is near-unique per case); grouped on grade + decision vs expectation."""
    verdict = doc.get("verdict") or {}
    case = doc.get("case") or {}
    return (
        f"{graded['grade']} | decision={verdict.get('decision')} "
        f"vs expected={case.get('expected_status')}"
    )


def _load_and_grade(run_dir: Path) -> list[dict]:
    items = []
    for result_path in sorted(run_dir.glob("*.result.json")):
        doc = json.loads(result_path.read_text(encoding="utf-8"))
        validate_result(doc)
        g = grade(doc)
        items.append({
            "scenario_id": doc["scenario_id"],
            "run": doc["run"],
            "grade": g["grade"],
            "status": g["status"],
            "confidence": g["confidence"],
            "findings": g["findings"],
            "reason": _one_line_reason(doc, g),
        })

    if not items:
        raise SystemExit(f"No *.result.json files found in {run_dir}")

    return items


def analyze(run_dir: str | Path, prev_dir: str | Path | None = None) -> dict:
    run_dir = Path(run_dir)
    items = _load_and_grade(run_dir)

    doc = {
        "summary": rollup(items),
        "grades": [
            {
                "scenario_id": i["scenario_id"],
                "run": i["run"],
                "grade": i["grade"],
                "status": i["status"],
                "confidence": i["confidence"],
            }
            for i in items
        ],
        "findings": finding_counts(items),
        "clusters": reason_clusters(items),
    }

    if prev_dir is not None:
        prev_items = _load_and_grade(Path(prev_dir))
        doc["diff"] = run_diff(prev_items, items)

    return doc
