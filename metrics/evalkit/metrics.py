"""Metric computation over normalized EvalRecords.

Everything here is deterministic arithmetic over the normalized records —
no LLM calls, no sampling — so rerunning on the same folder always yields
byte-identical metrics.json, and rerunning on a new eval set yields the
same schema.
"""

import statistics
from collections import Counter, defaultdict

SCHEMA_VERSION = "1.1"

# Outcomes we consider "the bot rendered a terminal decision" (vs stalled/escalated/unknown)
TERMINAL_DECISIONS = {"ELIGIBLE", "NOT_ELIGIBLE", "NO_DETERMINATION"}
STATUS_ORDER = ["ELIGIBLE", "NOT_ELIGIBLE", "NO_DETERMINATION", "PENDING", "ESCALATED", "UNRESOLVED", "UNKNOWN"]


def _rate(num, den):
    return {"num": num, "den": den, "rate": round(num / den, 4) if den else None}


def _amounts_match(rec, tol=0.02):
    """Expected vs actual amount, tolerant of ordering ('CAD 400' vs '400 CAD') and
    of small drift on same-currency quotes ('260 GBP' vs '259.01 GBP'). A converted
    dual-currency quote like '259.01 GBP (485.12 CAD)' matches on either pair, but
    cross-currency values are never auto-equated without a same-currency anchor."""
    exp = rec["expected_amount"]
    from .adapters import parse_amounts
    # zero quotes ('CAD 0') mean "no compensation" — same as quoting nothing
    acts = [p for p in parse_amounts(rec["actual_amount_raw"]) if p[1] != 0]
    if exp is None:
        return not acts
    if not acts:
        return False
    for ccy, val in acts:
        if ccy == exp[0] and abs(exp[1] - val) / exp[1] <= tol:
            return True
    return False


def _rescored_pass(rec):
    """Deterministic re-score, independent of the agent's own (LLM) judge:
    the bot's normalized decision equals the scripted expectation AND the
    quoted amount matches. Stable across reruns and across agents.

    Expected-PENDING scenarios: agents' status extraction never emits PENDING,
    so accept ESCALATED/NO_DETERMINATION as the scripted pending state when the
    transcript shows a submitted claim with a case reference and no amount."""
    if rec["actual_status"] == rec["expected_status"] and _amounts_match(rec):
        return True
    if rec["expected_status"] == "PENDING" and rec["actual_status"] in ("ESCALATED", "NO_DETERMINATION"):
        traj = rec.get("trajectory") or {}
        if "case_reference_issued" in (traj.get("stages_hit") or []):
            return _amounts_match(rec)
    return False


def _clean(rec):
    """A run counts as clean unless its harness error was fatal to the flow.
    (Some agents log cosmetic end-of-run errors on otherwise complete runs.)"""
    return not rec["run_error"] or not rec.get("error_fatal", True)


def _slice_bundle(recs):
    n = len(recs)
    ok = [r for r in recs if r["overall_pass"]]
    rescored = [r for r in recs if _rescored_pass(r)]
    no_err = [r for r in recs if _clean(r)]
    terminal = [r for r in recs if r["actual_status"] in TERMINAL_DECISIONS]
    correct_decision = [r for r in recs if r["actual_status"] == r["expected_status"]]
    traj = [r["trajectory"]["score"] for r in recs if r.get("trajectory") and r["trajectory"]["score"] is not None]
    return {
        "n": n,
        "goal_success": _rate(len(ok), n),
        "rescored_success": _rate(len(rescored), n),
        "clean_run": _rate(len(no_err), n),
        "terminal_decision": _rate(len(terminal), n),
        "decision_accuracy": _rate(len(correct_decision), n),
        "trajectory_mean": round(statistics.mean(traj), 4) if traj else None,
    }


def _pct(values, p):
    if not values:
        return None
    vals = sorted(values)
    idx = min(len(vals) - 1, max(0, round(p / 100 * (len(vals) - 1))))
    return round(vals[idx], 1)


