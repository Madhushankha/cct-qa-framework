"""Build evalkit's metrics.json + report.html for one run's canonical Result set.

    from metrics.run import build_metrics
    build_metrics("out/some_run", "out/some_run/metrics")

Loads every ``*.result.json`` in ``run_dir``, validates each against the canonical
Result schema (P0), maps it to evalkit's normalized EvalRecord via
``metrics.adapter.result_to_record``, then reuses evalkit's own deterministic
metrics/report engine unchanged — this file is the only integration glue.
"""
from __future__ import annotations

import json
from pathlib import Path

from core.result import validate_result

from metrics.adapter import render_transcript_md, result_to_record
from metrics.evalkit import taxonomy
from metrics.evalkit.metrics import compute_metrics
from metrics.evalkit.report import render_report, write_json
from metrics.evalkit.trajectory import annotate_trajectory

_DIALECTS = ("bravo", "alpha")


def _detect_dialect(records: list) -> str:
    """Pick the transcript dialect whose stage detectors hit the most canonical stages across the run.
    Ties break toward the first in `_DIALECTS`. Records are left re-rendered; the caller re-annotates
    with the winner so every record ends up on the same dialect."""
    best_fmt, best_hits = _DIALECTS[0], -1
    for fmt in _DIALECTS:
        hits = 0
        for r in records:
            r["transcript_text"] = render_transcript_md(r.get("transcript_raw"), fmt)
            annotate_trajectory(r, fmt=fmt)
            hits += len((r.get("trajectory") or {}).get("stages_hit") or [])
        if hits > best_hits:
            best_fmt, best_hits = fmt, hits
    return best_fmt


def build_metrics(run_dir: str | Path, out_dir: str | Path) -> Path:
    run_dir = Path(run_dir)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    records = []
    for result_path in sorted(run_dir.glob("*.result.json")):
        doc = json.loads(result_path.read_text(encoding="utf-8"))
        validate_result(doc)
        records.append(result_to_record(doc))

    if not records:
        raise SystemExit(f"No *.result.json files found in {run_dir}")

    for r in records:
        bucket, fatal = taxonomy.bucket_error(r["run_error"])
        r["error_bucket"], r["error_fatal"] = bucket, fatal

    # Auto-detect the bot's transcript dialect: render each record in a dialect, run the stage
    # detectors, and keep whichever dialect hits the most canonical stages across the run. The bot has
    # moved from the `alpha` wording to the `bravo` wording (greeting "How can I help you today?", OTP
    # "I've sent a verification code", "§W§INFO§FEEDBACK"), so hardcoding alpha left most flow stages at
    # 0%. Detection makes the trajectory correct regardless of which wording a run used.
    fmt = _detect_dialect(records)
    for r in records:
        r["transcript_text"] = render_transcript_md(r.get("transcript_raw"), fmt)
        annotate_trajectory(r, fmt=fmt)

    m = compute_metrics(records)

    metrics_path = out_dir / "metrics.json"
    write_json(metrics_path, m)

    html = render_report(m, taxonomy.STAGE_ORDER, taxonomy.STAGE_LABELS, taxonomy.ANOMALY_LABELS,
                          source_dir=str(run_dir))
    (out_dir / "report.html").write_text(html, encoding="utf-8")

    return metrics_path
