"""Standard local results layout for every run's outputs.

    results/<date>/<env>_<product>_<feed>_<time>/

Everything a run produces — the canonical `<TC>.result.json` files plus the derived reports
(evidence HTML, metrics.json/report.html, analysis JSON, quality HTML, jira review) — lives inside that
one run folder, so results are browsable by date, then by (env, product, feed, time). The runner writes
its Results here; the report/metrics/analysis/quality/jira commands default their output to the same
folder they read from.
"""
from __future__ import annotations

import datetime as _dt
from pathlib import Path

RESULTS_ROOT = Path("results")


def stamp(now: _dt.datetime | None = None) -> tuple[str, str]:
    """Return (date, time) strings for a run folder, e.g. ("2026-07-16", "142530").
    `now` is injectable so callers/tests can pass a fixed time (keeps things deterministic in tests)."""
    now = now or _dt.datetime.now()
    return now.strftime("%Y-%m-%d"), now.strftime("%H%M%S")


def run_dir(product: str, env: str, feed: str, date: str, time: str,
            root: str | Path = RESULTS_ROOT) -> Path:
    """The canonical run output folder: results/<date>/<feed>_<product>_<env>_<date>_<time>/.
    Feed-first and self-describing (carries date+time in the folder name), matching the seed-run
    convention runs/seed/<feed>_<product>_<env>_<date>_<time>/, so a run folder is identifiable on
    its own — one day can hold many runs."""
    return Path(root) / date / f"{feed}_{product}_{env}_{date}_{time}"


def new_run_dir(product: str, env: str, feed: str, now: _dt.datetime | None = None,
                root: str | Path = RESULTS_ROOT) -> Path:
    """Convenience: compute a fresh run folder stamped with the current (or given) time. Does not create it."""
    date, time = stamp(now)
    return run_dir(product, env, feed, date, time, root=root)
