"""SeatChange flow outcome — reads each case's REAL result (SEAT_CHANGED / PAYMENT_REQUIRED /
DECLINED / LIVE_AGENT / NO_DETERMINATION / UNKNOWN — matching seatchange.yaml's
`judge.verdict_enum`) directly off the gap-doc card body, independent of catalog/parser.py.

This is the SeatChange analogue of `seed/feeds/nc_outcome.py` — see that module's docstring for the
full rationale (no systemCode, no `data-out`, so `catalog/parser.py` leaves every SeatChange
UseCase.verdict as ""; the real outcome lives only in the card's title + Gherkin "Then" checklist
prose, which the shared parser does not capture into any field). Same method: a last-match-wins
phrase scan over (title, *checklist-lines) joined in document order, falling back to a per-category
default (`_DEFAULT_BY_CATEGORY`, keyed off `data-feat` — Happy Path / Eligibility Block / ID Failure
/ Auth Failure / Seat Map / Payment / Passenger Rules / Disruption / Edge Cases) when no signal
phrase is present.

Confidence is NOT uniform. Highest: Happy Path ("seat has been changed" / "SC-03a" confirmation
wording) and Eligibility Block ("blocked" / "contact X" / "should stop" wording). Lowest: Seat Map
and several Edge Cases cards whose checklist narrates only an intermediate/conditional state (e.g.
TC038's "if payment processed: ... / if not processed: ..." — an explicitly branching outcome this
module cannot represent as two verdicts, so it resolves to whichever branch's phrase is textually
last) — read those as PROVISIONAL. This module has NOT been cross-checked against a live chatbot
run; a live CRT/INT run against a seeded case is the actual source of truth.
"""
from __future__ import annotations

import html as html_lib
import re
from pathlib import Path

_WS_RE = re.compile(r"\s+")
_TAG_RE = re.compile(r"<[^>]+>")


def _text(raw: str) -> str:
    return _WS_RE.sub(" ", html_lib.unescape(_TAG_RE.sub("", raw or ""))).strip()


_CARD_RE = re.compile(r'<section class="card"([^>]*)>(.*?)</section>', re.S)
_ATTR_RE = re.compile(r'([\w-]+)="([^"]*)"')
_TCNAME_RE = re.compile(r'<span class="tcname">(.*?)</span>', re.S)
_CHECKS_RE = re.compile(r'<div class="checks">(.*?)</div>', re.S)
_CITEM_RE = re.compile(r'<span>(.*?)</span></label>', re.S)

# matches seatchange.yaml's judge.verdict_enum exactly.
VERDICTS = ("SEAT_CHANGED", "PAYMENT_REQUIRED", "DECLINED", "LIVE_AGENT", "NO_DETERMINATION", "UNKNOWN")

# (verdict, phrase pattern) — order in this list does not matter; classify_text() picks whichever
# pattern's LAST match lands latest in the scanned text, not the first pattern that matches.
_SIGNALS: list[tuple[str, re.Pattern]] = [
    ("LIVE_AGENT", re.compile(
        r"live agent|\blah\b|manual handling|transfer(?:red)? to (?:an? )?agent", re.I)),
    ("SEAT_CHANGED", re.compile(
        r"seat has been changed|sc-03a|complete the (?:flow|payment)|payment should process"
        r"|processed successfully|display combined total|\bnormally\b", re.I)),
    ("PAYMENT_REQUIRED", re.compile(
        r"remain on the payment screen|flexpay|split payment|only one form of payment"
        r"|selection should be preserved|choose another option|payment screen", re.I)),
    ("DECLINED", re.compile(
        r"should stop|blocked|not permitted|contact (?:air canada vacations"
        r"|your original booking channel|accessibility services)|group booking"
        r"|no seat map should be shown|has already departed|has been cancelled"
        r"|change should not proceed|no seat change should be recorded"
        r"|original seat should remain unchanged|conflict error|cancel the eupgrade", re.I)),
    ("NO_DETERMINATION", re.compile(
        r"\bretry\b|re-prompt|re-enter|session (?:has )?expired|restart|reject the name"
        r"|invalid code|prompt (?:the )?user to retry|greyed out|no available seats", re.I)),
]

_DEFAULT_BY_CATEGORY = {
    "Happy Path": "SEAT_CHANGED",
    "Eligibility Block": "DECLINED",
    "ID Failure": "NO_DETERMINATION",
    "Auth Failure": "NO_DETERMINATION",
    "Seat Map": "NO_DETERMINATION",
    "Payment": "PAYMENT_REQUIRED",
    "Passenger Rules": "SEAT_CHANGED",
    "Disruption": "LIVE_AGENT",
    "Edge Cases": "UNKNOWN",
}


def classify_text(category: str, lines: list[str]) -> str:
    """Classify one card's outcome from its (title, *checklist-lines) text: the LAST signal match
    (by start position in the `" | "`-joined text) wins; falls back to `category`'s default
    (`_DEFAULT_BY_CATEGORY`, else "UNKNOWN") when no signal phrase is present at all."""
    joined = " | ".join(lines)
    best_verdict, best_pos = None, -1
    for verdict, pattern in _SIGNALS:
        last_match = None
        for match in pattern.finditer(joined):
            last_match = match
        if last_match is not None and last_match.start() > best_pos:
            best_pos = last_match.start()
            best_verdict = verdict
    if best_verdict:
        return best_verdict
    return _DEFAULT_BY_CATEGORY.get(category, "UNKNOWN")


def _card_fields(attrs_raw: str, body: str) -> tuple[str, str, list[str]]:
    """(case_id, category, [title, *checklist_lines]) for one `<section class="card">` match."""
    attrs = dict(_ATTR_RE.findall(attrs_raw))
    case_id = attrs.get("id", "")
    category = attrs.get("data-feat", "")
    tcname_m = _TCNAME_RE.search(body)
    title = _text(tcname_m.group(1)) if tcname_m else ""
    checks_m = _CHECKS_RE.search(body)
    checks = [_text(c) for c in _CITEM_RE.findall(checks_m.group(1))] if checks_m else []
    return case_id, category, [title, *checks]


def outcomes_by_id(html_path: str | Path) -> dict[str, str]:
    """Parse a seatchange gap-doc HTML file and return {case_id: verdict} for every
    `<section class="card">` — independent of catalog/parser.py (see module docstring). One entry
    per card; a card with no checklist and no signal in its title gets its category's default (or
    "UNKNOWN")."""
    text = Path(html_path).read_text(encoding="utf-8")
    out: dict[str, str] = {}
    for attrs_raw, body in _CARD_RE.findall(text):
        case_id, category, lines = _card_fields(attrs_raw, body)
        if case_id:
            out[case_id] = classify_text(category, lines)
    return out


def outcome_for(uc, outcomes: dict[str, str]) -> str:
    """Look up `uc.id`'s outcome in a pre-parsed {case_id: verdict} map (see `outcomes_by_id`).
    Returns "UNKNOWN" if `uc.id` is absent from the map. See `nc_outcome.outcome_for`'s docstring for
    why this looks up a pre-parsed map rather than re-classifying from `uc` alone."""
    return outcomes.get(getattr(uc, "id", ""), "UNKNOWN")
