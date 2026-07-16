"""Render metrics.json into a self-contained HTML report.

One fixed template, driven only by the metrics dict — so every agent and every
future eval set produces a report with identical sections in identical order.
No generation timestamp is embedded: rerunning on the same folder yields a
byte-identical file.
"""

import html as _html
import json

# Palette: dataviz reference instance (light / dark selected per mode)
CSS = """
:root {
  --surface: #fcfcfb; --surface-2: #f4f3f0; --border: #e4e2dc;
  --ink: #0b0b0b; --ink-2: #52514e; --ink-3: #8a887f;
  --series: #2a78d6; --seq-250: #86b6ef; --seq-400: #3987e5; --seq-700: #0d366b;
  --good: #0ca30c; --warning: #fab219; --serious: #ec835a; --critical: #d03b3b;
}
@media (prefers-color-scheme: dark) {
  :root {
    --surface: #1a1a19; --surface-2: #242422; --border: #3a3936;
    --ink: #ffffff; --ink-2: #c3c2b7; --ink-3: #8a887f;
    --series: #3987e5; --seq-250: #184f95; --seq-400: #3987e5; --seq-700: #86b6ef;
  }
}
* { box-sizing: border-box; }
body { margin: 0; background: var(--surface); color: var(--ink);
  font: 14px/1.5 -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; }
.wrap { max-width: 1080px; margin: 0 auto; padding: 32px 24px 64px; }
h1 { font-size: 22px; margin: 0 0 4px; }
h2 { font-size: 16px; margin: 40px 0 4px; }
h1 + .sub, h2 + .sub { color: var(--ink-2); margin: 0 0 16px; font-size: 13px; }
.meta { color: var(--ink-2); font-size: 13px; margin-bottom: 24px; }
.meta b { color: var(--ink); font-weight: 600; }
.tiles { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 12px; }
.tile { background: var(--surface-2); border: 1px solid var(--border); border-radius: 8px; padding: 12px 14px; }
.tile .v { font-size: 26px; font-weight: 650; letter-spacing: -0.02em; }
.tile .l { color: var(--ink-2); font-size: 12px; margin-top: 2px; }
.tile .d { color: var(--ink-3); font-size: 11px; }
.tile .bar { height: 4px; border-radius: 2px; background: var(--border); margin-top: 8px; overflow: hidden; }
.tile .bar i { display: block; height: 100%; border-radius: 2px; background: var(--series); }
table { border-collapse: collapse; width: 100%; font-size: 13px; }
th { text-align: left; color: var(--ink-2); font-weight: 600; padding: 6px 10px; border-bottom: 1px solid var(--border); white-space: nowrap; }
td { padding: 6px 10px; border-bottom: 1px solid var(--border); vertical-align: middle; }
td.num, th.num { text-align: right; font-variant-numeric: tabular-nums; }
.cellbar { display: inline-block; width: 90px; height: 6px; background: var(--border); border-radius: 3px; vertical-align: middle; margin-left: 8px; overflow: hidden; }
.cellbar i { display: block; height: 100%; background: var(--series); border-radius: 3px; }
.scroll { overflow-x: auto; }
.badge { display: inline-flex; align-items: center; gap: 4px; font-size: 12px; font-weight: 600; }
.badge.pass { color: var(--good); }
.badge.fail { color: var(--critical); }
.matrix td.cell { text-align: center; min-width: 64px; font-variant-numeric: tabular-nums; }
.matrix td.diag { outline: 2px solid var(--series); outline-offset: -2px; }
.matrix th.rowh { text-align: right; }
.stage { display: grid; grid-template-columns: 240px 1fr 90px; gap: 10px; align-items: center; margin: 3px 0; font-size: 13px; }
.stage .sbar { height: 14px; background: var(--surface-2); border: 1px solid var(--border); border-radius: 4px; overflow: hidden; }
.stage .sbar i { display: block; height: 100%; background: var(--seq-400); border-radius: 3px 0 0 3px; }
.stage .pct { text-align: right; font-variant-numeric: tabular-nums; color: var(--ink-2); }
.anom { color: var(--ink); }
.filters { margin: 12px 0; display: flex; gap: 8px; flex-wrap: wrap; }
.filters button { background: var(--surface-2); color: var(--ink-2); border: 1px solid var(--border);
  border-radius: 16px; padding: 4px 12px; font-size: 12px; cursor: pointer; }
.filters button.on { background: var(--series); border-color: var(--series); color: #fff; }
#cases th, #cases td { padding: 4px 5px; font-size: 12px; }
#cases td:nth-child(11) { max-width: 170px; }
.note { color: var(--ink-3); font-size: 12px; margin-top: 6px; }
details { margin-top: 8px; }
summary { cursor: pointer; color: var(--ink-2); font-size: 13px; }
"""


