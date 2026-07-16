"""Adapters: parse each QA agent's native artifacts into the normalized EvalRecord schema.

Every agent output folder gets one adapter. Adding a third agent later means
writing one function here that emits the same record shape; everything
downstream (metrics, report) stays untouched.
"""

import glob
import json
import os
import re

# ---------------------------------------------------------------------------
# Normalized record schema (dict keys):
#   agent          str   label for the run set (e.g. "agent-alpha")
#   test_id        str   e.g. FD_TC_003
#   family         str   CORE | ED | PAY
#   env            str   e.g. CRT | INT
#   regime         str   APPR | EU | ASL | MIXED | UNKNOWN
#   expected_status    str   ELIGIBLE | NOT_ELIGIBLE | NO_DETERMINATION | PENDING
#   expected_amount    (ccy, value) or None
#   expected_system_code  str or ""
#   actual_status      str   normalized bot outcome
#   actual_amount_raw  str
#   overall_pass   bool  the agent's own end verdict for the test case
#   checks         list[{raw_name, canonical, passed}]
#   run_error      str or None   harness/runtime error captured by the agent
#   duration_s     float or None
#   turns          int or None
#   transcript_path str or None
#   contact_id     str
#   started        str
# ---------------------------------------------------------------------------

FAMILY_LABELS = {"CORE": "Core FD claim", "ED": "Edge/data variants (ED)", "PAY": "Payment variants (PAY)"}


def family_of(test_id):
    if "_ED_" in test_id:
        return "ED"
    if "_PAY_" in test_id:
        return "PAY"
    return "CORE"


AMOUNT_RE = re.compile(r"(?:(CAD|EUR|GBP|ILS|USD)\s*([\d,]+(?:\.\d+)?)|([\d,]+(?:\.\d+)?)\s*(CAD|EUR|GBP|ILS|USD))", re.I)


def parse_amounts(s):
    """All (ccy, value) pairs in a string. '259.01 GBP (485.12 CAD)' -> both pairs,
    so a converted quote can match on either currency. '—'/'none' -> []."""
    if not s or str(s).strip() in ("—", "none", "None", ""):
        return []
    out = []
    for m in AMOUNT_RE.finditer(str(s)):
        ccy = (m.group(1) or m.group(4)).upper()
        val = float((m.group(2) or m.group(3)).replace(",", ""))
        out.append((ccy, val))
    return out


def parse_amount(s):
    """First (ccy, value) pair or None. A zero amount ('CAD 0', one agent's way
    of scripting 'no compensation due') normalizes to None, matching the other
    agent's '—' sentinel."""
    pairs = [p for p in parse_amounts(s) if p[1] != 0]
    return pairs[0] if pairs else None


DECISION_CLASS_LABELS = {
    "EL": "EL — should be eligible", "NE": "NE — should be refused",
    "ND": "ND — should abstain", "PE": "PE — pending claim", "DB": "DB — denied boarding",
}


def regime_from_code(system_code, fallback):
    """Regime from systemCode segment 2 (FD-<REGIME>-<CLASS>-<n>). The scripted
    code is the ground truth; some agents' regime fields mislabel MIXED/DUP cases."""
    parts = (system_code or "").split("-")
    if len(parts) >= 2 and parts[1]:
        return parts[1].upper()
    return (fallback or "UNKNOWN").upper()


def decision_class_from_code(system_code):
    parts = (system_code or "").split("-")
    return parts[2].upper() if len(parts) >= 3 else "UNKNOWN"


def normalize_status(s):
    if s is None:
        return "UNKNOWN"
    s = str(s).strip().upper().replace(" ", "_").replace("-", "_")
    aliases = {
        "INELIGIBLE": "NOT_ELIGIBLE",
        "NOT_ELIGIBLE": "NOT_ELIGIBLE",
        "ELIGIBLE": "ELIGIBLE",
        "NO_DETERMINATION": "NO_DETERMINATION",
        "ESCALATED": "ESCALATED",
        "PENDING": "PENDING",
        "UNRESOLVED": "UNRESOLVED",
    }
    return aliases.get(s, s)


