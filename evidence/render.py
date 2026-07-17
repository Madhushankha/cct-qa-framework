"""Render self-contained HTML evidence pages from a canonical Result (P0 schema).

Three views, all pure functions over ``dict`` (already schema-validated by the caller):

- ``render_case``       — one case: chat history (OTP-masked) + verdict + checks + the
                          seed checkpoint vector + the DDS determination (proof).
- ``render_index``      — expected-vs-actual, one row per case, PASS/FAIL + OTP + checkpoints.
- ``render_bot_issues`` — FAILs grouped into issue cards keyed by ``verdict.decision``.

Stdlib only (html, re). Deterministic: no timestamps or randomness in the output beyond
what's already in the Result.
"""
from __future__ import annotations

import html
import re
from collections import defaultdict

# A "standalone" 6-digit run: not preceded/followed by another digit, so we never chew
# into a longer number (ticket #, amount, etc.) that merely contains 6 digits in a row.
_OTP_RE = re.compile(r"(?<!\d)\d{6}(?!\d)")
_OTP_MASK = "•" * 6  # ••••••

CSS = """<style>
:root { color-scheme: light dark; }
body {
  font-family: 'Segoe UI', Arial, sans-serif; margin: 24px; max-width: 1100px;
  color: #1a2330; background: #fafbfc;
}
h1 { margin: 0 0 10px; font-size: 22px; }
h2 { font-size: 15px; margin: 20px 0 6px; color: #0b3d6b; }
a { color: #0b5cad; }
table { border-collapse: collapse; width: 100%; margin: 6px 0 14px; }
td, th { border: 1px solid #dde3ea; padding: 6px 9px; font-size: 12.5px; text-align: left; vertical-align: top; }
th { background: #0b3d6b; color: #fff; }
.meta td:nth-child(odd) { background: #f0f4f8; font-weight: 600; width: 14%; }
.badge { display: inline-block; padding: 2px 12px; border-radius: 14px; color: #fff; font-weight: 700; font-size: 12px; }
.pass { color: #1b7e34; font-weight: 700; }
.fail { color: #b00020; font-weight: 700; }
.badge.pass { background: #1b7e34; color: #fff; }
.badge.fail { background: #b00020; color: #fff; }
.dl { display: inline-block; border: 1px solid #b9c6d6; border-radius: 14px; padding: 2px 11px;
      font-size: 11px; font-weight: 600; text-decoration: none; vertical-align: middle; margin-left: 8px; }
/* ── chat UI: aligned message bubbles (bot left / customer right) ── */
.chat { display: flex; flex-direction: column; gap: 12px; border: 1px solid #e3e8ee;
        border-radius: 12px; padding: 16px; background: #f6f8fb; max-height: 720px; overflow: auto; }
.turn { display: flex; flex-direction: column; max-width: 76%; }
.turn.bot { align-self: flex-start; align-items: flex-start; }
.turn.customer { align-self: flex-end; align-items: flex-end; }
.turn .who { font-size: 10.5px; color: #8a97a8; font-weight: 600; margin: 0 6px 3px; }
.turn .ts { color: #aab4c2; font-weight: 400; }
.bubble { padding: 8px 12px; border-radius: 16px; font-size: 12.5px; line-height: 1.45;
          white-space: pre-wrap; word-wrap: break-word; box-shadow: 0 1px 1.5px rgba(20,40,70,.06); }
.turn.bot .bubble { background: #fff; border: 1px solid #e3e8ee; color: #1a2330; border-bottom-left-radius: 4px; }
.turn.customer .bubble { background: #0b5cad; color: #fff; border-bottom-right-radius: 4px; }
.opts { display: flex; flex-wrap: wrap; gap: 5px; margin: 5px 2px 0; }
.turn.customer .opts { justify-content: flex-end; }
.chip { display: inline-block; border: 1px solid #b9c6d6; border-radius: 14px; padding: 2px 11px;
        font-size: 11px; background: #eef3f8; color: #34506e; }
.banner { background: #fff8e6; border: 1px solid #f0d98a; border-radius: 10px; padding: 7px 11px;
          font-size: 11.5px; margin-top: 5px; color: #6b5600; max-width: 100%; }
.flightcard { background: #eef4fb; border: 1px solid #9db8d6; border-radius: 10px; padding: 8px 12px;
              font-size: 12.5px; font-weight: 600; margin-top: 5px; color: #1a3a5c;
              display: inline-flex; align-items: center; gap: 8px; }
.flightcard::before { content: "✈"; font-size: 14px; }
.kpi { display: inline-block; background: #fff; border: 1px solid #dde3ea; border-radius: 8px; padding: 7px 12px; margin: 3px 6px 3px 0; }
.kpi b { font-size: 17px; display: block; color: #0b3d6b; }
.issue { background: #fff; border: 1px solid #dde3ea; border-left: 5px solid #b00020; border-radius: 8px; padding: 14px 16px; margin: 14px 0; }
.issue h2 { margin: 0 0 8px; color: #1a2330; }
.cnt { background: #b00020; color: #fff; font-weight: 700; border-radius: 20px; padding: 2px 10px; font-size: 13px; margin-left: 8px; }
code, .mono { font-family: ui-monospace, Consolas, monospace; font-size: 11.5px; }
@media (prefers-color-scheme: dark) {
  body { background: #14181f; color: #dfe6ee; }
  th { background: #14304d; }
  td, th { border-color: #2a323d; }
  .meta td:nth-child(odd) { background: #1c222c; }
  .chat { border-color: #2a323d; }
  .turn.customer .text { background: #1c2c3d; }
  .turn.bot .text { background: #1c3322; }
  .kpi, .issue { background: #1c222c; border-color: #2a323d; }
  .chat { background: #12161c; border-color: #2a323d; }
  .turn.bot .bubble { background: #1c222c; border-color: #2a323d; color: #dfe6ee; }
  .turn.customer .bubble { background: #2563a8; color: #fff; }
  .chip { background: #1c2530; border-color: #33475e; color: #a9c4e0; }
  .banner { background: #2a2410; border-color: #5a4d1c; color: #d8c78a; }
  .flightcard { background: #16283c; border-color: #33475e; color: #a9c4e0; }
  a { color: #6db3ff; }
}
</style>"""


