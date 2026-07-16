"""Tests for analysis.diff.run_diff: previous vs current terminal outcome per scenario_id."""
from __future__ import annotations

from analysis.diff import run_diff


def _item(scenario_id, status):
    return {"scenario_id": scenario_id, "status": status}


def test_flip_pass_to_fail_is_newly_failing():
    prev = [_item("a.b.c.T1", "PASS")]
    curr = [_item("a.b.c.T1", "FAIL")]

    d = run_diff(prev, curr)

    assert d["newly_failing"] == ["a.b.c.T1"]
    assert d["newly_passing"] == []
    assert d["still_failing"] == []
    assert d["still_passing"] == []


def test_flip_fail_to_pass_is_newly_passing():
    prev = [_item("a.b.c.T2", "FAIL")]
    curr = [_item("a.b.c.T2", "PASS")]

    d = run_diff(prev, curr)

    assert d["newly_passing"] == ["a.b.c.T2"]


def test_still_failing_and_still_passing():
    prev = [_item("a.b.c.T3", "FAIL"), _item("a.b.c.T4", "PASS")]
    curr = [_item("a.b.c.T3", "FAIL"), _item("a.b.c.T4", "PASS")]

    d = run_diff(prev, curr)

    assert d["still_failing"] == ["a.b.c.T3"]
    assert d["still_passing"] == ["a.b.c.T4"]


def test_non_binary_statuses_excluded_from_baseline():
    prev = [_item("a.b.c.T5", "INVALID")]
    curr = [_item("a.b.c.T5", "FAIL")]

    d = run_diff(prev, curr)

    # no prior PASS/FAIL baseline -> not classified into any bucket
    assert "a.b.c.T5" not in d["newly_failing"]
    assert "a.b.c.T5" not in d["newly_passing"]
    assert "a.b.c.T5" not in d["still_failing"]
    assert "a.b.c.T5" not in d["still_passing"]


def test_scenario_only_in_current_is_ignored_no_baseline():
    prev = []
    curr = [_item("a.b.c.NEW", "FAIL")]

    d = run_diff(prev, curr)

    for bucket in d.values():
        assert "a.b.c.NEW" not in bucket


def test_result_is_deterministic_sorted():
    prev = [_item("a.b.c.T2", "PASS"), _item("a.b.c.T1", "PASS")]
    curr = [_item("a.b.c.T2", "FAIL"), _item("a.b.c.T1", "FAIL")]

    d = run_diff(prev, curr)

    assert d["newly_failing"] == ["a.b.c.T1", "a.b.c.T2"]