def compute_metrics(records, error_bucketer=None):
    recs = sorted(records, key=lambda r: r["test_id"])
    n = len(recs)

    # --- headline ---
    headline = {
        "goal_success_rate": _rate(sum(1 for r in recs if r["overall_pass"]), n),
        "rescored_success_rate": _rate(sum(1 for r in recs if _rescored_pass(r)), n),
        "judge_agreement": _rate(sum(1 for r in recs if r["overall_pass"] == _rescored_pass(r)), n),
        "clean_run_rate": _rate(sum(1 for r in recs if _clean(r)), n),
        "terminal_decision_rate": _rate(sum(1 for r in recs if r["actual_status"] in TERMINAL_DECISIONS), n),
        "decision_accuracy": _rate(sum(1 for r in recs if r["actual_status"] == r["expected_status"]), n),
        "amount_accuracy": _rate(sum(1 for r in recs if _amounts_match(r)), n),
        "intent_recognition_rate": _rate(
            sum(1 for r in recs if r.get("trajectory") and r["trajectory"].get("intent_recognized")),
            sum(1 for r in recs if r.get("trajectory") is not None),
        ),
    }
    traj_scores = [r["trajectory"]["score"] for r in recs if r.get("trajectory") and r["trajectory"]["score"] is not None]
    headline["trajectory_match_mean"] = round(statistics.mean(traj_scores), 4) if traj_scores else None

    # --- decision confusion matrix (expected x actual) ---
    seen = set()
    for r in recs:
        seen.add(r["expected_status"])
        seen.add(r["actual_status"])
    labels = [s for s in STATUS_ORDER if s in seen] + sorted(seen - set(STATUS_ORDER))
    idx = {s: i for i, s in enumerate(labels)}
    matrix = [[0] * len(labels) for _ in labels]
    for r in recs:
        matrix[idx[r["expected_status"]]][idx[r["actual_status"]]] += 1
    confusion = {"labels": labels, "matrix": matrix}

    # --- canonical check accuracy ---
    checks = {}
    agg = defaultdict(lambda: {"pass": 0, "total": 0, "cases": set()})
    for r in recs:
        for c in r["checks"]:
            a = agg[c["canonical"]]
            a["total"] += 1
            a["pass"] += 1 if c["passed"] else 0
            a["cases"].add(r["test_id"])
    for key in sorted(agg):
        a = agg[key]
        checks[key] = {"pass": a["pass"], "total": a["total"],
                       "rate": round(a["pass"] / a["total"], 4), "cases": len(a["cases"])}

    # --- slices ---
    def slice_by(keyfn):
        groups = defaultdict(list)
        for r in recs:
            groups[keyfn(r)].append(r)
        return {k: _slice_bundle(v) for k, v in sorted(groups.items())}

    from .adapters import DECISION_CLASS_LABELS
    slices = {
        "family": slice_by(lambda r: r["family"]),
        "regime": slice_by(lambda r: r["regime"]),
        "expected_status": slice_by(lambda r: r["expected_status"]),
        "decision_class": slice_by(lambda r: DECISION_CLASS_LABELS.get(r.get("decision_class"), r.get("decision_class", "?"))),
        "system_code_prefix": slice_by(
            lambda r: "-".join(r["expected_system_code"].split("-")[:3]) if r["expected_system_code"] else "(none)"),
    }

    # --- trajectory detail ---
    trajectory = {"stage_coverage": {}, "anomaly_rates": {}, "by_family": {}}
    with_traj = [r for r in recs if r.get("trajectory")]
    if with_traj:
        stage_hits = Counter()
        anomaly_hits = Counter()
        for r in with_traj:
            for s in r["trajectory"]["stages_hit"]:
                stage_hits[s] += 1
            for a in r["trajectory"]["anomalies"]:
                anomaly_hits[a] += 1
        trajectory["stage_coverage"] = {s: _rate(c, len(with_traj)) for s, c in sorted(stage_hits.items())}
        trajectory["anomaly_rates"] = {a: _rate(c, len(with_traj)) for a, c in sorted(anomaly_hits.items())}
        fam_groups = defaultdict(list)
        for r in with_traj:
            if r["trajectory"]["score"] is not None:
                fam_groups[r["family"]].append(r["trajectory"]["score"])
        trajectory["by_family"] = {f: round(statistics.mean(v), 4) for f, v in sorted(fam_groups.items())}

    # --- operational ---
    durations = [r["duration_s"] for r in recs if isinstance(r["duration_s"], (int, float))]
    turns = [r["turns"] for r in recs if isinstance(r["turns"], (int, float))]
    err_buckets = Counter()
    for r in recs:
        if r["run_error"]:
            key = r.get("error_bucket") or (error_bucketer(r["run_error"]) if error_bucketer else "error")
            fatal = r.get("error_fatal", True)
            err_buckets[f"{key} ({'fatal' if fatal else 'cosmetic'})"] += 1
    ops = {
        "duration_s": {"p50": _pct(durations, 50), "p90": _pct(durations, 90),
                       "mean": round(statistics.mean(durations), 1) if durations else None},
        "turns": {"p50": _pct(turns, 50), "p90": _pct(turns, 90),
                  "mean": round(statistics.mean(turns), 1) if turns else None},
        "error_buckets": dict(sorted(err_buckets.items(), key=lambda kv: -kv[1])),
    }

    # --- per-case appendix rows ---
    cases = []
    for r in recs:
        cases.append({
            "test_id": r["test_id"], "family": r["family"], "regime": r["regime"],
            "system_code_prefix": ("-".join(r["expected_system_code"].split("-")[:3])
                                   if r["expected_system_code"] else "(none)"),
            "decision_class": r.get("decision_class", "?"),
            "expected_status": r["expected_status"], "actual_status": r["actual_status"],
            "expected_amount": (f"{r['expected_amount'][0]} {r['expected_amount'][1]:g}" if r["expected_amount"] else "—"),
            "actual_amount": r["actual_amount_raw"],
            "overall_pass": r["overall_pass"],
            "rescored_pass": _rescored_pass(r),
            "trajectory_score": (r["trajectory"]["score"] if r.get("trajectory") else None),
            "anomalies": (sorted(r["trajectory"]["anomalies"]) if r.get("trajectory") else []),
            "run_error": bool(r["run_error"]) and r.get("error_fatal", True),
            "duration_s": r["duration_s"],
        })

    return {
        "schema_version": SCHEMA_VERSION,
        "agent": recs[0]["agent"] if recs else "?",
        "env": Counter(r["env"] for r in recs).most_common(1)[0][0] if recs else "?",
        "n_cases": n,
        "headline": headline,
        "confusion": confusion,
        "checks": checks,
        "slices": slices,
        "trajectory": trajectory,
        "ops": ops,
        "cases": cases,
    }