def esc(s):
    return _html.escape(str(s))


def _pctf(rate_obj):
    if not rate_obj or rate_obj.get("rate") is None:
        return "—", ""
    r = rate_obj["rate"]
    return f"{r * 100:.1f}%", f"{rate_obj['num']}/{rate_obj['den']}"


def _tile(label, rate_obj, detail=None):
    v, frac = _pctf(rate_obj)
    w = (rate_obj.get("rate") or 0) * 100 if rate_obj else 0
    d = detail or frac
    return (f'<div class="tile"><div class="v">{esc(v)}</div><div class="l">{esc(label)}</div>'
            f'<div class="d">{esc(d)}</div><div class="bar"><i style="width:{w:.1f}%"></i></div></div>')


def _tile_plain(label, value, detail=""):
    return (f'<div class="tile"><div class="v">{esc(value)}</div><div class="l">{esc(label)}</div>'
            f'<div class="d">{esc(detail)}</div></div>')


def _slice_table(title, sub, bundle_map):
    rows = []
    for key, b in bundle_map.items():
        gs, gsf = _pctf(b["goal_success"])
        rs, _ = _pctf(b["rescored_success"])
        da, _ = _pctf(b["decision_accuracy"])
        td, _ = _pctf(b["terminal_decision"])
        cr, _ = _pctf(b["clean_run"])
        tj = f"{b['trajectory_mean'] * 100:.0f}%" if b.get("trajectory_mean") is not None else "—"
        w = (b["goal_success"]["rate"] or 0) * 100
        rows.append(
            f"<tr><td>{esc(key)}</td><td class='num'>{b['n']}</td>"
            f"<td class='num'>{gs}<span class='cellbar'><i style='width:{w:.0f}%'></i></span></td>"
            f"<td class='num'>{esc(gsf)}</td><td class='num'>{rs}</td><td class='num'>{da}</td>"
            f"<td class='num'>{td}</td><td class='num'>{tj}</td><td class='num'>{cr}</td></tr>")
    return (f"<h2>{esc(title)}</h2><p class='sub'>{esc(sub)}</p><div class='scroll'><table>"
            "<tr><th>Slice</th><th class='num'>Cases</th><th class='num'>Goal success (judged)</th>"
            "<th class='num'>Pass/total</th><th class='num'>Re-scored</th><th class='num'>Decision accuracy</th>"
            "<th class='num'>Terminal decision</th><th class='num'>Trajectory</th>"
            "<th class='num'>Clean runs</th></tr>" + "".join(rows) + "</table></div>")


def _seq_color(frac):
    """Interpolate the sequential blue ramp (light mode values; dark handled by opacity floor)."""
    # steps 100..700 light ramp endpoints for background heat
    return f"color-mix(in srgb, var(--seq-400) {max(8, frac * 100):.0f}%, var(--surface-2))"


