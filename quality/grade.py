"""``quality_report()``: canonical Result -> a response-QUALITY grade (not correctness).

Two layers: deterministic (``quality.checks``, always run, stdlib-only, no network) and
an optional Bedrock LLM judge (``quality.rubric.llm_judge``, only run when
``use_llm=True``). The 0-100 score is always derived deterministically from finding
severities; the LLM layer only ever contributes to the score when explicitly enabled.
"""
from __future__ import annotations

from quality.checks import deterministic_checks
from quality.rubric import DEFAULT_MODEL, DEFAULT_REGION, llm_judge

_SEVERITY_PENALTY = {"High": 15, "Medium": 7, "Low": 3}
_MAX_SCORE = 100


def _score(findings: list[dict]) -> int:
    score = _MAX_SCORE
    for f in findings:
        score -= _SEVERITY_PENALTY.get(f.get("severity"), 5)
    return max(0, min(_MAX_SCORE, score))


def quality_report(result: dict, use_llm: bool = False, model: str | None = None,
                    region: str | None = None) -> dict:
    """Grade one canonical Result's transcript for response QUALITY.

    ``use_llm=False`` (the default) never imports boto3 and never makes a network call:
    ``llm`` is ``None`` and the score comes purely from the deterministic layer. Passing
    ``use_llm=True`` additionally calls ``quality.rubric.llm_judge`` and folds its
    findings into the score.

    Returns ``{scenario_id, test_case, deterministic, llm, score, summary}``.
    """
    transcript = result.get("transcript") or []
    case = result.get("case") or {}
    det = deterministic_checks(transcript)

    llm: list[dict] | None = None
    all_findings = list(det)
    if use_llm:
        llm = llm_judge(transcript, case, model or DEFAULT_MODEL, region or DEFAULT_REGION)
        all_findings = all_findings + llm

    score = _score(all_findings)
    high = sum(1 for f in all_findings if f.get("severity") == "High")
    medium = sum(1 for f in all_findings if f.get("severity") == "Medium")
    low = sum(1 for f in all_findings if f.get("severity") == "Low")
    summary = (
        f"{len(det)} deterministic finding(s)"
        + (f", {len(llm)} LLM finding(s)" if llm is not None else "")
        + f" — {high} High / {medium} Medium / {low} Low — score {score}/100"
    )

    return {
        "scenario_id": result.get("scenario_id", ""),
        "test_case": case.get("test_case", ""),
        "deterministic": det,
        "llm": llm,
        "score": score,
        "summary": summary,
    }
