"""HTML/text rendering for the jira package: the pre-filing review page, the chat-only
attachment used both for filing and for the recreate-comment workflow, and the ready-to-paste
JIRA comment text for "recreated & re-ran, still moves to manual review" follow-ups.

Stdlib only (html, hashlib via payload). Deterministic: no timestamps/randomness beyond what's
already in the Result.
"""
from __future__ import annotations

import html
import json
import re

# Same standalone-6-digit convention as evidence.render — never chew into a longer number.
_OTP_RE = re.compile(r"(?<!\d)\d{6}(?!\d)")
_OTP_MASK = "•" * 6

CSS = """<style>
:root { color-scheme: light dark; }
body { font-family: 'Segoe UI', Arial, sans-serif; margin: 22px; max-width: 1080px;
  color: #1a2330; background: #fafbfc; }
h1 { margin: 0 0 4px; font-size: 21px; }
h2 { font-size: 14px; margin: 16px 0 6px; color: #0b3d6b; }
table { border-collapse: collapse; width: 100%; margin: 6px 0 14px; }
td, th { border: 1px solid #dde3ea; padding: 6px 9px; font-size: 12.3px; text-align: left; vertical-align: top; }
th { background: #22344a; color: #fff; }
.card { background: #fff; border: 1px solid #dde3ea; border-left: 5px solid #b00020; border-radius: 8px;
  padding: 12px 14px; margin: 14px 0; }
.kpi { display: inline-block; background: #fff; border: 1px solid #dde3ea; border-radius: 8px;
  padding: 7px 12px; margin: 3px 6px 3px 0; }
.kpi b { font-size: 17px; display: block; color: #0b3d6b; }
pre.desc { background: #f7f9fb; border: 1px solid #e2e7ee; border-radius: 6px; padding: 9px;
  font-size: 11.5px; white-space: pre-wrap; overflow-x: auto; }
.chat { border: 1px solid #eee; border-radius: 6px; padding: 8px; max-height: 520px; overflow: auto; }
.turn { margin: 4px 0; }
.turn .who { font-size: 11px; color: #667; font-weight: 600; }
.turn .text { padding: 7px 10px; border-radius: 7px; font-size: 12.5px; white-space: pre-wrap; }
.turn.customer .text { background: #eaf2fb; }
.turn.bot .text { background: #eafbea; }
.mono { font-family: ui-monospace, Consolas, monospace; font-size: 11.5px; }
@media (prefers-color-scheme: dark) {
  body { background: #14181f; color: #dfe6ee; }
  th { background: #14304d; }
  td, th { border-color: #2a323d; }
  .card, .kpi { background: #1c222c; border-color: #2a323d; }
  pre.desc { background: #1c222c; border-color: #2a323d; }
  .chat { border-color: #2a323d; }
  .turn.customer .text { background: #1c2c3d; }
  .turn.bot .text { background: #1c3322; }
}
</style>"""


def _esc(value) -> str:
    return html.escape("" if value is None else str(value))


def _mask_otp(text: str) -> str:
    return _OTP_RE.sub(_OTP_MASK, text or "")


def _chat_turns_html(transcript: list[dict]) -> str:
    rows = []
    for turn in transcript or []:
        role = turn.get("role", "") or ""
        text = turn.get("text", "") or ""
        if role == "customer":
            text = _mask_otp(text)
        who_cls = "customer" if role == "customer" else "bot"
        rows.append(
            f'<div class="turn {who_cls}"><div class="who">{_esc(role)}</div>'
            f'<div class="text">{_esc(text)}</div></div>'
        )
    return "".join(rows) or "<p>(no transcript)</p>"


def chat_history_html(result: dict) -> str:
    """Self-contained chat-only HTML page (OTP-masked) — used both as the JIRA issue
    attachment and as the recreate-comment attachment. Identified by PNR/passenger, not by
    internal test-case id (mirrors the existing recreate-comment convention)."""
    case = result.get("case") or {}
    auth = result.get("auth") or {}
    who = " / ".join(x for x in [case.get("pnr", ""), case.get("passenger", "")] if x)
    return f"""<!doctype html>
<html><head><meta charset="utf-8"><title>Chat history — {_esc(who)}</title>{CSS}</head>
<body>
<h1>Chat history — {_esc(who)}</h1>
<p class="mono">ContactId: {_esc(auth.get('contact_id'))} · scenario {_esc(result.get('scenario_id'))}</p>
<div class="chat">{_chat_turns_html(result.get('transcript'))}</div>
</body></html>"""


def render_recreate_comment(result: dict) -> tuple[str, str]:
    """(chat_only_html, comment_text) for the recreate/re-run follow-up workflow: re-run a
    filed defect's scenario, attach the fresh chat, post a ready comment confirming it still
    reproduces."""
    case = result.get("case") or {}
    verdict = result.get("verdict") or {}
    auth = result.get("auth") or {}

    chat_only_html = chat_history_html(result)

    comment_text = (
        f"Recreated and re-ran {result.get('scenario_id', '')} "
        f"(PNR {case.get('pnr', '')}) — same result: bot {verdict.get('decision', '')} "
        f"instead of {case.get('expected_status', '')}; still moves to manual review. "
        f"See attached chat history for the re-run transcript. "
        f"ContactId: {auth.get('contact_id')}."
    )
    return chat_only_html, comment_text


def _payload_card(payload: dict) -> str:
    fields = payload.get("fields") or {}
    return f"""<div class="card">
<h2>{_esc(fields.get('summary'))}</h2>
<table>
<tr><th>dedup_key</th><td class="mono">{_esc(payload.get('dedup_key'))}</td>
    <th>PNR</th><td class="mono">{_esc(payload.get('pnr'))}</td></tr>
<tr><th>scenario</th><td class="mono" colspan="3">{_esc(payload.get('scenario_id'))}</td></tr>
</table>
<details><summary>fields (JIRA create payload)</summary>
<pre class="desc">{_esc(json.dumps(fields, indent=2, sort_keys=True))}</pre></details>
<details><summary>description (wiki markup)</summary>
<pre class="desc">{_esc(payload.get('description_wiki'))}</pre></details>
</div>"""


def render_review(payloads: list[dict]) -> str:
    """Human-reviewable HTML page listing every payload that WOULD be filed — nothing here
    files anything; it's the review artifact the `cctqa jira` CLI writes before --file."""
    cards = "".join(_payload_card(p) for p in payloads) if payloads else "<p>No defects selected.</p>"
    return f"""<!doctype html>
<html><head><meta charset="utf-8"><title>JIRA review — {len(payloads)} defect(s)</title>{CSS}</head>
<body>
<h1>JIRA bug review</h1>
<div><span class="kpi"><b>{len(payloads)}</b>defect(s) selected (Valid FAIL only)</span></div>
{cards}
</body></html>"""