def render_report(m, stage_order, stage_labels, anomaly_labels, source_dir=""):
    h = m["headline"]
    parts = []
    parts.append(f"<h1>Agentic QA Evaluation — {esc(m['agent'])}</h1>")
    fam_counts = {}
    for c in m["cases"]:
        fam_counts[c["family"]] = fam_counts.get(c["family"], 0) + 1
    fams = " · ".join(f"{k} {v}" for k, v in sorted(fam_counts.items()))
    parts.append(
        f"<div class='meta'>Environment <b>{esc(m['env'])}</b> · <b>{m['n_cases']}</b> test cases "
        f"({esc(fams)}) · metrics schema <b>v{esc(m['schema_version'])}</b>"
        + (f" · source <b>{esc(source_dir)}</b>" if source_dir else "") + "</div>")

    # 1. headline tiles
    parts.append("<h2>1 · Headline</h2><p class='sub'>End-to-end outcomes across the whole suite.</p>")
    dur = m["ops"]["duration_s"]
    parts.append("<div class='tiles'>"
                 + _tile("Goal success (judged)", h["goal_success_rate"])
                 + _tile("Goal success (re-scored)", h["rescored_success_rate"])
                 + _tile("Judge agreement", h["judge_agreement"])
                 + _tile("Decision accuracy", h["decision_accuracy"])
                 + _tile("Intent recognition", h["intent_recognition_rate"])
                 + _tile_plain("Trajectory match (mean)",
                               f"{h['trajectory_match_mean'] * 100:.1f}%" if h.get("trajectory_match_mean") is not None else "—",
                               "ordered stage coverage")
                 + _tile("Terminal decision rate", h["terminal_decision_rate"])
                 + _tile("Amount accuracy", h["amount_accuracy"])
                 + _tile("Clean runs (no harness error)", h["clean_run_rate"])
                 + _tile_plain("Median duration", f"{dur['p50']:.0f}s" if dur["p50"] is not None else "—",
                               f"p90 {dur['p90']:.0f}s" if dur["p90"] is not None else "")
                 + "</div>")
    parts.append("<p class='note'>Goal success (judged) = the QA agent's own end-to-end verdict. "
                 "Goal success (re-scored) = deterministic rule: normalized bot decision equals the scripted expectation "
                 "AND the quoted amount matches (currency-aware, ±2%). "
                 "Judge agreement = share of cases where the two verdicts coincide — a consistency check on the agent's LLM judge. "
                 "Decision accuracy = decision match ignoring amounts. "
                 "Intent recognition = the bot eventually routed the request into the claim flow; "
                 "first-try routing failures show up under the intent-misroute anomaly. "
                 "Terminal decision = bot rendered a final determination rather than stalling or escalating. "
                 "Clean runs = harness completed without a runtime error (a test-agent metric, not a bot metric).</p>")

    # 2. confusion matrix
    labels = m["confusion"]["labels"]
    mat = m["confusion"]["matrix"]
    total = sum(sum(r) for r in mat) or 1
    rows = ["<tr><th class='rowh'>expected ↓ / actual →</th>"
            + "".join(f"<th class='num'>{esc(l)}</th>" for l in labels) + "<th class='num'>Σ</th></tr>"]
    for i, l in enumerate(labels):
        if sum(mat[i]) == 0:
            continue
        cells = []
        for j, v in enumerate(mat[i]):
            heat = _seq_color(v / total * 4) if v else "transparent"
            diag = " diag" if i == j and v else ""
            cells.append(f"<td class='cell{diag}' style='background:{heat}'>{v or ''}</td>")
        rows.append(f"<tr><th class='rowh'>{esc(l)}</th>{''.join(cells)}<td class='num'>{sum(mat[i])}</td></tr>")
    parts.append("<h2>2 · Decision outcomes — expected vs. actual</h2>"
                 "<p class='sub'>Rows are the scripted expectation, columns what the bot concluded. "
                 "Outlined diagonal = correct decisions.</p>"
                 f"<div class='scroll'><table class='matrix'>{''.join(rows)}</table></div>")

    # 3. per-intent slices
    parts.append(_slice_table("3a · By test family (intent group)",
                              "CORE = standard flight-delay claims, ED = edge/data variants, PAY = payment variants.",
                              m["slices"]["family"]))
    parts.append(_slice_table("3b · By compensation regime", "APPR (Canada), EU261, ASL (Israel), mixed itineraries.",
                              m["slices"]["regime"]))
    parts.append(_slice_table("3c · By expected outcome", "How the bot performs on should-pay vs. should-refuse scenarios.",
                              m["slices"]["expected_status"]))
    parts.append(_slice_table("3d · By decision class", "Scripted decision class from the system code.",
                              m["slices"]["decision_class"]))
    parts.append(_slice_table("3e · By scenario code family", "Prefix of the scripted system code (regime + decision class).",
                              m["slices"]["system_code_prefix"]))

    # 4. checks
    crow = []
    for key, c in m["checks"].items():
        w = c["rate"] * 100
        crow.append(f"<tr><td>{esc(key)}</td><td class='num'>{c['cases']}</td><td class='num'>{c['pass']}/{c['total']}</td>"
                    f"<td class='num'>{c['rate'] * 100:.1f}%<span class='cellbar'><i style='width:{w:.0f}%'></i></span></td></tr>")
    parts.append("<h2>4 · Assertion accuracy by canonical check</h2>"
                 "<p class='sub'>The agents' free-text check names normalized into a fixed taxonomy, "
                 "so the same rows appear on every report.</p>"
                 "<div class='scroll'><table><tr><th>Canonical check</th><th class='num'>Cases</th>"
                 "<th class='num'>Passed/total</th><th class='num'>Pass rate</th></tr>"
                 + "".join(crow) + "</table></div>")

    # 5. trajectory funnel
    parts.append("<h2>5 · Business-flow trajectory</h2>"
                 "<p class='sub'>Share of conversations that reached each canonical flow stage "
                 "(deterministic detectors over the transcripts).</p>")
    cov = m["trajectory"]["stage_coverage"]
    srows = []
    for s in stage_order:
        r = cov.get(s)
        pct = (r["rate"] or 0) * 100 if r else 0
        frac = f"{r['num']}/{r['den']}" if r else "0"
        srows.append(f"<div class='stage'><div>{esc(stage_labels.get(s, s))}</div>"
                     f"<div class='sbar'><i style='width:{pct:.1f}%'></i></div>"
                     f"<div class='pct' title='{esc(frac)}'>{pct:.1f}%</div></div>")
    parts.append("".join(srows))

    an = m["trajectory"]["anomaly_rates"]
    if an:
        arows = "".join(
            f"<tr><td class='anom'>⚠ {esc(anomaly_labels.get(k, k))}</td>"
            f"<td class='num'>{v['num']}</td><td class='num'>{(v['rate'] or 0) * 100:.1f}%</td></tr>"
            for k, v in sorted(an.items(), key=lambda kv: -(kv[1]['num'])))
        parts.append("<h2>6 · Conversation anomalies</h2>"
                     "<p class='sub'>Off-flow events detected in transcripts; each can hit multiple times per suite.</p>"
                     "<div class='scroll'><table><tr><th>Anomaly</th><th class='num'>Conversations</th>"
                     f"<th class='num'>Rate</th></tr>{arows}</table></div>")

    # 7. ops
    ops = m["ops"]
    erows = "".join(f"<tr><td>{esc(k)}</td><td class='num'>{v}</td></tr>" for k, v in ops["error_buckets"].items()) \
            or "<tr><td colspan='2'>none</td></tr>"
    tn = ops["turns"]
    parts.append("<h2>7 · Operational profile</h2><p class='sub'>Latency, conversation length, harness errors.</p>"
                 "<div class='tiles'>"
                 + _tile_plain("Duration p50 / p90",
                               f"{ops['duration_s']['p50']:.0f}s / {ops['duration_s']['p90']:.0f}s"
                               if ops['duration_s']['p50'] is not None else "—",
                               f"mean {ops['duration_s']['mean']}s")
                 + _tile_plain("Turns p50 / p90",
                               (f"{tn['p50']:.0f} / {tn['p90']:.0f}" if tn["p50"] is not None else "n/a"),
                               (f"mean {tn['mean']}" if tn["mean"] is not None else "not captured by this agent"))
                 + "</div>"
                 "<h3 style='font-size:14px;margin:16px 0 4px'>Harness error buckets</h3>"
                 f"<div class='scroll'><table><tr><th>Bucket</th><th class='num'>Runs</th></tr>{erows}</table></div>")

    # 8. per-case appendix
    body_rows = []
    for c in m["cases"]:
        badge = ("<span class='badge pass'>✓ PASS</span>" if c["overall_pass"] else "<span class='badge fail'>✕ FAIL</span>")
        rbadge = ("<span class='badge pass'>✓</span>" if c["rescored_pass"] else "<span class='badge fail'>✕</span>")
        tj = f"{c['trajectory_score'] * 100:.0f}%" if c["trajectory_score"] is not None else "—"
        anoms = ", ".join(anomaly_labels.get(a, a) for a in c["anomalies"]) or ""
        disagree = c["overall_pass"] != c["rescored_pass"]
        cls = (("f" if not c["overall_pass"] else "p")
               + (" a" if c["anomalies"] else "") + (" e" if c["run_error"] else "")
               + (" d" if disagree else ""))
        body_rows.append(
            f"<tr class='{cls}'><td>{esc(c['test_id'])}</td><td>{esc(c['family'])}</td><td>{esc(c['regime'])}</td>"
            f"<td>{esc(c['expected_status'])}</td><td>{esc(c['actual_status'])}</td>"
            f"<td class='num'>{esc(c['expected_amount'])}</td><td class='num'>{esc(c['actual_amount'])}</td>"
            f"<td>{badge}</td><td>{rbadge}{' ⚠' if disagree else ''}</td><td class='num'>{tj}</td><td>{esc(anoms)}</td>"
            f"<td class='num'>{c['duration_s'] if c['duration_s'] is not None else '—'}</td></tr>")
    parts.append("<h2>8 · Per-case results</h2>"
                 "<div class='filters'>"
                 "<button class='on' data-f='all'>All</button>"
                 "<button data-f='f'>Failures</button>"
                 "<button data-f='d'>Judge disagreements</button>"
                 "<button data-f='a'>With anomalies</button>"
                 "<button data-f='e'>Harness errors</button></div>"
                 "<div class='scroll'><table id='cases'>"
                 "<tr><th>Test</th><th>Family</th><th>Regime</th><th>Expected</th><th>Actual</th>"
                 "<th class='num'>Exp. amount</th><th class='num'>Bot amount</th><th>Judged</th><th>Re-scored</th>"
                 "<th class='num'>Trajectory</th><th>Anomalies</th><th class='num'>Dur (s)</th></tr>"
                 + "".join(body_rows) + "</table></div>")

    script = """
document.querySelectorAll('.filters button').forEach(b => b.addEventListener('click', () => {
  document.querySelectorAll('.filters button').forEach(x => x.classList.remove('on'));
  b.classList.add('on');
  const f = b.dataset.f;
  let shown = 0;
  document.querySelectorAll('#cases tr').forEach((tr, i) => {
    if (i === 0 || tr.id === 'empty-row') return;
    const show = (f === 'all' || tr.classList.contains(f));
    tr.style.display = show ? '' : 'none';
    if (show) shown++;
  });
  let er = document.getElementById('empty-row');
  if (!er) {
    er = document.createElement('tr');
    er.id = 'empty-row';
    const cols = document.querySelectorAll('#cases tr th').length;
    er.innerHTML = `<td colspan="${cols}" style="color:var(--ink-3);padding:14px">No cases match this filter.</td>`;
    document.querySelector('#cases').appendChild(er);
  }
  er.style.display = shown ? 'none' : '';
}));
"""
    return ("<!doctype html><html><head><meta charset='utf-8'>"
            f"<title>QA Eval — {esc(m['agent'])}</title>"
            "<meta name='viewport' content='width=device-width, initial-scale=1'>"
            f"<style>{CSS}</style></head><body><div class='wrap'>"
            + "".join(parts) + f"</div><script>{script}</script></body></html>")


