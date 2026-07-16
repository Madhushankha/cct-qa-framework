"""Evidence-based coverage matrix per use case, generated from metrics.json.

    python3 -m evalkit.coverage reports/agent-bravo/metrics.json

Emits coverage.csv + coverage.html next to the metrics file. One row per
scenario-code family (the suite's finest designed use-case granularity), with:
labeled-example count, gap to the golden-dataset target, measured scores,
dominant failure modes mined from the failing cases, and a status where
"done" means measured AND passing — never just "code merged".

Use cases the suite doesn't exercise at all cannot appear here; add scripted
cases for them and rerun. The matrix only ever claims what was measured.
"""

import argparse
import csv
import json
import os
import sys
from collections import Counter, defaultdict

GOLDEN_TARGET = 50          # labeled examples per use case for the CI golden set
DONE_MIN_N = 10             # minimum sample before a use case can be "done"
DONE_MIN_SCORE = 0.90       # re-scored success needed for "done"

REGIME_MEANING = {"APPR": "APPR (Canada)", "EU": "EU261/UK261", "ASL": "ASL (Israel)",
                  "MIXED": "Mixed itinerary", "DUP": "Duplicate claim"}
CLASS_MEANING = {"EL": "should pay", "NE": "should refuse", "ND": "should abstain",
                 "PE": "pending claim", "DB": "denied boarding"}


def describe_prefix(prefix):
    parts = prefix.split("-")
    if len(parts) < 3:
        return prefix
    return f"{REGIME_MEANING.get(parts[1], parts[1])} · {CLASS_MEANING.get(parts[2], parts[2])}"


def build_rows(m, anomaly_labels):
    groups = defaultdict(list)
    for c in m["cases"]:
        groups[c["system_code_prefix"]].append(c)

    rows = []
    for prefix in sorted(groups):
        cases = groups[prefix]
        n = len(cases)
        rescored = sum(1 for c in cases if c["rescored_pass"])
        judged = sum(1 for c in cases if c["overall_pass"])
        decision = sum(1 for c in cases if c["actual_status"] == c["expected_status"])
        traj = [c["trajectory_score"] for c in cases if c["trajectory_score"] is not None]

        failing = [c for c in cases if not c["rescored_pass"]]
        wrong_outcomes = Counter(f"{c['expected_status']}→{c['actual_status']}"
                                 for c in failing if c["actual_status"] != c["expected_status"])
        anoms = Counter(a for c in failing for a in c["anomalies"])
        modes = [f"{k} ({v})" for k, v in wrong_outcomes.most_common(2)]
        modes += [f"{anomaly_labels.get(k, k)} ({v})" for k, v in anoms.most_common(2)]

        score = rescored / n
        if n >= DONE_MIN_N and score >= DONE_MIN_SCORE:
            status = "done (measured & passing)"
        elif n < DONE_MIN_N:
            status = "under-sampled"
        else:
            status = "partial (measured, failing)"

        rows.append({
            "use_case": prefix,
            "meaning": describe_prefix(prefix),
            "examples": n,
            "gap_to_golden_50": max(0, GOLDEN_TARGET - n),
            "rescored_success": round(score, 3),
            "judged_success": round(judged / n, 3),
            "decision_accuracy": round(decision / n, 3),
            "trajectory_mean": round(sum(traj) / len(traj), 3) if traj else None,
            "top_failure_modes": "; ".join(modes) if modes else "—",
            "status": status,
        })
    return rows


def write_csv(rows, path):
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)


def write_html(rows, m, path):
    from .report import CSS, esc
    status_badge = {
        "done (measured & passing)": "<span class='badge pass'>✓ done</span>",
        "partial (measured, failing)": "<span class='badge fail'>✕ partial</span>",
        "under-sampled": "<span class='badge' style='color:var(--warning)'>▲ under-sampled</span>",
    }
    body = []
    for r in rows:
        tj = f"{r['trajectory_mean'] * 100:.0f}%" if r["trajectory_mean"] is not None else "—"
        body.append(
            f"<tr><td><b>{esc(r['use_case'])}</b><br><span style='color:var(--ink-2);font-size:12px'>{esc(r['meaning'])}</span></td>"
            f"<td>{status_badge[r['status']]}</td>"
            f"<td class='num'>{r['examples']}</td><td class='num'>{r['gap_to_golden_50'] or '—'}</td>"
            f"<td class='num'>{r['rescored_success'] * 100:.1f}%</td><td class='num'>{r['judged_success'] * 100:.1f}%</td>"
            f"<td class='num'>{r['decision_accuracy'] * 100:.1f}%</td><td class='num'>{tj}</td>"
            f"<td style='max-width:260px'>{esc(r['top_failure_modes'])}</td></tr>")
    done = sum(1 for r in rows if r["status"].startswith("done"))
    partial = sum(1 for r in rows if r["status"].startswith("partial"))
    under = len(rows) - done - partial
    html = ("<!doctype html><html><head><meta charset='utf-8'>"
            f"<title>Coverage matrix — {esc(m['agent'])}</title>"
            "<meta name='viewport' content='width=device-width, initial-scale=1'>"
            f"<style>{CSS}</style></head><body><div class='wrap'>"
            f"<h1>Use-case coverage matrix — {esc(m['agent'])}</h1>"
            f"<div class='meta'>Environment <b>{esc(m['env'])}</b> · {m['n_cases']} measured cases · "
            f"<b>{done}</b> done · <b>{partial}</b> partial · <b>{under}</b> under-sampled · "
            f"status rule: done = ≥{DONE_MIN_N} examples AND ≥{DONE_MIN_SCORE:.0%} re-scored success</div>"
            "<p class='note'>Evidence-based: every number is measured from executed sessions. "
            "'Gap to golden 50' = additional labeled examples needed for the per-intent CI golden set. "
            "Use cases with no scripted tests cannot appear here — absence from this table is itself a coverage gap.</p>"
            "<div class='scroll'><table><tr><th>Use case</th><th>Status</th><th class='num'>Examples</th>"
            "<th class='num'>Gap to golden 50</th><th class='num'>Re-scored success</th>"
            "<th class='num'>Judged success</th><th class='num'>Decision accuracy</th>"
            "<th class='num'>Trajectory</th><th>Top failure modes (among failing cases)</th></tr>"
            + "".join(body) + "</table></div></div></body></html>")
    with open(path, "w") as f:
        f.write(html)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("metrics", help="path to a metrics.json produced by evalkit.run_eval")
    args = ap.parse_args(argv)

    from . import taxonomy
    m = json.load(open(args.metrics))
    rows = build_rows(m, taxonomy.ANOMALY_LABELS)
    out_dir = os.path.dirname(os.path.abspath(args.metrics))
    write_csv(rows, os.path.join(out_dir, "coverage.csv"))
    write_html(rows, m, os.path.join(out_dir, "coverage.html"))
    done = sum(1 for r in rows if r["status"].startswith("done"))
    print(f"[{m['agent']}] {len(rows)} use cases ({done} done) -> {out_dir}/coverage.html + coverage.csv")


if __name__ == "__main__":
    main(sys.argv[1:])