def load_agent_alpha(dir_path, canonicalize_check):
    """agent-alpha: *_result.json with case/session/run_meta/verdict/widgets/transcript."""
    records = []
    for path in sorted(glob.glob(os.path.join(dir_path, "*_result.json"))):
        d = json.load(open(path))
        case = d.get("case") or {}
        run_meta = d.get("run_meta") or {}
        verdict = d.get("verdict") or {}
        test_id = case.get("Test Case") or re.sub(r"_result\.json$", "", os.path.basename(path))
        checks = []
        for c in verdict.get("checks") or []:
            checks.append({
                "raw_name": c.get("name", ""),
                "canonical": canonicalize_check(c.get("name", "")),
                "passed": bool(c.get("pass")),
            })
        transcript = os.path.join(dir_path, f"{test_id}_transcript.md")
        code = case.get("systemCode") or ""
        records.append({
            "agent": os.path.basename(os.path.normpath(dir_path)),
            "test_id": test_id,
            "family": family_of(test_id),
            "env": (d.get("session") or {}).get("env", ""),
            "regime": regime_from_code(code, case.get("Regime")),
            "decision_class": decision_class_from_code(code),
            "expected_status": normalize_status(case.get("Status")),
            "expected_amount": parse_amount(case.get("Amount")),
            "expected_system_code": code,
            "actual_status": normalize_status(verdict.get("bot_said_eligible")),
            "actual_amount_raw": str(verdict.get("bot_amount") or "none"),
            "overall_pass": bool(verdict.get("matches_expected")),
            "checks": checks,
            "run_error": run_meta.get("error") or None,
            "duration_s": run_meta.get("duration_s"),
            "turns": None,
            "transcript_path": transcript if os.path.exists(transcript) else None,
            "contact_id": run_meta.get("contact_id", ""),
            "started": run_meta.get("started", ""),
        })
    return records


def load_agent_bravo(dir_path, canonicalize_check):
    """agent-bravo: *_qa_report.json flat schema + *_results.jsonl for turn counts."""
    turns_by_tc = {}
    for jl in glob.glob(os.path.join(dir_path, "*results.jsonl")):
        for line in open(jl):
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            turns_by_tc[row.get("tc")] = row.get("turns")

    records = []
    for path in sorted(glob.glob(os.path.join(dir_path, "*_qa_report.json"))):
        d = json.load(open(path))
        test_id = d.get("test_case") or re.sub(r"_qa_report\.json$", "", os.path.basename(path))
        expected = d.get("expected") or {}
        actual = d.get("actual") or {}
        checks = []
        for c in d.get("checks") or []:
            checks.append({
                "raw_name": c.get("name", ""),
                "canonical": canonicalize_check(c.get("name", "")),
                "passed": bool(c.get("pass")),
            })
        transcript = os.path.join(dir_path, f"{test_id}_chat_transcript.md")
        code = expected.get("systemCode") or ""
        records.append({
            "agent": os.path.basename(os.path.normpath(dir_path)),
            "test_id": test_id,
            "family": family_of(test_id),
            "env": d.get("env", ""),
            "regime": regime_from_code(code, (d.get("regime") or "UNKNOWN").replace("—", "UNKNOWN")),
            "decision_class": decision_class_from_code(code),
            "expected_status": normalize_status(expected.get("status")),
            "expected_amount": parse_amount(expected.get("amount")),
            "expected_system_code": code,
            "actual_status": normalize_status(actual.get("eligibility")),
            "actual_amount_raw": str(actual.get("amount") or "none"),
            "overall_pass": (d.get("overall") == "PASS"),
            "checks": checks,
            "run_error": d.get("run_error") or None,
            "duration_s": d.get("duration_s"),
            "turns": turns_by_tc.get(test_id),
            "transcript_path": transcript if os.path.exists(transcript) else None,
            "contact_id": d.get("contact_id", ""),
            "started": d.get("run_started", ""),
        })
    return records


ADAPTERS = {
    "alpha": load_agent_alpha,
    "bravo": load_agent_bravo,
}


def detect_adapter(dir_path):
    """Pick the adapter by artifact fingerprint so the CLI works on future folders too."""
    if glob.glob(os.path.join(dir_path, "*_result.json")):
        return "alpha"
    if glob.glob(os.path.join(dir_path, "*_qa_report.json")):
        return "bravo"
    raise SystemExit(f"No known QA artifacts (*_result.json / *_qa_report.json) found in {dir_path}")