def _esc(value) -> str:
    return html.escape("" if value is None else str(value))


def _amount(a) -> str:
    if not a:
        return "—"  # em dash
    return f'{a.get("currency", "")} {a.get("value", "")}'.strip()


def _mask_otp(text: str) -> str:
    return _OTP_RE.sub(_OTP_MASK, text or "")


def _pass_fail(ok) -> str:
    return "PASS" if ok else "FAIL"


def _cls(ok) -> str:
    return "pass" if ok else "fail"


# friendly speaker labels (match the reference evidence style)
_WHO = {"customer": "\U0001f464 Customer", "assistant": "\U0001f916 Ask AC",
        "bot": "\U0001f916 Ask AC"}

# widget markup embedded in bot text: §W§<TYPE>§<body>
_WIDGET_SPLIT = re.compile(r"(§W§[A-Z_]+§)")
_WIDGET_HEAD = re.compile(r"§W§([A-Z_]+)§")
_BOLD_RE = re.compile(r"\*\*(.+?)\*\*", re.S)


def _md(text: str) -> str:
    """Escape, then render **bold** — the only markdown the bot emits."""
    return _BOLD_RE.sub(r"<b>\1</b>", _esc(text))


def _widget_html(wtype: str, body: str) -> str:
    """Render one embedded widget as a chat-UI element (chips / banner / flight card)."""
    body = body.strip()
    if not body:
        return ""
    if wtype in ("OPTIONS", "QUICK_REPLIES", "SINGLE_SELECT", "MULTI_SELECT"):
        chips = "".join(f'<span class="chip">{_md(o.strip())}</span>'
                        for o in body.split("•") if o.strip())
        return f'<div class="opts">{chips}</div>'
    if wtype in ("FLIGHT", "FLIGHT_SAME_PNR"):
        return f'<div class="flightcard">{_md(body)}</div>'
    # BANNER, INFO_BANNER, and anything else -> a subtle callout
    return f'<div class="banner">{_md(body)}</div>'


def _fmt_msg(text: str) -> str:
    """A message body -> bubble text + any widgets. Splits on §W§TYPE§ markers so option lists,
    banners, and flight cards render as chat-UI elements instead of raw control codes."""
    parts = _WIDGET_SPLIT.split(text or "")
    plain = parts[0].strip()
    out = f'<div class="bubble">{_md(plain)}</div>' if plain else ""
    i = 1
    while i < len(parts):
        m = _WIDGET_HEAD.match(parts[i])
        body = parts[i + 1] if i + 1 < len(parts) else ""
        if m:
            out += _widget_html(m.group(1), body)
        i += 2
    return out or '<div class="bubble"></div>'


