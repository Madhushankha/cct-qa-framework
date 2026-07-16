"""file_defects(): opt-in JIRA filing with a resume-safe ledger + dedupe.

DEFAULT dry_run=True: returns exactly what WOULD be filed, files nothing, touches no network.
Only dry_run=False actually POSTs (stdlib urllib) to jira_conf["base_url"] using Basic auth
built from the env vars JIRA_EMAIL / JIRA_API_TOKEN (never read from anywhere else), attaches
the payload's chat-history HTML, and appends the dedup_key + created issue key to the ledger
JSON (a list) immediately after each create — so an interruption can never orphan/re-file an
issue. Any payload whose dedup_key is already in the ledger is skipped in both modes.
"""
from __future__ import annotations

import base64
import json
import mimetypes
import os
import ssl
import urllib.error
import urllib.request
from pathlib import Path

_DEFAULT_ATTACHMENT_FILENAME = "chat_history.html"


class JiraFileError(Exception):
    pass


def _load_ledger(ledger_path: str | Path) -> list[dict]:
    p = Path(ledger_path)
    if not p.exists():
        return []
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    return data if isinstance(data, list) else []


def _save_ledger(ledger_path: str | Path, ledger: list[dict]) -> None:
    p = Path(ledger_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(ledger, indent=2, sort_keys=True), encoding="utf-8")


def _auth_header() -> str:
    email = os.environ.get("JIRA_EMAIL")
    token = os.environ.get("JIRA_API_TOKEN")
    if not email or not token:
        raise JiraFileError(
            "JIRA_EMAIL and JIRA_API_TOKEN must both be set in the environment to file defects "
            "(never read from config or the payload)."
        )
    return "Basic " + base64.b64encode(f"{email}:{token}".encode()).decode()


def _post_issue(base_url: str, fields: dict) -> dict:  # pragma: no cover - network path, dry_run only in tests
    body = json.dumps({"fields": fields}).encode("utf-8")
    req = urllib.request.Request(
        base_url.rstrip("/") + "/rest/api/2/issue",
        data=body, method="POST",
        headers={"Authorization": _auth_header(), "Accept": "application/json",
                 "Content-Type": "application/json"},
    )
    ctx = ssl.create_default_context()
    with urllib.request.urlopen(req, timeout=60, context=ctx) as resp:
        raw = resp.read().decode("utf-8", "replace")
        return json.loads(raw) if raw.strip() else {}


def _attach(base_url: str, issue_key: str, filename: str, content: bytes) -> None:  # pragma: no cover
    boundary = "----cctqa-jira-boundary"
    ctype = mimetypes.guess_type(filename)[0] or "application/octet-stream"
    pre = (f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{filename}"\r\n'
           f"Content-Type: {ctype}\r\n\r\n").encode()
    post = f"\r\n--{boundary}--\r\n".encode()
    body = pre + content + post
    req = urllib.request.Request(
        base_url.rstrip("/") + f"/rest/api/2/issue/{issue_key}/attachments",
        data=body, method="POST",
        headers={"Authorization": _auth_header(), "X-Atlassian-Token": "no-check",
                 "Content-Type": f"multipart/form-data; boundary={boundary}"},
    )
    ctx = ssl.create_default_context()
    with urllib.request.urlopen(req, timeout=120, context=ctx):
        pass


def file_defects(payloads: list[dict], jira_conf: dict, ledger_path: str | Path,
                  dry_run: bool = True, limit: int | None = None) -> dict:
    """payloads: jira.payload.build_payload() outputs. Returns
    {"dry_run": bool, "would_file": [...], "filed": [...], "skipped": [dedup_key, ...]}."""
    ledger = _load_ledger(ledger_path)
    already_filed = {entry.get("dedup_key") for entry in ledger if isinstance(entry, dict)}

    todo: list[dict] = []
    skipped: list[str] = []
    for payload in payloads:
        key = payload.get("dedup_key")
        if key in already_filed:
            skipped.append(key)
        else:
            todo.append(payload)

    if limit is not None:
        todo = todo[:limit]

    if dry_run:
        return {"dry_run": True, "would_file": todo, "filed": [], "skipped": skipped}

    base_url = jira_conf.get("base_url")
    if not base_url:
        raise JiraFileError("jira_conf['base_url'] is required to file defects")

    filed: list[dict] = []
    for payload in todo:
        issue = _post_issue(base_url, payload["fields"])
        issue_key = issue.get("key")

        attachment_html = payload.get("attachment_html")
        if issue_key and attachment_html:
            try:
                _attach(base_url, issue_key,
                        payload.get("attachment_filename") or _DEFAULT_ATTACHMENT_FILENAME,
                        attachment_html.encode("utf-8"))
            except Exception:
                pass  # attachment failure must not lose the created issue / orphan the ledger

        # record IMMEDIATELY so an interruption can never orphan / re-file this defect
        ledger.append({"dedup_key": payload.get("dedup_key"), "key": issue_key})
        _save_ledger(ledger_path, ledger)
        filed.append({"dedup_key": payload.get("dedup_key"), "key": issue_key})

    return {"dry_run": False, "would_file": [], "filed": filed, "skipped": skipped}
