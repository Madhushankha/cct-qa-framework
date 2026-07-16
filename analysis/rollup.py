"""rollup(): pass-rate over WORKING tests only, broken down by product/env/feed + grade mix.

Cascade convention (docs/context.md §4.3): pass-rate is computed over PASS+FAIL "working"
tests only. Harness FAIL / Environment ERROR are infra noise and are excluded from the
denominator (reported separately as `infra`); Invalid PASS is compromised evidence and is
also excluded from the denominator (reported separately as `invalid`) — it is neither a
trustworthy pass nor a fail. Weak PASS (status WARN) still counts as a pass: the outcome
matched expectations, the evidence is just thinner.
"""
from __future__ import annotations

from collections import Counter

_INFRA_GRADES = {"Harness FAIL", "Environment ERROR"}
_INVALID_GRADES = {"Invalid PASS"}
_PASS_STATUSES = {"PASS", "WARN"}


def _bucket_stats(items: list[dict]) -> dict:
    total = len(items)
    infra = [i for i in items if i.get("grade") in _INFRA_GRADES]
    invalid = [i for i in items if i.get("grade") in _INVALID_GRADES]
    working = [i for i in items if i.get("grade") not in _INFRA_GRADES and i.get("grade") not in _INVALID_GRADES]
    passes = [i for i in working if i.get("status") in _PASS_STATUSES]
    fails = [i for i in working if i.get("status") == "FAIL"]

    pass_rate = (len(passes) / len(working)) if working else None

    return {
        "total": total,
        "working": len(working),
        "pass": len(passes),
        "fail": len(fails),
        "invalid": len(invalid),
        "infra": len(infra),
        "pass_rate": pass_rate,
    }


def _breakdown(items: list[dict], axis: str) -> dict:
    groups: dict[str, list[dict]] = {}
    for i in items:
        key = (i.get("run") or {}).get(axis)
        if key is None:
            continue
        groups.setdefault(key, []).append(i)
    return {key: _bucket_stats(group) for key, group in sorted(groups.items())}


def rollup(items: list[dict]) -> dict:
    """items: graded items, each {"scenario_id", "grade", "status", "run": {"product","env","feed"}}."""
    grade_mix = dict(sorted(Counter(i.get("grade") for i in items).items()))

    return {
        "totals": _bucket_stats(items),
        "grade_mix": grade_mix,
        "by_product": _breakdown(items, "product"),
        "by_env": _breakdown(items, "env"),
        "by_feed": _breakdown(items, "feed"),
    }
