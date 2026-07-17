"""Tests for jira.payload.build_payload: canonical Result + grade + jira_conf -> a reviewable
JIRA bug payload {"fields", "description_wiki", "dedup_key", ...}."""
from __future__ import annotations

import json
from pathlib import Path

from analysis.grade import grade
from jira.payload import build_payload
from tests.test_jira_select import determination_gap_result, pass_result

_CONF_PATH = Path(__file__).resolve().parent.parent / "jira" / "config.example.json"


def _conf(**overrides) -> dict:
    conf = json.loads(_CONF_PATH.read_text(encoding="utf-8"))
    conf.update(overrides)
    return conf


def test_build_payload_returns_the_required_keys():
    result = determination_gap_result()
    g = grade(result)

    payload = build_payload(result, g, _conf())

    assert "fields" in payload
    assert "description_wiki" in payload
    assert "dedup_key" in payload
    assert isinstance(payload["fields"], dict)
    assert isinstance(payload["description_wiki"], str)
    assert isinstance(payload["dedup_key"], str)


def test_description_wiki_contains_system_code_escalated_and_contact_id():
    result = determination_gap_result()
    g = grade(result)

    payload = build_payload(result, g, _conf())
    desc = payload["description_wiki"]

    assert "FD-EU-EL-27" in desc          # expected_system_code
    assert "ESCALATED" in desc            # actual bot decision
    assert "c1" in desc                   # ContactId


def test_description_wiki_includes_dds_determination_proof():
    result = determination_gap_result()
    g = grade(result)

    desc = build_payload(result, g, _conf())["description_wiki"]

    assert "ELIGIBLE" in desc             # DDS status on file
    assert "determination on file" in desc


def test_description_wiki_includes_grade_findings():
    result = determination_gap_result()
    g = grade(result)

    desc = build_payload(result, g, _conf())["description_wiki"]

    assert "DETERMINATION_IN_DDS_BUT_ESCALATED" in desc


def test_dedup_key_is_stable_across_calls():
    result = determination_gap_result()
    g = grade(result)

    key1 = build_payload(result, g, _conf())["dedup_key"]
    key2 = build_payload(determination_gap_result(), grade(determination_gap_result()), _conf())["dedup_key"]

    assert key1 == key2
    assert key1  # non-empty


def test_dedup_key_differs_for_a_different_pnr():
    result_a = determination_gap_result()
    result_b = determination_gap_result()
    result_b["case"]["pnr"] = "OTHERX"
    result_b["scenario_id"] = "bravo.crt.fd.FD_TC_099"

    key_a = build_payload(result_a, grade(result_a), _conf())["dedup_key"]
    key_b = build_payload(result_b, grade(result_b), _conf())["dedup_key"]

    assert key_a != key_b


def test_fields_use_ids_from_jira_conf_not_hardcoded():
    result = determination_gap_result()
    g = grade(result)
    conf = _conf(project="ZZZ", issuetype_id="99999", component_id="88888",
                 priority_id="7", affects_version_id="66666",
                 cf_testing_type="customfield_1", testing_type_id="1",
                 cf_severity="customfield_2", severity_id="2")

    fields = build_payload(result, g, conf)["fields"]

    assert fields["project"] == {"key": "ZZZ"}
    assert fields["issuetype"] == {"id": "99999"}
    assert fields["components"] == [{"id": "88888"}]
    assert fields["priority"] == {"id": "7"}
    assert fields["versions"] == [{"id": "66666"}]
    assert fields["customfield_1"] == {"id": "1"}
    assert fields["customfield_2"] == {"id": "2"}


def test_build_payload_works_for_a_pass_result_too_selection_is_the_caller_responsibility():
    # build_payload itself doesn't gate on grade — jira.select does that before this is called.
    result = pass_result()
    g = grade(result)

    payload = build_payload(result, g, _conf())

    assert payload["dedup_key"]
    assert "fields" in payload
