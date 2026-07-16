"""select_defects(): pick real bot-side product defects out of a graded Result batch.

Input is a list of ``{"result": <Result>, "grade": <grade dict from analysis.grade.grade>}``
(the same shape ``jira/cli.py`` assembles from a run dir). Only ``Valid FAIL`` is a real
product defect worth a ticket — ``Harness FAIL`` / ``Environment ERROR`` are infra noise, and
any PASS (Strong/Weak/Invalid) is, by definition, not a failure to file.
"""
from __future__ import annotations

_DEFECT_GRADE = "Valid FAIL"


def select_defects(graded_results: list[dict]) -> list[dict]:
    """Keep only items whose grade is 'Valid FAIL'. Preserves input order."""
    return [
        item for item in graded_results
        if (item.get("grade") or {}).get("grade") == _DEFECT_GRADE
    ]
