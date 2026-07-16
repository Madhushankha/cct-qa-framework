"""run_jira(): the implementation behind `cctqa jira <run_dir>` — grade a run's Results,
select bot-side defects, build reviewable payloads, write the review HTML, and (only with
--file) actually file them. Dry-run (nothing filed) is the default and the only mode ever
exercised by tests; filing is opt-in and never happens implicitly.
"""
from __future__ import annotations

import json
from pathlib import Path

from core.result import validate_result

from analysis.grade import grade
from jira.file import file_defects
from jira.payload import build_payload
from jira.render import render_review
from jira.select import select_defects

_DEFAULT_CONF_PATH = Path(__file__).resolve().parent / "config.example.json"


def _load_jira_conf(jira_conf_path: str | Path | None) -> dict:
    conf_path = Path(jira_conf_path) if jira_conf_path else _DEFAULT_CONF_PATH
    return json.loads(conf_path.read_text(encoding="utf-8"))


def _load_graded_results(run_dir: Path) -> list[dict]:
    graded_results = []
    for result_path in sorted(run_dir.glob("*.result.json")):
        doc = json.loads(result_path.read_text(encoding="utf-8"))
        validate_result(doc)
        graded_results.append({"result": doc, "grade": grade(doc)})
    if not graded_results:
        raise SystemExit(f"No *.result.json files found in {run_dir}")
    return graded_results


def run_jira(run_dir: str | Path, *, file: bool = False, limit: int | None = None,
             out_file: str | Path | None = None, jira_conf_path: str | Path | None = None,
             ledger_path: str | Path | None = None) -> int:
    run_dir = Path(run_dir)
    jira_conf = _load_jira_conf(jira_conf_path)

    graded_results = _load_graded_results(run_dir)
    defects = select_defects(graded_results)
    payloads = [build_payload(item["result"], item["grade"], jira_conf) for item in defects]

    out_path = Path(out_file) if out_file else run_dir / "jira" / "review.html"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(render_review(payloads), encoding="utf-8")
    print(f"wrote jira review to {out_path} ({len(payloads)} defect(s) selected)")

    resolved_ledger = Path(ledger_path) if ledger_path else run_dir / "jira" / "jira_created.json"
    outcome = file_defects(payloads, jira_conf, resolved_ledger, dry_run=not file, limit=limit)

    if file:
        print(f"filed {len(outcome['filed'])} defect(s); skipped {len(outcome['skipped'])} "
              f"(already in ledger) -> {resolved_ledger}")
    else:
        print(f"DRY RUN: would file {len(outcome['would_file'])} defect(s); "
              f"skipped {len(outcome['skipped'])} (already in ledger). Pass --file to actually file.")

    return 0
