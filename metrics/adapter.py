"""Adapter: canonical CCT-QA Result (P0 ``core/schema/result.schema.json``) -> evalkit's
normalized EvalRecord dict (see ``metrics/evalkit/adapters.py`` module docstring for the
exact record shape evalkit's metrics/report/trajectory modules consume).

Because there is now ONE canonical Result schema (P0), there is one adapter here — not
one per product/env like evalkit's own ``load_agent_alpha`` / ``load_agent_bravo``.
"""
from __future__ import annotations

from metrics.evalkit import taxonomy
from metrics.evalkit.adapters import (
    decision_class_from_code,
    family_of,
    normalize_status,
    regime_from_code,
)


def _amount_tuple(amount: dict | None) -> tuple[str, float] | None:
    """{"currency": ..., "value": ...} | None -> (ccy, value) | None, evalkit's shape."""
    if not amount:
        return None
    return (amount["currency"], amount["value"])


def _amount_raw(amount: dict | None) -> str:
    """evalkit's adapters render actual amounts as free text it re-parses with
    ``adapters.parse_amount``; "none" is the sentinel a null amount maps to."""
    if not amount:
        return "none"
    return f"{amount['currency']} {amount['value']}"


# Role -> the transcript-line marker evalkit's `alpha` stage detectors are anchored on. The
# canonical Result transcript ({role, note, text}) renders to `**🤖 BOT** [note]: text` lines, the
# exact dialect the alpha regexes were mined from (this bot's greeting + [mailinator-otp] notes match
# alpha), so the trajectory analysis works off the inline transcript with no file on disk.
_ROLE_MARK = {"assistant": "🤖 BOT", "bot": "🤖 BOT", "customer": "🧑 CUSTOMER", "user": "🧑 CUSTOMER"}


def render_transcript_md(transcript) -> str:
    """Render an inline canonical transcript to the alpha markdown dialect the stage detectors read."""
    lines = []
    for t in transcript or []:
        mark = _ROLE_MARK.get(str(t.get("role") or "").lower())
        if not mark:
            continue
        note = t.get("note")
        tag = f" [{note}]" if note else ""
        text = str(t.get("text") or "").replace("\r", " ").replace("\n", " ")
        lines.append(f"**{mark}**{tag}: {text}")
    return "\n".join(lines)


def result_to_record(result: dict) -> dict:
    """Map ONE canonical Result document to evalkit's normalized EvalRecord dict."""
    run = result["run"]
    case = result["case"]
    verdict = result["verdict"]
    harness = result["harness"]
    auth = result["auth"]

    test_id = case["test_case"]
    code = case.get("expected_system_code") or ""

    checks = [
        {
            "raw_name": c.get("name", ""),
            "canonical": taxonomy.canonicalize_check(c.get("name", "")),
            "passed": bool(c.get("pass")),
        }
        for c in (verdict.get("checks") or [])
    ]

    return {
        "agent": run.get("product", ""),
        "test_id": test_id,
        "family": family_of(test_id),
        "env": run.get("env", ""),
        "regime": regime_from_code(code, case.get("regime")),
        "decision_class": decision_class_from_code(code),
        "expected_status": normalize_status(case.get("expected_status")),
        "expected_amount": _amount_tuple(case.get("expected_amount")),
        "expected_system_code": code,
        "actual_status": normalize_status(verdict.get("decision")),
        "actual_amount_raw": _amount_raw(verdict.get("amount")),
        "overall_pass": bool(verdict.get("matches_expected")),
        "checks": checks,
        "run_error": harness.get("error"),
        "duration_s": run.get("duration_s"),
        # Turn count from the inline transcript (the canonical schema has no separate counter).
        "turns": len(result.get("transcript") or []) or None,
        # Canonical Results carry the transcript INLINE. Render it to the alpha markdown dialect and
        # hand it over as transcript_text so evalkit.trajectory.annotate_trajectory can run the
        # deterministic flow-stage detectors on it (no transcript file on disk needed).
        "transcript_path": None,
        "transcript_text": render_transcript_md(result.get("transcript")),
        "contact_id": auth.get("contact_id"),
        "started": run.get("started"),
    }
