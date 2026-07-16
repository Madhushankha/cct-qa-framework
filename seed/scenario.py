"""Scenario attributes parsed from the gap-doc case title — env-COMMON (what to test), not env
data. temporal_intent drives the today-relative flight date; delay/status feed the FDM message."""
from __future__ import annotations

import datetime
import re

TEMPORAL = ("completed", "pending", "pre_travel", "no_travel")
_HR_RE = re.compile(r"delay\s*(\d+)\s*hr", re.IGNORECASE)
_BAND_RE = re.compile(r"delay\s*(\d+)\s*[-–]?\s*<?\s*(\d+)?", re.IGNORECASE)
_TIER = {400: 240, 700: 400, 1000: 600}


def temporal_intent(uc) -> str:
    t = (uc.title or "").lower()
    if "pre-travel" in t or "pre travel" in t:
        return "pre_travel"
    if "pending" in t or "72 hours not elapsed" in t or "72 hrs not elapsed" in t:
        return "pending"
    if "no travel" in t or "cancelled" in t:
        return "no_travel"
    return "completed"


def delay_minutes(uc) -> int:
    t = uc.title or ""
    m = _BAND_RE.search(t)
    if m:
        lo = int(m.group(1))
        if lo >= 9:
            return 600
        if lo >= 6:
            return 400
        if lo >= 3:
            return 240
    m = _HR_RE.search(t)
    if m:
        return int(m.group(1)) * 60
    try:
        return _TIER.get(int((uc.seed.amount or {}).get("value", 0)), 240)
    except (TypeError, ValueError):
        return 240


def segment_status(uc) -> str:
    return "UN" if temporal_intent(uc) == "no_travel" else "HK"


_OFFSET_DAYS = {"completed": -7, "pending": -1, "pre_travel": 3, "no_travel": -7}


def scenario_date(intent: str, now: datetime.datetime) -> str:
    return (now.date() + datetime.timedelta(days=_OFFSET_DAYS.get(intent, -7))).isoformat()


def flight_date_for(uc, now: datetime.datetime) -> str:
    return scenario_date(temporal_intent(uc), now)


# --- change (UPDATE feeds: nc, seatchange) -----------------------------------------------------
# nc/seatchange are UPDATE feeds: the seed path needs a CREATE-prelude built from the change's
# 'from' value before sending the real UPDATE at the 'to' value (see the generic-feed-seeder design
# doc's CREATE-prelude section and docs/superpowers/plans/2026-07-17-nc-seatchange-seed.md).

_KIND_BY_FEED = {"nc": "name", "seatchange": "seat"}


def change(uc, feed: str | None = None) -> dict | None:
    """Change event for UPDATE-feed cases: {"kind": "name"|"seat", "from": ..., "to": ...}, or
    None if `uc` carries no change (not an nc/seatchange case).

    `kind` is resolved from `feed` when given ("nc" -> "name", "seatchange" -> "seat" — the
    reliable signal, since a case belongs to whichever feed's gap doc it was parsed from), else
    inferred from the case id prefix (`NameCorrection_*` / `SeatChange_*`). The id-prefix fallback
    is imperfect: one card in the nc gap doc (id `SeatChange_TC049`, title "Name with slight
    misspelling passes identification and completes flow") is mislabeled upstream — pass
    `feed="nc"` to sidestep it.

    `from`/`to` (the concrete old/new name or seat) are None: neither gap doc's cards carry them in
    any field catalog/parser.py currently captures. Both docs have zero <div class="datagrid"> cards
    (seed_pending=True for every case) and zero bot/user transcript rows (`_ROW_RE` matches nothing)
    — the raw Gherkin steps under <details class="orig"> do mention concrete values (e.g.
    "Sarah Chen" -> "Sara Chen" for NameCorrection_TC001) but that text isn't parsed into any
    UseCase field today. Filling from/to needs a parser extension to capture those steps; until
    then this stub carries `kind` (and the CREATE-prelude "does a change exist" check) without the
    concrete values.
    """
    kind = _KIND_BY_FEED.get(feed) if feed else None
    if kind is None:
        id_l = (uc.id or "").lower()
        if id_l.startswith("namecorrection"):
            kind = "name"
        elif id_l.startswith("seatchange"):
            kind = "seat"
    if kind is None:
        return None
    return {"kind": kind, "from": None, "to": None}
