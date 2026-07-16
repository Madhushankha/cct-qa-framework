"""run_diff(): run-over-run scenario diff — the piece cct-cascade lacks (docs/context.md §4.8).

Compares each scenario's terminal PASS/FAIL outcome between a previous and a current graded
run, keyed by scenario_id, and buckets the result into newly_failing / newly_passing /
still_failing / still_passing. WARN (Weak PASS) and INVALID (Invalid PASS) statuses are
ambiguous evidence-wise and are excluded from both sides of the comparison — a scenario
needs a PASS/FAIL baseline on *both* sides to be classified.
"""
from __future__ import annotations

_TERMINAL_STATUSES = ("PASS", "FAIL")


def _status_map(items: list[dict]) -> dict[str, str]:
    return {
        i["scenario_id"]: i["status"]
        for i in items
        if i.get("status") in _TERMINAL_STATUSES
    }


def run_diff(prev: list[dict], curr: list[dict]) -> dict:
    """prev/curr: lists of graded items, each with at least {"scenario_id", "status"}.

    Returns {"newly_failing": [...], "newly_passing": [...], "still_failing": [...],
    "still_passing": [...]} — each a sorted list of scenario_id, deterministic across runs.
    """
    prev_map = _status_map(prev)
    curr_map = _status_map(curr)

    newly_failing, newly_passing, still_failing, still_passing = [], [], [], []

    for scenario_id, cur_status in curr_map.items():
        prev_status = prev_map.get(scenario_id)
        if prev_status is None:
            continue  # no PASS/FAIL baseline for this scenario — not diffable
        if prev_status == "PASS" and cur_status == "FAIL":
            newly_failing.append(scenario_id)
        elif prev_status == "FAIL" and cur_status == "PASS":
            newly_passing.append(scenario_id)
        elif prev_status == "FAIL" and cur_status == "FAIL":
            still_failing.append(scenario_id)
        elif prev_status == "PASS" and cur_status == "PASS":
            still_passing.append(scenario_id)

    return {
        "newly_failing": sorted(newly_failing),
        "newly_passing": sorted(newly_passing),
        "still_failing": sorted(still_failing),
        "still_passing": sorted(still_passing),
    }
