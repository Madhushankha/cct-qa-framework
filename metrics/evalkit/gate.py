"""CI eval gate: pass/fail a metrics.json against absolute floors and a baseline.

    # in CI, after `python3 -m evalkit.run_eval <agent-out-dir> --out-dir reports`:
    python3 -m evalkit.gate reports/<agent>/metrics.json --baseline baselines/<agent>.json

Exit code 0 = gate passes; 1 = gate fails (block the merge). Two kinds of checks:

1. Absolute floors — minimum acceptable values regardless of history.
2. Regression vs baseline — any watched metric dropping more than the tolerance
   below the last known-good run fails, even if still above the floor.

Promote a known-good run with --update-baseline (typically on merge to main).
Per-slice regressions are checked for slices with at least --min-n cases, so a
2-case slice can't flap the gate.
"""

import argparse
import json
import os
import sys

# metric key -> (path into metrics.json, absolute floor)
WATCHED = {
    "rescored_success_rate": (("headline", "rescored_success_rate", "rate"), 0.70),
    "decision_accuracy": (("headline", "decision_accuracy", "rate"), 0.80),
    "intent_recognition_rate": (("headline", "intent_recognition_rate", "rate"), 0.95),
    "trajectory_match_mean": (("headline", "trajectory_match_mean"), 0.75),
    "amount_accuracy": (("headline", "amount_accuracy", "rate"), 0.75),
}
REGRESSION_TOLERANCE = 0.02  # absolute drop allowed vs baseline
MIN_SLICE_N = 10


def _get(d, path):
    for k in path:
        d = d.get(k) if isinstance(d, dict) else None
        if d is None:
            return None
    return d


def _slice_rates(m, min_n):
    out = {}
    for dim in ("family", "regime", "expected_status"):
        for key, b in m["slices"][dim].items():
            if b["n"] >= min_n and b["rescored_success"]["rate"] is not None:
                out[f"{dim}:{key}"] = b["rescored_success"]["rate"]
    return out


def run_gate(metrics_path, baseline_path=None, tolerance=REGRESSION_TOLERANCE,
             min_n=MIN_SLICE_N, update_baseline=False):
    m = json.load(open(metrics_path))
    failures, lines = [], []

    lines.append(f"eval gate · {m['agent']} · {m['n_cases']} cases · schema v{m['schema_version']}")

    for name, (path, floor) in WATCHED.items():
        val = _get(m, path)
        if val is None:
            failures.append(f"{name}: missing from metrics")
            continue
        ok = val >= floor
        lines.append(f"  [{'PASS' if ok else 'FAIL'}] {name} = {val:.3f} (floor {floor:.2f})")
        if not ok:
            failures.append(f"{name} {val:.3f} below floor {floor:.2f}")

    baseline = None
    if baseline_path and os.path.exists(baseline_path):
        baseline = json.load(open(baseline_path))
        if baseline.get("schema_version") != m.get("schema_version"):
            lines.append(f"  [WARN] baseline schema v{baseline.get('schema_version')} != current v{m.get('schema_version')} — regression checks skipped")
        else:
            for name, (path, _) in WATCHED.items():
                cur, base = _get(m, path), _get(baseline, path)
                if cur is None or base is None:
                    continue
                ok = cur >= base - tolerance
                lines.append(f"  [{'PASS' if ok else 'FAIL'}] {name} vs baseline: {cur:.3f} vs {base:.3f}")
                if not ok:
                    failures.append(f"{name} regressed {base:.3f} -> {cur:.3f} (tolerance {tolerance})")
            cur_slices, base_slices = _slice_rates(m, min_n), _slice_rates(baseline, min_n)
            for key in sorted(set(cur_slices) & set(base_slices)):
                cur, base = cur_slices[key], base_slices[key]
                if cur < base - tolerance:
                    failures.append(f"slice {key} re-scored success regressed {base:.3f} -> {cur:.3f}")
                    lines.append(f"  [FAIL] slice {key}: {cur:.3f} vs baseline {base:.3f}")
    elif baseline_path:
        lines.append(f"  [WARN] no baseline at {baseline_path} — floors only")

    verdict = "GATE PASS" if not failures else "GATE FAIL"
    lines.append(verdict + ("" if not failures else f" — {len(failures)} check(s) failed"))
    for f in failures:
        lines.append(f"    · {f}")

    if update_baseline and baseline_path and not failures:
        os.makedirs(os.path.dirname(baseline_path) or ".", exist_ok=True)
        with open(baseline_path, "w") as f:
            json.dump(m, f, indent=1, sort_keys=True)
        lines.append(f"baseline updated -> {baseline_path}")

    return len(failures) == 0, "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("metrics", help="path to a metrics.json produced by evalkit.run_eval")
    ap.add_argument("--baseline", help="path to the last known-good metrics.json")
    ap.add_argument("--tolerance", type=float, default=REGRESSION_TOLERANCE)
    ap.add_argument("--min-n", type=int, default=MIN_SLICE_N)
    ap.add_argument("--update-baseline", action="store_true",
                    help="promote this run to baseline if the gate passes")
    args = ap.parse_args(argv)
    ok, report = run_gate(args.metrics, args.baseline, args.tolerance, args.min_n, args.update_baseline)
    print(report)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main(sys.argv[1:])