def _chat_html(transcript: list[dict]) -> str:
    rows = []
    for turn in transcript or []:
        role = turn.get("role", "") or ""
        text = turn.get("text", "") or ""
        if role == "customer":
            text = _mask_otp(text)
        who_cls = "customer" if role == "customer" else "bot"
        who = _WHO.get(role, role or "?")
        note = turn.get("note")
        note_html = f' <span class="ts">· {_esc(note)}</span>' if note else ""
        rows.append(
            f'<div class="turn {who_cls}">'
            f'<div class="who">{who} <span class="ts">{_esc(turn.get("ts") or "")}</span>{note_html}</div>'
            f"{_fmt_msg(text)}"
            f"</div>"
        )
    return "".join(rows) or "<p>(no transcript)</p>"


def _checks_table(checks: list[dict]) -> str:
    rows = "".join(
        f"<tr><td>{_esc(c.get('name'))}</td><td>{_esc(c.get('expected'))}</td>"
        f"<td>{_esc(c.get('actual'))}</td>"
        f"<td class=\"{_cls(c.get('pass'))}\">{_pass_fail(c.get('pass'))}</td></tr>"
        for c in checks or []
    )
    return (
        '<table><tr><th>Check</th><th>Expected</th><th>Actual</th><th>Result</th></tr>'
        f"{rows or '<tr><td colspan=4>no checks</td></tr>'}</table>"
    )


def _checkpoints_table(checkpoints: list[dict]) -> str:
    rows = "".join(
        f"<tr><td>{_esc(cp.get('area'))}</td>"
        f"<td class=\"{_cls(cp.get('pass'))}\">{_pass_fail(cp.get('pass'))}</td></tr>"
        for cp in checkpoints or []
    )
    return (
        '<table><tr><th>Seed checkpoint</th><th>Result</th></tr>'
        f"{rows or '<tr><td colspan=2>no checkpoints</td></tr>'}</table>"
    )


def _dds_html(dds) -> str:
    if not dds:
        return "<p>No DDS determination recorded for this case.</p>"
    return (
        "<table><tr><th>Status</th><th>System code</th><th>Amount</th><th>Trace</th></tr>"
        f"<tr><td>{_esc(dds.get('status'))}</td><td>{_esc(dds.get('system_code'))}</td>"
        f"<td>{_esc(_amount(dds.get('amount')))}</td>"
        f"<td class=\"mono\">{_esc(dds.get('trace_s3'))}</td></tr></table>"
    )


def render_case(result: dict) -> str:
    """Per-case evidence page: chat (OTP masked) + verdict + checks + checkpoints + DDS."""
    case = result.get("case", {}) or {}
    verdict = result.get("verdict", {}) or {}
    seed = result.get("seed", {}) or {}
    auth = result.get("auth", {}) or {}
    ok = bool(verdict.get("matches_expected"))

    expected = f"{case.get('expected_status', '')} · {case.get('expected_system_code', '')} · {_amount(case.get('expected_amount'))}"
    actual = f"{verdict.get('decision', '')} · {_amount(verdict.get('amount'))}"

    return f"""<!doctype html>
<html><head><meta charset="utf-8"><title>{_esc(case.get('test_case'))} — {_esc(case.get('passenger'))}</title>{CSS}</head>
<body>
<h1>{_esc(case.get('test_case'))} <span class="badge {_cls(ok)}">{_pass_fail(ok)}</span> <a class="dl" download href="{_esc(case.get('test_case'))}.evidence.html">&#11015; download</a></h1>
<table class="meta">
<tr><td>PNR</td><td>{_esc(case.get('pnr'))}</td><td>Passenger</td><td>{_esc(case.get('passenger'))}</td></tr>
<tr><td>Regime</td><td>{_esc(case.get('regime'))}</td><td>ContactId</td><td class="mono">{_esc(auth.get('contact_id'))}</td></tr>
<tr><td>Expected</td><td>{_esc(expected)}</td><td>Actual (bot)</td><td>{_esc(actual)}</td></tr>
<tr><td>OTP fetched</td><td>{'yes' if auth.get('otp_fetched') else 'no'}</td><td>Scenario</td><td class="mono">{_esc(result.get('scenario_id'))}</td></tr>
</table>
<h2>Verdict</h2>
<p>{_esc(verdict.get('reasoning'))}</p>
{_checks_table(verdict.get('checks'))}
<h2>Seed checkpoint vector</h2>
{_checkpoints_table(seed.get('checkpoints'))}
<h2>DDS determination (proof)</h2>
{_dds_html(seed.get('dds'))}
<h2>Chat history</h2>
<div class="chat">{_chat_html(result.get('transcript'))}</div>
</body></html>"""


