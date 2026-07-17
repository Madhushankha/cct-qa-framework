"""grade(): canonical Result (P0) -> {grade, status, confidence, findings}.

Cascade-style grade taxonomy (see docs/context.md §4): separates product defects from
harness/env noise so pass-rate is trustworthy. Deterministic, stdlib-only.

Grade taxonomy:
    Strong PASS       matches_expected, seed verified, no failed checks
    Weak PASS         matches_expected but seed.verified is False
    Invalid PASS      matches_expected but at least one verdict.checks[].pass is False
    Valid FAIL        not matches_expected, no harness error
    Harness FAIL      harness.error set, bucket is not env/timeout-shaped
    Environment ERROR harness.error set, bucket is env/timeout-shaped (otp/timeout/access-denied)

Findings are stable-coded {level, code, message, severity} entries used for aggregate
clustering (analysis.cluster) — the same finding code should always mean the same thing.
"""
from __future__ import annotations

# harness.error_bucket values (see metrics/evalkit/taxonomy.py _ERROR_BUCKETS) that indicate
# environment/infra noise rather than a harness bug in the flow itself.
_ENV_BUCKETS = {"bot_reply_timeout", "otp_fetch_failure", "send_access_denied"}

# coarse status per grade (README: "status = coarse PASS|WARN|FAIL|INVALID from grade").
_STATUS_BY_GRADE = {
    "Strong PASS": "PASS",
    "Weak PASS": "WARN",
    "Invalid PASS": "INVALID",
    "Valid FAIL": "FAIL",
    "Harness FAIL": "FAIL",
    "Environment ERROR": "FAIL",
}

# confidence base score per grade, before per-finding penalties.
_BASE_CONFIDENCE = {
    "Strong PASS": 95,
    "Weak PASS": 65,
    "Invalid PASS": 10,
    "Valid FAIL": 85,
    "Harness FAIL": 30,
    "Environment ERROR": 30,
}

_FINDING_PENALTY = 5


def _finding(level: str, code: str, message: str, severity: str) -> dict:
    return {"level": level, "code": code, "message": message, "severity": severity}


import re as _re

# The bot ITSELF reports a transient backend outage in the chat (the case-intake/DDS system was
# unreachable at submit), so it never surfaces as a harness exception — yet it is an ENVIRONMENT
# failure, not a product defect (the bot handled the flow correctly up to the outage). Detect the
# bot's own outage language so these aren't graded "Valid FAIL" and filed as false Jira tickets.
_OUTAGE_RE = _re.compile(
    r"trouble reaching our case system|reaching our case system|having trouble reaching|"
    r"case system right now|try again in a few|temporarily unavailable|"
    r"system is (?:currently |temporarily )?unavailable|unable to (?:process|reach)[^.]*(?:right now|at this time)",
    _re.I)


def _backend_outage(result: dict) -> bool:
    """True if a bot turn reports a transient backend/case-system outage (see _OUTAGE_RE)."""
    for t in result.get("transcript") or []:
        if t.get("role") in ("assistant", "bot") and _OUTAGE_RE.search(str(t.get("text") or "")):
            return True
    return False


def _determination_gap_finding(result: dict) -> dict | None:
    """The recurring determination-gap: DDS already reached an eligible-shaped verdict but
    the bot escalated / reached no determination instead of surfacing it."""
    seed = result.get("seed") or {}
    dds = seed.get("dds")
    if not isinstance(dds, dict):
        return None
    dds_status = (dds.get("status") or "").upper()
    if "ELIGIBLE" not in dds_status or "NOT_ELIGIBLE" in dds_status:
        return None
    decision = (result.get("verdict") or {}).get("decision") or ""
    if decision.upper() not in {"ESCALATED", "NO_DETERMINATION"}:
        return None
    return _finding(
        "warning",
        "DETERMINATION_IN_DDS_BUT_ESCALATED",
        f"DDS reached '{dds.get('status')}' but bot decision was '{decision}'",
        "high",
    )


def grade(result: dict) -> dict:
    """Grade one canonical Result document. Returns {grade, status, confidence, findings}."""
    harness = result.get("harness") or {}
    verdict = result.get("verdict") or {}
    seed = result.get("seed") or {}

    harness_error = harness.get("error")
    error_bucket = harness.get("error_bucket")
    matches_expected = bool(verdict.get("matches_expected"))
    seed_verified = bool(seed.get("verified"))
    checks = verdict.get("checks") or []
    failed_checks = [c for c in checks if not c.get("pass", True)]

    findings: list[dict] = []

    if harness_error:
        if error_bucket in _ENV_BUCKETS:
            grade_name = "Environment ERROR"
            findings.append(_finding(
                "error", "ENVIRONMENT_ERROR",
                f"harness reported an environment/infra error: {harness_error}", "high",
            ))
        else:
            grade_name = "Harness FAIL"
            findings.append(_finding(
                "error", "HARNESS_ERROR",
                f"harness error: {harness_error}", "high",
            ))
    elif matches_expected:
        if failed_checks:
            grade_name = "Invalid PASS"
            names = ", ".join(c.get("name", "?") for c in failed_checks)
            findings.append(_finding(
                "warning", "PASS_WITH_FAILED_ASSERTION",
                f"matched expected outcome but failed check(s): {names}", "high",
            ))
        elif not seed_verified:
            grade_name = "Weak PASS"
            findings.append(_finding(
                "warning", "PASS_WITHOUT_SEED_VERIFICATION",
                "matched expected outcome but seed was not verified", "medium",
            ))
        else:
            grade_name = "Strong PASS"
    elif _backend_outage(result):
        # bot handled the flow correctly but the case/DDS backend was unreachable at submit — an
        # environment failure, NOT a product defect (so it is excluded from Jira defect selection).
        grade_name = "Environment ERROR"
        findings.append(_finding(
            "error", "BACKEND_OUTAGE",
            "bot reported a transient backend/case-system outage at submit; not a product defect",
            "high",
        ))
    else:
        grade_name = "Valid FAIL"

    gap = _determination_gap_finding(result)
    if gap is not None:
        findings.append(gap)

    status = _STATUS_BY_GRADE[grade_name]
    confidence = max(0, min(100, _BASE_CONFIDENCE[grade_name] - _FINDING_PENALTY * len(findings)))

    return {
        "grade": grade_name,
        "status": status,
        "confidence": confidence,
        "findings": findings,
    }
