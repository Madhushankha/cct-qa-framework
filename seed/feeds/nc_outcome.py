"""NC (Name Correction) flow outcome — reads each case's REAL result (CORRECTED / DOCS_REQUIRED /
NOT_ELIGIBLE / LIVE_AGENT / NO_DETERMINATION / UNKNOWN — matching nc.yaml's `judge.verdict_enum`)
directly off the gap-doc card body, independent of catalog/parser.py.

Why this exists: NC has no systemCode (a name correction carries no `FD-<REGIME>-<CLASS>-<n>`-style
code), so `catalog/parser.py`'s `_verdict_from_syscode` — the mechanism every other onboarded feed
relies on to fill `UseCase.verdict` — has nothing to key off of; every nc UseCase.verdict parses as
"". The gap doc carries no `data-out` attribute either (only soc/fd's datagrid cards set that). So
the real outcome only exists as PROSE: the card's title (`<span class="tcname">`) and its Gherkin
"Then" checklist (`<div class="checks"><label class="citem"><span>...</span></label>...</div>`) —
neither of which `catalog/parser.py` captures into any `UseCase` field today (the same kind of gap
`seed.scenario.change()` already documents for the from/to name values). Since `catalog/parser.py`
is out of this module's scope to change, this module re-reads the raw HTML directly instead.

Method — a same last-match-wins heuristic scan, not a validated ground truth: each card's title +
full checklist text (in document order) is scanned for a fixed set of outcome-signal phrases (see
`_SIGNALS`); whichever signal's LAST match lands latest in the text wins, since a card's closing
checklist lines narrate what finally happened (an early "1 document required" mention followed by a
later "successfully corrected" line is a CORRECTED case, not a DOCS_REQUIRED one — the correction
completed after the document step). A card with no signal phrase at all falls back to a per-category
default (`_DEFAULT_BY_CATEGORY`, keyed off the card's `data-feat` — Happy Path/Ineligible/Failure
Handling/Edge Case).

Confidence is NOT uniform: Happy Path (explicit "successfully corrected" wording) and the
channel/carrier-routing Ineligible cases (explicit "blocked"/"live agent"/"contact X" wording) score
highest; Failure Handling and Edge Case cards whose checklist narrates only an intermediate step
(no closing "Then" that states the terminal outcome) fall back to the category default and should be
read as PROVISIONAL. This module has NOT been cross-checked against a live chatbot run — treat every
value here as "our best read of the gap-doc's intent", not a validated verdict. A live CRT/INT run
against a seeded case is the actual source of truth.
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

# matches nc.yaml's judge.verdict_enum exactly.
VERDICTS = ("CORRECTED", "DOCS_REQUIRED", "NOT_ELIGIBLE", "LIVE_AGENT", "NO_DETERMINATION", "UNKNOWN")

# (verdict, phrase pattern) — order in this list does not matter; classify_text() picks whichever
# pattern's LAST match lands latest in the scanned text, not the first pattern that matches.
_SIGNALS: list[tuple[str, re.Pattern]] = [
    ("LIVE_AGENT", re.compile(r"live agent|manual review", re.I)),
    ("CORRECTED", re.compile(
        r"successfully corrected|process(?:ed|es)? successfully|complete(?:d)? successfully"
        r"|return success", re.I)),
    ("DOCS_REQUIRED", re.compile(
        r"document(?:s)?\s*(?:is|are)?\s*required|please upload"
        r"|upload (?:a copy of )?(?:your )?passport|send (?:your )?supporting document", re.I)),
    ("NOT_ELIGIBLE", re.compile(
        r"not permitted|ineligible booking|not eligible|blocked|not supported|fail eligibility"
        r"|group travel desk|another airline|travel agent|employee travel program"
        r"|flight pass program|ac cargo|limited to one|permitted only once", re.I)),
    ("NO_DETERMINATION", re.compile(
        r"should fail|failure messaging|unable to (?:confirm|complete|assist)", re.I)),
]

_DEFAULT_BY_CATEGORY = {
    "Happy Path": "CORRECTED",
    "Ineligible": "NOT_ELIGIBLE",
    "Failure Handling": "NO_DETERMINATION",
    "Edge Case": "UNKNOWN",
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
    """Parse an nc gap-doc HTML file and return {case_id: verdict} for every `<section class="card">`
    — independent of catalog/parser.py (see module docstring). One entry per card; a card with no
    checklist and no signal in its title gets its category's default (or "UNKNOWN")."""
    text = Path(html_path).read_text(encoding="utf-8")
    out: dict[str, str] = {}
    for attrs_raw, body in _CARD_RE.findall(text):
        case_id, category, lines = _card_fields(attrs_raw, body)
        if case_id:
            out[case_id] = classify_text(category, lines)
    return out


def outcome_for(uc, outcomes: dict[str, str]) -> str:
    """Look up `uc.id`'s outcome in a pre-parsed {case_id: verdict} map (see `outcomes_by_id`).
    Returns "UNKNOWN" if `uc.id` is absent from the map (e.g. a card added upstream since the map was
    built). This indirection (rather than re-classifying from `uc.title` alone) is deliberate: a bare
    `UseCase` does not carry the Gherkin checklist text `catalog/parser.py` drops today — only the
    raw HTML does — so a from-`uc`-alone classification would be materially weaker than
    `outcomes_by_id`'s full-checklist read."""
    return outcomes.get(getattr(uc, "id", ""), "UNKNOWN")