def render_index(results: list[dict]) -> str:
    """Expected-vs-actual, one row per case: PASS/FAIL, OTP, checkpoint-pass count."""
    rows = []
    for r in results:
        case = r.get("case", {}) or {}
        verdict = r.get("verdict", {}) or {}
        seed = r.get("seed", {}) or {}
        auth = r.get("auth", {}) or {}
        ok = bool(verdict.get("matches_expected"))
        checkpoints = seed.get("checkpoints") or []
        cp_pass = sum(1 for c in checkpoints if c.get("pass"))
        tc = case.get("test_case", "")
        expected = f"{case.get('expected_status', '')} · {case.get('expected_system_code', '')} · {_amount(case.get('expected_amount'))}"
        actual = f"{verdict.get('decision', '')} · {_amount(verdict.get('amount'))}"
        rows.append(
            f'<tr><td><a href="{_esc(tc)}.evidence.html">{_esc(tc)}</a></td>'
            f'<td class="mono">{_esc(case.get("pnr"))}</td>'
            f"<td>{_esc(expected)}</td><td>{_esc(actual)}</td>"
            f'<td class="{_cls(ok)}">{_pass_fail(ok)}</td>'
            f'<td>{"&#10003;" if auth.get("otp_fetched") else "&#8212;"}</td>'
            f"<td>{cp_pass}/{len(checkpoints)}</td></tr>"
        )
    n = len(results)
    p = sum(1 for r in results if r.get("verdict", {}).get("matches_expected"))
    pct = round(100 * p / n) if n else 0
    return f"""<!doctype html>
<html><head><meta charset="utf-8"><title>Expected vs Actual</title>{CSS}</head>
<body>
<h1>Expected vs Actual</h1>
<div>
<span class="kpi"><b>{n}</b>cases</span>
<span class="kpi"><b class="pass">{p}</b>PASS</span>
<span class="kpi"><b class="fail">{n - p}</b>FAIL</span>
<span class="kpi"><b>{pct}%</b>pass rate</span>
</div>
<table>
<tr><th>Case</th><th>PNR</th><th>Expected</th><th>Actual (bot)</th><th>Result</th><th>OTP</th><th>Checkpoints</th></tr>
{"".join(rows)}
</table>
</body></html>"""


def render_bot_issues(results: list[dict]) -> str:
    """FAILs grouped into issue cards keyed by verdict.decision, with an example chat
    and the affected scenario_ids/contact_ids."""
    fails = [r for r in results if not r.get("verdict", {}).get("matches_expected")]
    groups: dict[str, list[dict]] = defaultdict(list)
    for r in fails:
        decision = r.get("verdict", {}).get("decision") or "UNKNOWN"
        groups[decision].append(r)

    cards = []
    for decision in sorted(groups):
        items = groups[decision]
        example = items[0]
        id_rows = "".join(
            f'<tr><td class="mono">{_esc(r.get("scenario_id"))}</td>'
            f'<td class="mono">{_esc(r.get("auth", {}).get("contact_id"))}</td></tr>'
            for r in items
        )
        cards.append(f"""<div class="issue">
<h2>{_esc(decision)}<span class="cnt">{len(items)}</span></h2>
<p>Example chat — {_esc(example.get('scenario_id'))}</p>
<div class="chat">{_chat_html(example.get('transcript'))}</div>
<h2>Affected cases</h2>
<table><tr><th>Scenario</th><th>ContactId</th></tr>{id_rows}</table>
</div>""")

    body = "".join(cards) if cards else "<p>No failures.</p>"
    return f"""<!doctype html>
<html><head><meta charset="utf-8"><title>Bot Issues</title>{CSS}</head>
<body>
<h1>Bot Issues</h1>
<div><span class="kpi"><b>{len(results)}</b>run</span>
<span class="kpi"><b class="fail">{len(fails)}</b>fail</span>
<span class="kpi"><b>{len(groups)}</b>issue groups</span></div>
{body}
</body></html>"""
