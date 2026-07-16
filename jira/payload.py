"""build_payload(): one canonical Result (P0) + its grade (P6) -> a reviewable JIRA bug payload.

    payload = build_payload(result, grade, jira_conf)
    payload == {"fields": {...}, "description_wiki": "...", "dedup_key": "...", ...}

``fields`` carries only IDs resolved from ``jira_conf`` (see ``config.example.json``) — never
hardcoded project/component/custom-field IDs, so a JIRA-instance change is a config edit, not a
code edit. ``description_wiki`` is JIRA wiki markup (api v2 create, not ADF): test intent,
expected vs actual, the DDS determination proof (the recurring "eligible in DDS but bot
escalated" gap — see analysis.grade), the grade findings, and the ContactId. ``dedup_key`` is a
stable hash of (scenario_id or pnr) + system_code, used by ``jira.file.file_defects`` and the
ledger to skip re-filing the same defect on a re-run.
"""
from __future__ import annotations

import hashlib

from jira.render import chat_history_html

_DEFAULT_ATTACHMENT_FILENAME = "chat_history.html"


def _amount(a) -> str:
    if not a:
        return "n/a"
    return f'{a.get("currency", "")} {a.get("value", "")}'.strip()


def _dedup_key(result: dict) -> str:
    case = result.get("case") or {}
    identity = case.get("pnr") or result.get("scenario_id") or ""
    system_code = case.get("expected_system_code") or ""
    raw = f"{identity}::{system_code}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def _dds_proof_line(seed: dict) -> str:
    dds = (seed or {}).get("dds")
    if not dds:
        return "No DDS determination recorded for this case."
    status = dds.get("status")
    system_code = dds.get("system_code")
    amount = _amount(dds.get("amount"))
    return f"determination on file: {status} {system_code} {amount}"


def _findings_wiki(findings: list[dict]) -> str:
    if not findings:
        return "|| Code || Severity || Message ||\n| — | — | (no findings) |"
    rows = "\n".join(
        f"| {f.get('code')} | {f.get('severity')} | {f.get('message')} |" for f in findings
    )
    return f"|| Code || Severity || Message ||\n{rows}"


def _summary(result: dict) -> str:
    run = result.get("run") or {}
    case = result.get("case") or {}
    verdict = result.get("verdict") or {}
    env = (run.get("env") or "").upper()
    feed = (run.get("feed") or "").upper()
    pnr = case.get("pnr") or ""
    decision = verdict.get("decision") or ""
    expected = case.get("expected_status") or ""
    return f"[{env}][{feed}] {pnr} — {decision} vs expected {expected}"


def _description_wiki(result: dict, grade: dict) -> str:
    run = result.get("run") or {}
    case = result.get("case") or {}
    verdict = result.get("verdict") or {}
    seed = result.get("seed") or {}
    auth = result.get("auth") or {}

    expected = (
        f"{case.get('expected_status', '')} · {case.get('expected_system_code', '')} · "
        f"{_amount(case.get('expected_amount'))}"
    )
    actual = f"{verdict.get('decision', '')} · {_amount(verdict.get('amount'))}"

    return f"""h3. Test
* *Scenario:* {result.get('scenario_id', '')}
* *Test case:* {case.get('test_case', '')}
* *Regime:* {case.get('regime', '')}
* *Booking:* PNR {case.get('pnr', '')} (pnrId {case.get('pnr_id', '')})
* *Passenger:* {case.get('passenger', '')}
* *Environment:* {run.get('env', '')} ({run.get('product', '')}), feed {run.get('feed', '')}

h3. Expected
* {expected}

h3. Actual (bot)
* {actual}

h3. DDS determination (proof)
* {_dds_proof_line(seed)}, but bot {verdict.get('decision', '')}

h3. Grade findings
{_findings_wiki(grade.get('findings') or [])}

h3. Evidence
* *ContactId:* {auth.get('contact_id')}
* *Reasoning:* {verdict.get('reasoning', '')}
"""


def _fields(result: dict, description_wiki: str, jira_conf: dict) -> dict:
    fields = {
        "project": {"key": jira_conf["project"]},
        "issuetype": {"id": jira_conf["issuetype_id"]},
        "summary": _summary(result),
        "description": description_wiki,
        "priority": {"id": jira_conf["priority_id"]},
        "versions": [{"id": jira_conf["affects_version_id"]}],
        "components": [{"id": jira_conf["component_id"]}],
        jira_conf["cf_testing_type"]: {"id": jira_conf["testing_type_id"]},
        jira_conf["cf_severity"]: {"id": jira_conf["severity_id"]},
    }
    labels = jira_conf.get("labels")
    if labels:
        fields["labels"] = list(labels)
    return fields


def build_payload(result: dict, grade: dict, jira_conf: dict) -> dict:
    """result: canonical Result (P0). grade: analysis.grade.grade(result) output.
    jira_conf: externalized field/component/project IDs (see config.example.json)."""
    description_wiki = _description_wiki(result, grade)
    dedup_key = _dedup_key(result)
    fields = _fields(result, description_wiki, jira_conf)

    return {
        "fields": fields,
        "description_wiki": description_wiki,
        "dedup_key": dedup_key,
        "attachment_html": chat_history_html(result),
        "attachment_filename": _DEFAULT_ATTACHMENT_FILENAME,
        "scenario_id": result.get("scenario_id"),
        "pnr": (result.get("case") or {}).get("pnr"),
    }
