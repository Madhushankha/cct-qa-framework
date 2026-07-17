"""Tests for jira.file.file_defects: dry-run by default (files nothing, never touches the
network), resume-safe ledger dedupe, and idempotent re-runs. NEVER exercises the real POST
path — dry_run stays True throughout; that path is reference-only per the P8 spec.
"""
from __future__ import annotations

import json

from analysis.grade import grade
from jira.file import file_defects
from jira.payload import build_payload
from tests.test_jira_select import determination_gap_result


def _conf() -> dict:
    return {
        "base_url": "https://example.atlassian.net",
        "project": "CHAI", "issuetype_id": "10004", "component_id": "21829",
        "priority_id": "2", "affects_version_id": "30837",
        "cf_testing_type": "customfield_10153", "testing_type_id": "14669",
        "cf_severity": "customfield_10158", "severity_id": "10413",
    }


def _payload(pnr="HQNVYV", scenario_id="bravo.crt.fd.FD_TC_002"):
    result = determination_gap_result()
    result["case"]["pnr"] = pnr
    result["scenario_id"] = scenario_id
    return build_payload(result, grade(result), _conf())


def test_file_defects_dry_run_is_the_default_and_writes_nothing_to_the_network(tmp_path, monkeypatch):
    # A poisoned urllib.request.urlopen: if file_defects's dry-run path ever tried to hit the
    # network, this test would raise/hang instead of silently "succeeding".
    import urllib.request

    def _boom(*args, **kwargs):
        raise AssertionError("dry_run must never touch the network")

    monkeypatch.setattr(urllib.request, "urlopen", _boom)

    ledger_path = tmp_path / "jira_created.json"
    payload = _payload()

    outcome = file_defects([payload], _conf(), ledger_path)  # dry_run defaults to True

    assert outcome["dry_run"] is True
    assert outcome["would_file"] == [payload]
    assert outcome["filed"] == []
    assert outcome["skipped"] == []
    assert not ledger_path.exists()  # dry-run never writes the ledger


def test_file_defects_explicit_dry_run_true_matches_default(tmp_path):
    ledger_path = tmp_path / "jira_created.json"
    payload = _payload()

    outcome = file_defects([payload], _conf(), ledger_path, dry_run=True)

    assert outcome["would_file"] == [payload]


def test_file_defects_dedup_skips_a_key_already_in_the_ledger(tmp_path):
    payload = _payload()
    ledger_path = tmp_path / "jira_created.json"
    ledger_path.write_text(json.dumps([{"dedup_key": payload["dedup_key"], "key": "CHAI-99999"}]),
                            encoding="utf-8")

    outcome = file_defects([payload], _conf(), ledger_path, dry_run=True)

    assert outcome["would_file"] == []
    assert outcome["skipped"] == [payload["dedup_key"]]


def test_file_defects_dedup_only_skips_the_matching_key(tmp_path):
    filed_payload = _payload(pnr="HQNVYV", scenario_id="bravo.crt.fd.FD_TC_002")
    new_payload = _payload(pnr="OTHERXX", scenario_id="bravo.crt.fd.FD_TC_777")
    ledger_path = tmp_path / "jira_created.json"
    ledger_path.write_text(json.dumps([{"dedup_key": filed_payload["dedup_key"], "key": "CHAI-99999"}]),
                            encoding="utf-8")

    outcome = file_defects([filed_payload, new_payload], _conf(), ledger_path, dry_run=True)

    assert outcome["would_file"] == [new_payload]
    assert outcome["skipped"] == [filed_payload["dedup_key"]]


def test_file_defects_second_dry_run_is_idempotent(tmp_path):
    payload = _payload()
    ledger_path = tmp_path / "jira_created.json"
    ledger_path.write_text(json.dumps([]), encoding="utf-8")

    first = file_defects([payload], _conf(), ledger_path, dry_run=True)
    second = file_defects([payload], _conf(), ledger_path, dry_run=True)

    assert first == second
    assert json.loads(ledger_path.read_text(encoding="utf-8")) == []  # untouched by dry-run


def test_file_defects_respects_limit_in_dry_run(tmp_path):
    payload_a = _payload(pnr="AAAAAA", scenario_id="bravo.crt.fd.FD_TC_100")
    payload_b = _payload(pnr="BBBBBB", scenario_id="bravo.crt.fd.FD_TC_200")
    ledger_path = tmp_path / "jira_created.json"

    outcome = file_defects([payload_a, payload_b], _conf(), ledger_path, dry_run=True, limit=1)

    assert outcome["would_file"] == [payload_a]


def test_file_defects_missing_ledger_file_is_treated_as_empty(tmp_path):
    payload = _payload()
    ledger_path = tmp_path / "does_not_exist.json"

    outcome = file_defects([payload], _conf(), ledger_path, dry_run=True)

    assert outcome["skipped"] == []
    assert outcome["would_file"] == [payload]
