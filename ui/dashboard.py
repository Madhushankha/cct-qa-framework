"""P7 dashboard — a single browsable index over ALL runs under results/.

Scans `results/<date>/<env>_<product>_<feed>_<time>/*.result.json`, aggregates each run's PASS/FAIL/
ERROR, and renders one `results/index.html` grouped by date. Each row carries doc chips — Report
(`index.html`), Quality (`quality-index.html`), Bot issues (`bot-issues.html`), Metrics
(`report.html`) — linked (with a download anchor) only when the file exists in the run dir at build
time, greyed otherwise. A vanilla-JS filter bar (env / product / feed / from–to date) hides rows and
recomputes the stat tiles from visible rows; the page stays self-contained (works from `file://`).
Pure over the filesystem + the canonical Result schema; reuses the evidence stylesheet so the look
matches the reports.

    from ui.dashboard import build_dashboard
    build_dashboard("results")            # writes results/index.html
"""
from __future__ import annotations

import json
from pathlib import Path

from evidence.render import CSS, _cls, _esc

# The pipeline as an ordered strip — each stage of the flow, in order, keyed to the artifact it
# produces inside the run dir. Rendered as: Preseed › Run › Evidence › Quality › Metrics › Analysis,
# each a link (+ download) when the artifact exists, greyed when the stage hasn't produced it yet.
_PIPELINE = (
    ("Preseed", "preseed.html"),
    ("Run", "index.html"),
    ("Evidence", "bot-issues.html"),
    ("Quality", "quality-index.html"),
    ("Metrics", "report.html"),
    ("Analysis", "analysis.json"),
)

# dashboard-only additions on top of the shared evidence CSS (chips reuse .chip)
_DASH_CSS = """<style>
.pipe { display: inline-flex; align-items: center; flex-wrap: wrap; gap: 2px; margin-left: 8px; }
.pipe .chip { text-decoration: none; }
.pipe .chip.off { opacity: .4; }
.pipe .chip.dl { padding: 2px 5px; }
.pipe .sep { opacity: .35; margin: 0 2px; }
.filters { margin: 14px 0; display: flex; flex-wrap: wrap; gap: 10px; align-items: center;
           font-size: 13px; }
.filters select, .filters input { font: inherit; padding: 2px 4px; }
</style>"""


# a run folder is named "<env>_<product>_<feed>_<time>"
def _parse_cell(name: str) -> dict:
    parts = name.split("_")
    if len(parts) >= 4:
        env, product, feed, time = parts[0], parts[1], parts[2], parts[-1]
    else:
        env = product = feed = time = name
    return {"env": env, "product": product, "feed": feed, "time": time}


def _tally(run_dir: Path) -> dict:
    """Count PASS/FAIL/ERROR across a run's *.result.json (mirrors the runner's own tally rule)."""
    p = f = e = 0
    for rf in sorted(run_dir.glob("*.result.json")):
        try:
            doc = json.loads(rf.read_text(encoding="utf-8"))
        except Exception:
            e += 1
            continue
        v = doc.get("verdict", {}) or {}
        if doc.get("harness", {}).get("error") and not v.get("reached_determination"):
            e += 1
        elif v.get("matches_expected"):
            p += 1
        else:
            f += 1
    return {"pass": p, "fail": f, "error": e, "cases": p + f + e}


def collect_runs(results_root) -> list[dict]:
    """One record per run folder that has result files, newest date first."""
    root = Path(results_root)
    runs = []
    for date_dir in sorted((d for d in root.iterdir() if d.is_dir()), reverse=True):
        for cell in sorted((c for c in date_dir.iterdir() if c.is_dir()), reverse=True):
            if not any(cell.glob("*.result.json")):
                continue
            rec = {"date": date_dir.name, "cell": cell.name,
                   "rel_dir": f"{date_dir.name}/{cell.name}",
                   "docs": {fname: (cell / fname).is_file() for _, fname in _PIPELINE},
                   **_parse_cell(cell.name), **_tally(cell)}
            runs.append(rec)
    return runs


def _chips(r: dict) -> str:
    """The pipeline strip for one run: each stage a linked chip (+ download) when its artifact
    exists, greyed span when the stage hasn't run yet, joined by › into an ordered flow."""
    parts = []
    for i, (label, fname) in enumerate(_PIPELINE):
        if i:
            parts.append('<span class="sep">&rsaquo;</span>')
        if r["docs"].get(fname):
            href = _esc(f'{r["rel_dir"]}/{fname}')
            parts.append(f'<a class="chip" href="{href}">{_esc(label)}</a>'
                         f'<a class="chip dl" download href="{href}" title="Download {_esc(label)}">&#11015;</a>')
        else:
            parts.append(f'<span class="chip off">{_esc(label)}</span>')
    return f'<span class="pipe">{"".join(parts)}</span>'


def _options(values: list[str]) -> str:
    opts = ['<option value="all">all</option>']
    opts += [f'<option value="{_esc(v)}">{_esc(v)}</option>' for v in sorted(set(values))]
    return "".join(opts)


