"""Tests for analysis.rollup.rollup: pass-rate over WORKING tests only."""
from __future__ import annotations

from analysis.rollup import rollup


def _item(scenario_id, grade, status, product="bravo", env="crt", feed="fd"):
    return {
        "scenario_id": scenario_id,
        "grade": grade,
        "status": status,
        "run": {"product": product, "env": env, "feed": feed},
    }


def test_pass_rate_excludes_harness_fail_from_denominator():
    items = [
        _item("a.b.c.T1", "Strong PASS", "PASS"),
        _item("a.b.c.T2", "Valid FAIL", "FAIL"),
        _item("a.b.c.T3", "Harness FAIL", "FAIL"),
    ]

    r = rollup(items)

    totals = r["totals"]
    assert totals["total"] == 3
    assert totals["working"] == 2          # Harness FAIL excluded
    assert totals["pass"] == 1
    assert totals["fail"] == 1
    assert totals["infra"] == 1
    assert totals["pass_rate"] == 0.5


def test_environment_error_also_excluded_from_denominator():
    items = [
        _item("a.b.c.T1", "Strong PASS", "PASS"),
        _item("a.b.c.T2", "Environment ERROR", "FAIL"),
    ]

    r = rollup(items)

    assert r["totals"]["working"] == 1
    assert r["totals"]["infra"] == 1
    assert r["totals"]["pass_rate"] == 1.0


def test_invalid_pass_excluded_from_denominator_but_reported():
    items = [
        _item("a.b.c.T1", "Strong PASS", "PASS"),
        _item("a.b.c.T2", "Invalid PASS", "INVALID"),
    ]

    r = rollup(items)

    assert r["totals"]["working"] == 1
    assert r["totals"]["invalid"] == 1
    assert r["totals"]["pass_rate"] == 1.0


def test_weak_pass_counts_as_pass_in_denominator():
    items = [
        _item("a.b.c.T1", "Weak PASS", "WARN"),
        _item("a.b.c.T2", "Valid FAIL", "FAIL"),
    ]

    r = rollup(items)

    assert r["totals"]["working"] == 2
    assert r["totals"]["pass"] == 1
    assert r["totals"]["pass_rate"] == 0.5


def test_breakdown_by_product_env_feed():
    items = [
        _item("a.b.c.T1", "Strong PASS", "PASS", product="bravo", env="crt", feed="fd"),
        _item("a.b.c.T2", "Valid FAIL", "FAIL", product="bravo", env="int", feed="soc"),
    ]

    r = rollup(items)

    assert r["by_product"]["bravo"]["total"] == 2
    assert r["by_env"]["crt"]["total"] == 1
    assert r["by_env"]["int"]["total"] == 1
    assert r["by_feed"]["fd"]["pass_rate"] == 1.0
    assert r["by_feed"]["soc"]["pass_rate"] == 0.0


def test_grade_mix_counts_every_grade():
    items = [
        _item("a.b.c.T1", "Strong PASS", "PASS"),
        _item("a.b.c.T2", "Strong PASS", "PASS"),
        _item("a.b.c.T3", "Harness FAIL", "FAIL"),
    ]

    r = rollup(items)

    assert r["grade_mix"]["Strong PASS"] == 2
    assert r["grade_mix"]["Harness FAIL"] == 1


def test_empty_items_no_zero_division():
    r = rollup([])

    assert r["totals"]["total"] == 0
    assert r["totals"]["working"] == 0
    assert r["totals"]["pass_rate"] is None