def render_comparison(metrics_list, stage_order, stage_labels, anomaly_labels):
    """Side-by-side view over N metrics.json payloads sharing the same schema."""
    cols = "".join(f"<th class='num'>{esc(m['agent'])}<br><span style='font-weight:400;color:var(--ink-2)'>"
                   f"{esc(m['env'])} · {m['n_cases']} cases</span></th>" for m in metrics_list)

    def row(label, fn, fmt=lambda v: f"{v * 100:.1f}%" if v is not None else "—"):
        tds = "".join(f"<td class='num'>{fmt(fn(m))}</td>" for m in metrics_list)
        return f"<tr><td>{esc(label)}</td>{tds}</tr>"

    kpis = [
        ("Goal success (judged)", lambda m: m["headline"]["goal_success_rate"]["rate"]),
        ("Goal success (re-scored)", lambda m: m["headline"]["rescored_success_rate"]["rate"]),
        ("Judge agreement", lambda m: m["headline"]["judge_agreement"]["rate"]),
        ("Decision accuracy", lambda m: m["headline"]["decision_accuracy"]["rate"]),
        ("Terminal decision rate", lambda m: m["headline"]["terminal_decision_rate"]["rate"]),
        ("Intent recognition", lambda m: m["headline"]["intent_recognition_rate"]["rate"]),
        ("Trajectory match (mean)", lambda m: m["headline"]["trajectory_match_mean"]),
        ("Amount accuracy", lambda m: m["headline"]["amount_accuracy"]["rate"]),
        ("Clean run rate", lambda m: m["headline"]["clean_run_rate"]["rate"]),
    ]
    krows = "".join(row(l, f) for l, f in kpis)
    krows += row("Median duration (s)", lambda m: m["ops"]["duration_s"]["p50"],
                 fmt=lambda v: f"{v:.0f}" if v is not None else "—")

    # per-family goal success
    fams = sorted({f for m in metrics_list for f in m["slices"]["family"]})
    frows = ""
    for fam in fams:
        frows += row(f"Goal success · {fam}",
                     lambda m, fam=fam: (m["slices"]["family"].get(fam) or {}).get("goal_success", {}).get("rate"))
    regs = sorted({r for m in metrics_list for r in m["slices"]["regime"]})
    rrows = ""
    for reg in regs:
        rrows += row(f"Goal success · {reg}",
                     lambda m, reg=reg: (m["slices"]["regime"].get(reg) or {}).get("goal_success", {}).get("rate"))

    # stage coverage side by side
    srows = ""
    for s in stage_order:
        tds = ""
        for m in metrics_list:
            r = m["trajectory"]["stage_coverage"].get(s)
            pct = (r["rate"] or 0) * 100 if r else 0
            tds += (f"<td><div class='sbar' style='height:12px;background:var(--surface-2);"
                    f"border:1px solid var(--border);border-radius:4px;overflow:hidden'>"
                    f"<i style='display:block;height:100%;width:{pct:.0f}%;background:var(--seq-400)'></i></div>"
                    f"<span style='font-size:11px;color:var(--ink-2)'>{pct:.0f}%</span></td>")
        srows += f"<tr><td>{esc(stage_labels.get(s, s))}</td>{tds}</tr>"

    return ("<!doctype html><html><head><meta charset='utf-8'><title>QA Eval — comparison</title>"
            "<meta name='viewport' content='width=device-width, initial-scale=1'>"
            f"<style>{CSS}</style></head><body><div class='wrap'>"
            "<h1>Agentic QA Evaluation — side-by-side</h1>"
            "<p class='sub'>Same metrics schema per column; environments differ, so read differences as "
            "environment+run differences, not agent quality alone.</p>"
            f"<h2>Headline</h2><div class='scroll'><table><tr><th>Metric</th>{cols}</tr>{krows}</table></div>"
            f"<h2>Goal success by family</h2><div class='scroll'><table><tr><th></th>{cols}</tr>{frows}</table></div>"
            f"<h2>Goal success by regime</h2><div class='scroll'><table><tr><th></th>{cols}</tr>{rrows}</table></div>"
            f"<h2>Stage coverage</h2><div class='scroll'><table><tr><th>Stage</th>{cols}</tr>{srows}</table></div>"
            "</div></body></html>")


def write_json(path, obj):
    with open(path, "w") as f:
        json.dump(obj, f, indent=1, sort_keys=True)
        f.write("\n")
