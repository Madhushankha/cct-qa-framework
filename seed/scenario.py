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