def _filter_bar(runs: list[dict]) -> str:
    return (
        '<div class="filters">'
        f'<label>Env <select id="f-env" onchange="applyFilters()">{_options([r["env"] for r in runs])}</select></label>'
        f'<label>Product <select id="f-product" onchange="applyFilters()">{_options([r["product"] for r in runs])}</select></label>'
        f'<label>Feed <select id="f-feed" onchange="applyFilters()">{_options([r["feed"] for r in runs])}</select></label>'
        '<label>From <input id="f-from" type="date" onchange="applyFilters()"></label>'
        '<label>To <input id="f-to" type="date" onchange="applyFilters()"></label>'
        "</div>"
    )


# vanilla inline JS: hide non-matching rows, recompute the stat tiles from visible rows only
_FILTER_JS = """<script>
function applyFilters() {
  var env = document.getElementById('f-env').value;
  var product = document.getElementById('f-product').value;
  var feed = document.getElementById('f-feed').value;
  var from = document.getElementById('f-from').value;
  var to = document.getElementById('f-to').value;
  var rows = document.querySelectorAll('tr[data-env]');
  var runs = 0, cases = 0, pass = 0;
  for (var i = 0; i < rows.length; i++) {
    var r = rows[i], d = r.getAttribute('data-date');
    var show = (env === 'all' || r.getAttribute('data-env') === env)
      && (product === 'all' || r.getAttribute('data-product') === product)
      && (feed === 'all' || r.getAttribute('data-feed') === feed)
      && (!from || d >= from) && (!to || d <= to);
    r.style.display = show ? '' : 'none';
    if (show) {
      runs += 1;
      cases += parseInt(r.getAttribute('data-cases'), 10) || 0;
      pass += parseInt(r.getAttribute('data-pass'), 10) || 0;
    }
  }
  document.getElementById('t-runs').textContent = runs;
  document.getElementById('t-cases').textContent = cases;
  document.getElementById('t-pass').textContent = pass;
  document.getElementById('t-notpass').textContent = cases - pass;
  document.getElementById('t-pct').textContent = (cases ? Math.round(100 * pass / cases) : 0) + '%';
}
</script>"""


def render_dashboard(runs: list[dict]) -> str:
    total_cases = sum(r["cases"] for r in runs)
    total_pass = sum(r["pass"] for r in runs)
    pct = round(100 * total_pass / total_cases) if total_cases else 0

    by_date: dict[str, list[dict]] = {}
    for r in runs:
        by_date.setdefault(r["date"], []).append(r)

    sections = []
    for date in sorted(by_date, reverse=True):
        rows = []
        for r in sorted(by_date[date], key=lambda x: x["time"], reverse=True):
            rate = round(100 * r["pass"] / r["cases"]) if r["cases"] else 0
            ok = r["fail"] == 0 and r["error"] == 0 and r["cases"] > 0
            rows.append(
                f'<tr data-env="{_esc(r["env"])}" data-product="{_esc(r["product"])}" '
                f'data-feed="{_esc(r["feed"])}" data-date="{_esc(r["date"])}" '
                f'data-cases="{r["cases"]}" data-pass="{r["pass"]}" '
                f'data-fail="{r["fail"]}" data-error="{r["error"]}">'
                f'<td>{_esc(r["env"])} · {_esc(r["product"])} · {_esc(r["feed"])}{_chips(r)}</td>'
                f'<td class="mono">{_esc(r["time"])}</td>'
                f'<td>{r["cases"]}</td>'
                f'<td class="pass">{r["pass"]}</td>'
                f'<td class="{"fail" if r["fail"] else ""}">{r["fail"]}</td>'
                f'<td>{r["error"]}</td>'
                f'<td class="{_cls(ok)}">{rate}%</td></tr>'
            )
        sections.append(
            f"<h2>{_esc(date)}</h2><table>"
            "<tr><th>Run (env · product · feed)</th><th>Time</th><th>Cases</th>"
            "<th>PASS</th><th>FAIL</th><th>ERR</th><th>Pass rate</th></tr>"
            f"{''.join(rows)}</table>"
        )

    return f"""<!doctype html>
<html><head><meta charset="utf-8"><title>CCT-QA-FRAMEWORK — Results</title>{CSS}{_DASH_CSS}</head>
<body>
<h1>CCT-QA-FRAMEWORK — Results</h1>
<div>
<span class="kpi"><b id="t-runs">{len(runs)}</b>runs</span>
<span class="kpi"><b id="t-cases">{total_cases}</b>cases</span>
<span class="kpi"><b class="pass" id="t-pass">{total_pass}</b>PASS</span>
<span class="kpi"><b class="fail" id="t-notpass">{total_cases - total_pass}</b>not-pass</span>
<span class="kpi"><b id="t-pct">{pct}%</b>overall</span>
</div>
{_filter_bar(runs)}
{''.join(sections) or '<p>No runs found under results/.</p>'}
{_FILTER_JS}
</body></html>"""


def build_dashboard(results_root="results", out=None) -> Path:
    """Scan `results_root`, render the dashboard, write it to `out` (default results_root/index.html)."""
    runs = collect_runs(results_root)
    html = render_dashboard(runs)
    out_path = Path(out) if out else (Path(results_root) / "index.html")
    out_path.write_text(html, encoding="utf-8")
    return out_path
