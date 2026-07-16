"""Deterministic (non-LLM) chat-quality checks over a canonical Result transcript.

Ported from chat-quality/quality_check.py's ``deterministic_checks()``: pattern-based
detection of duplicate messages, empty bot bubbles, leaked internal tokens, technical
errors surfaced to the customer, repeated bot questions (flow loops), and generic
placeholder floods. Stdlib-only (``re``) — no network, no LLM, deterministic output.
"""
from __future__ import annotations

import re

# Internal tokens that must NOT be shown to a customer (content/security areas 9 & 10).
LEAK_PATTERNS = [
    r"FD-[A-Z]+-[A-Z]+-?\d*", r"\bSF-[A-Z]{2}-\d+", r"\bBF-[A-Z]{2}-\d+",
    r"execution_traces", r"pnr_id", r"trip_details", r"\bsystemCode\b",
    r"s3://", r"traces/DDS", r"Traceback", r"\b[0-9a-f]{8}-[0-9a-f]{4}-",  # uuids
    r"\bAccessDenied", r"\bNullPointer", r"\bstack ?trace",
]
ERROR_PATTERNS = [
    r"\b500\b", r"internal server error", r"\btimed? ?out", r"unable to process",
    r"something went wrong", r"try again later", r"AccessDenied", r"exception",
]
PLACEHOLDER = ["processing your request and will assist", "how i can help"]


def _norm(s: str | None) -> str:
    return re.sub(r"\s+", " ", (s or "").strip().lower())


def _finding(area: str, severity: str, issue: str, evidence: str | None) -> dict:
    return {
        "layer": "deterministic",
        "area": area,
        "severity": severity,
        "issue": issue,
        "evidence": (evidence or "")[:160],
    }


def deterministic_checks(transcript: list[dict]) -> list[dict]:
    """Programmatic defect detection mapped to the 10 quality areas.

    ``transcript`` is the canonical Result's list of ``{role, text, ts, note}`` turns
    (see core/schema/result.schema.json); ``role == "customer"`` is the user, any other
    role is the bot. Returns a list of findings, each
    ``{layer: "deterministic", area, severity, issue, evidence}``.
    """
    tr = transcript or []
    findings: list[dict] = []
    bots = [m for m in tr if m.get("role") != "customer"]
    users = [m for m in tr if m.get("role") == "customer"]

    # Area 1 — duplicate bot responses
    seen: dict[str, int] = {}
    for m in bots:
        n = _norm(m.get("text"))
        if not n:
            continue
        if n in seen:
            findings.append(_finding(
                "1 Duplicate messages", "High",
                "Duplicate bot response (same text sent again)", m.get("text"),
            ))
        seen[n] = seen.get(n, 0) + 1

    # Area 1 — duplicate user messages (consecutive identical)
    for a, b in zip(users, users[1:]):
        na, nb = _norm(a.get("text")), _norm(b.get("text"))
        if na and na == nb:
            findings.append(_finding(
                "1 Duplicate messages", "Medium",
                "Duplicate/echoed user message", b.get("text"),
            ))

    # Area 2 — empty bot bubble
    for m in bots:
        if not (m.get("text") or "").strip():
            findings.append(_finding("2 Send/receive quality", "Medium", "Empty bot message bubble", ""))

    # Area 2/7 — placeholder floods (generic 'processing…' filler)
    ph = [m for m in bots if any(k in _norm(m.get("text")) for k in PLACEHOLDER)]
    if len(ph) >= 2:
        findings.append(_finding(
            "2 Send/receive quality", "Medium",
            f"{len(ph)} generic 'processing…' placeholder replies (filler / no real content)",
            ph[0].get("text"),
        ))

    # Area 2 — timestamp ordering
    ts = [m.get("ts") for m in tr if m.get("ts")]
    if ts != sorted(ts):
        findings.append(_finding(
            "2 Send/receive quality", "Low",
            "Message timestamps not monotonically increasing (ordering)", "",
        ))

    # Area 5 — repeated question (bot asks the same thing 3+ times)
    qs: dict[str, int] = {}
    for m in bots:
        n = _norm(m.get("text"))
        if n.endswith("?") or "could you please" in n or "what is your" in n:
            qs[n] = qs.get(n, 0) + 1
    for q, c in qs.items():
        if c >= 3:
            findings.append(_finding(
                "5 Conversation flow", "High",
                f"Bot asked the same question {c}× (loop / not remembering)", q,
            ))

    # Area 7 — technical/error text shown to the customer
    for m in bots:
        text = m.get("text") or ""
        if any(re.search(p, text, re.I) for p in ERROR_PATTERNS):
            findings.append(_finding(
                "7 API/error handling", "High",
                "Technical/error wording shown to the customer", text,
            ))

    # Area 9/10 — internal codes / field names / tokens leaked
    for m in bots:
        text = m.get("text") or ""
        for p in LEAK_PATTERNS:
            mt = re.search(p, text)
            if mt:
                findings.append(_finding(
                    "9/10 Content & security", "High",
                    f"Internal token leaked to user (pattern {p})", mt.group(0),
                ))
                break

    return findings
