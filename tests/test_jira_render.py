"""Tests for jira.render: the pre-filing review page and the recreate-comment workflow."""
from __future__ import annotations

from analysis.grade import grade
from jira.payload import build_payload
from jira.render import render_recreate_comment, render_review
from tests.test_jira_select import determination_gap_result


def _conf() -> dict:
    return {
        "project": "CHAI", "issuetype_id": "10004", "component_id": "21829",
        "priority_id": "2", "affects_version_id": "30837",
        "cf_testing_type": "customfield_10153", "testing_type_id": "14669",
        "cf_severity": "customfield_10158", "severity_id": "10413",
    }


def test_render_review_lists_every_payload():
    result = determination_gap_result()
    payload = build_payload(result, grade(result), _conf())

    html_out = render_review([payload])

    assert payload["dedup_key"] in html_out
    assert "ESCALATED" in html_out
    assert "<!doctype html>" in html_out.lower()


def test_render_review_handles_no_payloads():
    html_out = render_review([])
    assert "No defects selected" in html_out


def test_render_recreate_comment_returns_chat_html_and_comment_text():
    result = determination_gap_result()

    chat_only_html, comment_text = render_recreate_comment(result)

    assert "<!doctype html>" in chat_only_html.lower()
    assert "recreated and re-ran" in comment_text.lower()
    assert "still moves to manual review" in comment_text.lower()
    assert result["scenario_id"] in comment_text
    assert result["auth"]["contact_id"] in comment_text


def test_render_recreate_comment_masks_otp_in_chat_html():
    result = determination_gap_result()  # transcript has a standalone 6-digit OTP: 483920

    chat_only_html, _ = render_recreate_comment(result)

    assert "483920" not in chat_only_html
    assert "•" * 6 in chat_only_html
