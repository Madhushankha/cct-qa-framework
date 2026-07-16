"""CLI: build consistent eval reports from one or more QA-agent output folders.

    python3 -m evalkit.run_eval agent-alpha agent-bravo --out-dir reports

For each folder it emits:
    reports/<folder>/metrics.json   stable machine-readable metrics (schema-versioned)
    reports/<folder>/report.html    the standard report (same sections every run)
and, when given 2+ folders:
    reports/comparison.html         side-by-side view

Adding a new agent's output format = one adapter in adapters.py. Everything else
(taxonomy, metrics, report) is shared, which is what keeps reports consistent
across agents and across eval sets.
"""

import argparse
import os
import sys

from . import taxonomy
from .adapters import ADAPTERS, detect_adapter
from .metrics import compute_metrics
from .report import render_comparison, render_report, write_json
from .trajectory import annotate_trajectory


def evaluate_dir(dir_path, out_dir):
    adapter_key = detect_adapter(dir_path)
    records = ADAPTERS[adapter_key](dir_path, taxonomy.canonicalize_check)
    if not records:
        raise SystemExit(f"No records parsed from {dir_path}")
    for r in records:
        bucket, fatal = taxonomy.bucket_error(r["run_error"])
        r["error_bucket"], r["error_fatal"] = bucket, fatal
        annotate_trajectory(r, fmt=adapter_key)
    m = compute_metrics(records)
    name = os.path.basename(os.path.normpath(dir_path))
    dest = os.path.join(out_dir, name)
    os.makedirs(dest, exist_ok=True)
    write_json(os.path.join(dest, "metrics.json"), m)
    html = render_report(m, taxonomy.STAGE_ORDER, taxonomy.STAGE_LABELS, taxonomy.ANOMALY_LABELS,
                         source_dir=dir_path)
    with open(os.path.join(dest, "report.html"), "w") as f:
        f.write(html)
    print(f"[{name}] {m['n_cases']} cases -> {dest}/report.html "
          f"(judged {m['headline']['goal_success_rate']['rate']:.1%}, "
          f"re-scored {m['headline']['rescored_success_rate']['rate']:.1%})")
    return m


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("dirs", nargs="+", help="agent output folders")
    ap.add_argument("--out-dir", default="reports")
    args = ap.parse_args(argv)

    all_metrics = [evaluate_dir(d, args.out_dir) for d in args.dirs]
    if len(all_metrics) > 1:
        cmp_html = render_comparison(all_metrics, taxonomy.STAGE_ORDER, taxonomy.STAGE_LABELS,
                                     taxonomy.ANOMALY_LABELS)
        path = os.path.join(args.out_dir, "comparison.html")
        with open(path, "w") as f:
            f.write(cmp_html)
        print(f"[comparison] -> {path}")


if __name__ == "__main__":
    main(sys.argv[1:])
