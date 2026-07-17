"""Render a ``quality.grade.quality_report()`` dict to self-contained HTML
(light/dark aware, stdlib only: ``html``).
"""
from __future__ import annotations

import html

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
.kpi { display: inline-block; background: #fff; border: 1px solid #dde3ea; border-radius: 8px; padding: 7px 12px; margin: 3px 6px 3px 0; }
.kpi b { font-size: 17px; display: block; color: #0b3d6b; }
.dl { display: inline-block; border: 1px solid #b9c6d6; border-radius: 14px; padding: 2px 11px;
      font-size: 11px; font-weight: 600; text-decoration: none; vertical-align: middle; margin-left: 8px; }
code { font-family: ui-monospace, Consolas, monospace; font-size: 11.5px; }
@media (prefers-color-scheme: dark) {
  body { background: #14181f; color: #dfe6ee; }
  th { background: #14304d; }
  td, th { border-color: #2a323d; }
  .kpi { background: #1c222c; border-color: #2a323d; }
  a { color: #6db3ff; }
}
</style>"""

_SEV_COLOR = {"High": "#b00020", "Medium": "#b8860b", "Low": "#666"}


def _esc(value) -> str:
    return html.escape("" if value is None else str(value))


def _score_color(score: int) -> str:
    if score >= 85:
        return "#1b7e34"
    if score >= 60:
        return "#b8860b"
    return "#b00020"


def _findings_table(findings: list[dict] | None, with_recommendation: bool = False) -> str:
    if not findings:
        return '<p style="color:#1b7e34">No issues detected.</p>'
    header = "<tr><th>Area</th><th>Severity</th><th>Issue</th><th>Evidence</th>"
    header += "<th>Recommendation</th></tr>" if with_recommendation else "</tr>"
    rows = []
    for f in findings:
        sev = f.get("severity", "")
        row = (
            f'<tr><td>{_esc(f.get("area"))}</td>'
            f'<td style="color:{_SEV_COLOR.get(sev, "#666")};font-weight:600">{_esc(sev)}</td>'
            f'<td>{_esc(f.get("issue"))}</td>'
            f'<td><code>{_esc(f.get("evidence"))}</code></td>'
        )
        if with_recommendation:
            row += f'<td>{_esc(f.get("recommendation"))}</td>'
        row += "</tr>"
        rows.append(row)
    return f"<table>{header}{''.join(rows)}</table>"


def render_quality(report: dict) -> str:
    """One case's quality review page: score + deterministic findings + (optional) LLM findings."""
    scenario_id = report.get("scenario_id", "")
    test_case = report.get("test_case") or scenario_id
    score = report.get("score", 0)
    det = report.get("deterministic") or []
    llm = report.get("llm")
    summary = report.get("summary", "")

    llm_section = ""
    if llm is not None:
        llm_section = f"""<h2>LLM judge</h2>
{_findings_table(llm, with_recommendation=True)}"""

    return f"""<!doctype html>
<html><head><meta charset="utf-8"><title>Quality — {_esc(test_case)}</title>{CSS}</head>
<body>
<h1>Response Quality — {_esc(test_case)} <a class="dl" download href="{_esc(test_case)}.quality.html">&#11015; download</a></h1>
<p class="mono" style="color:#667">{_esc(scenario_id)}</p>
<div>
<span class="kpi"><b style="color:{_score_color(score)}">{score}</b>/100 quality score</span>
<span class="kpi"><b>{len(det)}</b>deterministic</span>
<span class="kpi"><b>{len(llm) if llm is not None else "—"}</b>LLM</span>
</div>
<p>{_esc(summary)}</p>
<h2>Deterministic checks</h2>
{_findings_table(det)}
{llm_section}
</body></html>"""


def render_quality_index(reports: list[dict]) -> str:
    """Index across every graded case: score, finding counts, link to the per-case page."""
    rows = []
    for r in reports:
        scenario_id = r.get("scenario_id", "")
        test_case = r.get("test_case") or scenario_id
        score = r.get("score", 0)
        det = r.get("deterministic") or []
        llm = r.get("llm")
        rows.append(
            f'<tr><td><a href="{_esc(test_case)}.quality.html">{_esc(test_case)}</a></td>'
            f'<td class="mono" style="color:#667">{_esc(scenario_id)}</td>'
            f'<td style="color:{_score_color(score)};font-weight:700">{score}</td>'
            f"<td>{len(det)}</td><td>{len(llm) if llm is not None else '—'}</td></tr>"
        )
    n = len(reports)
    avg = round(sum(r.get("score", 0) for r in reports) / n) if n else 0
    return f"""<!doctype html>
<html><head><meta charset="utf-8"><title>Response Quality — index</title>{CSS}</head>
<body>
<h1>Response Quality — Index</h1>
<div>
<span class="kpi"><b>{n}</b>cases</span>
<span class="kpi"><b style="color:{_score_color(avg)}">{avg}</b>avg score</span>
</div>
<table><tr><th>Case</th><th>Scenario</th><th>Score</th><th>Deterministic</th><th>LLM</th></tr>{"".join(rows)}</table>
</body></html>"""
