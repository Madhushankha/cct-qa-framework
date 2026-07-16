"""The 10-area quality RUBRIC + the optional Bedrock LLM judge layer.

``llm_judge`` is only ever invoked when a caller explicitly opts in (e.g.
``quality.grade.quality_report(use_llm=True)`` or ``cctqa quality --llm``). ``boto3``
is imported lazily inside the function body so importing this module — or running the
deterministic layer with ``use_llm=False`` — never requires boto3 to be installed and
never touches the network.
"""
from __future__ import annotations

DEFAULT_MODEL = "global.anthropic.claude-opus-4-8"
DEFAULT_REGION = "ca-central-1"

# 10-area rubric ported from chat-quality/quality_check.py: duplicate messages,
# send/receive quality, business logic, quick replies/widgets, conversation flow
# (accuracy/helpfulness of staying on-task), UI/UX, API/error handling, session/context,
# content quality (clarity/tone/empathy/grammar), security/privacy.
RUBRIC = """You are a senior QA reviewer auditing an Air Canada WEB-CHAT conversation for QUALITY DEFECTS.
Grade it against these 10 areas (flag only REAL issues you can evidence from the transcript):
 1 Duplicate messages — same user/bot message appearing twice; backend/retry double-replies.
 2 Send/receive quality — message order, missing/empty replies, response attached to wrong turn, stuck loaders.
 3 Business logic / compensation — wrong eligibility, wrong amount, final decision given before required info, UI≠backend.
 4 Quick replies / widgets — options match the message, clicking triggers the right flow, no stale options, button text == payload.
 5 Conversation flow — completes; recovers from unexpected input; handles intent switch; consistent answers; no repeated questions.
 6 UI/UX — (only if visible in transcript) empty bubbles, cut-off text, broken widgets.
 7 API/error handling — friendly retry vs raw errors, timeouts, blank/broken messages, infinite loading.
 8 Session/context — remembers context, no context leak, no duplicated history.
 9 Content quality — clear, grammatical, empathetic, appropriate tone, helpful, consistent, no dead-ends, no internal field names/codes shown.
10 Security/privacy — no leaked system prompts/keys/tokens, no other-customer data, no backend detail in errors.
For each issue: area, severity (High/Medium/Low), the verbatim evidence quote, and a recommendation."""

_JUDGE_TOOL = {
    "toolSpec": {
        "name": "submit_quality_review",
        "description": "Return the structured chat-quality review.",
        "inputSchema": {"json": {
            "type": "object",
            "properties": {
                "overall_rating": {"type": "string", "enum": ["PASS", "MINOR_ISSUES", "MAJOR_ISSUES"]},
                "summary": {"type": "string"},
                "findings": {"type": "array", "items": {"type": "object", "properties": {
                    "area": {"type": "string", "description": "one of the 10 areas, e.g. '1 Duplicate messages'"},
                    "severity": {"type": "string", "enum": ["High", "Medium", "Low"]},
                    "observation": {"type": "string"},
                    "evidence": {"type": "string", "description": "verbatim quote from the transcript"},
                    "recommendation": {"type": "string"},
                }, "required": ["area", "severity", "observation", "evidence", "recommendation"]}},
            },
            "required": ["overall_rating", "summary", "findings"],
        }},
    }
}


def llm_judge(transcript: list[dict], case: dict, model: str, region: str) -> list[dict]:
    """Ask a Bedrock Claude model (Converse API + tool-use) to grade ``transcript``
    against ``RUBRIC``. Returns findings shaped like ``quality.checks.deterministic_checks``'s
    output plus a ``recommendation`` key, with ``layer: "llm"``.

    Imports ``boto3`` lazily — never call this unless the caller has explicitly enabled
    the LLM layer; it makes a real network call to Bedrock.
    """
    import boto3  # lazy: keeps the deterministic layer network-free & boto3-optional

    convo = "\n".join(
        f"{'USER' if m.get('role') == 'customer' else 'BOT'}: {m.get('text', '')}" for m in transcript
    )
    expected = (f"Test case {case.get('test_case', '?')} | expected {case.get('expected_status', '?')} "
                f"{case.get('expected_amount', '')} {case.get('expected_system_code', '')}")
    client = boto3.Session(region_name=region).client("bedrock-runtime")
    message = (f"{RUBRIC}\n\nEXPECTED (business): {expected}\n\nTRANSCRIPT:\n{convo}\n\n"
               "Call submit_quality_review with every real defect you find (or an empty findings list if clean).")
    response = client.converse(
        modelId=model,
        messages=[{"role": "user", "content": [{"text": message}]}],
        toolConfig={"tools": [_JUDGE_TOOL], "toolChoice": {"tool": {"name": "submit_quality_review"}}},
        inferenceConfig={"maxTokens": 3000},
    )
    review = {"overall_rating": "PASS", "summary": "no tool output", "findings": []}
    for block in response["output"]["message"]["content"]:
        if "toolUse" in block:
            review = block["toolUse"]["input"]
            break

    return [
        {
            "layer": "llm",
            "area": f.get("area", ""),
            "severity": f.get("severity", "Low"),
            "issue": f.get("observation", ""),
            "evidence": f.get("evidence", ""),
            "recommendation": f.get("recommendation", ""),
        }
        for f in review.get("findings", [])
    ]
