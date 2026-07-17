"""BAGGAGE (Mid-Journey) bag-event payload builder — a SEPARATE LANE, not the FD Kafka/DDS path.

Baggage is the most divergent feed: there is NO pnr+ticket+FDM message and NO DDS pin. A baggage
"seed" is a stream of SmartSuite BAG EVENTS that a live baggage-rules API then evaluates:

    BagReadyForLoading -> BagLoaded -> BagSeen -> BagMishandled

The rules API decides eligibility live over those events plus contextual facts — days since the bag
was mishandled (e.g. the 21-day window), whether Air Canada is the last carrier (AC vs OAL
responsibility), and whether a delayed-bag report (AHL/DPR) exists. See
docs/superpowers/plans/2026-07-17-baggage-seed.md.

>>> STUB / NOT WIRED <<<
This module only BUILDS the event payloads (offline, deterministic). It does NOT post them to
SmartSuite and does NOT query the baggage-rules API — those are the live half of the lane and are
not implemented yet. The payload SHAPE here is a plausible SmartSuite record envelope; treat it as a
scaffold to be reconciled against the real SmartSuite schema when the live lane is built.

Every timestamp is TODAY-RELATIVE (the baggage analogue of FD's temporal-intent -> flight-date
mapping): the mishandle timestamp is `now - N days` so the age-based rules fire correctly
("within 21 days" -> N<21, "after the 21-day window" -> N>21).
"""
from __future__ import annotations

import datetime
import re

# The bag-event lifecycle, in order. build_event_sequence emits them in exactly this order.
BAG_EVENTS = ("BagReadyForLoading", "BagLoaded", "BagSeen", "BagMishandled")

# Relative minute offsets from the mishandle instant for the pre-mishandle lifecycle events. The
# ready/load/seen events happen around departure; the mishandle is detected on arrival.
_EVENT_OFFSET_MIN = {
    "BagReadyForLoading": -180,
    "BagLoaded": -150,
    "BagSeen": -120,
    "BagMishandled": 0,
}

_DAYS_RE = re.compile(r"(\d+)\s*[- ]?day", re.IGNORECASE)
_NTH_DAY_RE = re.compile(r"(\d+)(?:st|nd|rd|th)\s*day", re.IGNORECASE)
_HRS_RE = re.compile(r"(\d+)\s*hour", re.IGNORECASE)


def mishandle_age_days(uc, *, default: int = 3) -> int:
    """How many days ago the bag was mishandled, read from the case title.

    The gap-doc titles encode the age relative to the rules windows:
      - "within 21 days"            -> a value < 21 (default 3)
      - "after the 21-day window"   -> a value > 21 (window+2)
      - "exactly the 21st day"      -> 21
      - "over 51 days old" / "51+"  -> that many days
      - "1 hour 20 minutes"         -> 0 (same-day short delay)
    Falls back to `default` (3 days, comfortably inside the 21-day window)."""
    t = (getattr(uc, "title", "") or "").lower()
    # explicit Nth-day boundary ("exactly the 21st day")
    m = _NTH_DAY_RE.search(t)
    if m:
        return int(m.group(1))
    # "over N days" / "N+ days" / "N-day"
    m = _DAYS_RE.search(t)
    day_val = int(m.group(1)) if m else None
    if day_val is not None:
        if "after" in t or "over" in t or "+" in t or "beyond" in t or "past" in t or "outside" in t:
            # explicitly outside the named window -> ensure age exceeds it
            return day_val + 2 if ("within" not in t) else max(day_val - 1, 0)
        if "within" in t:
            return min(3, max(day_val - 1, 0)) or 3
        return day_val
    # sub-day short delay ("1 hour 20 minutes", "delayed only 1 hour")
    if _HRS_RE.search(t):
        return 0
    return default


def last_carrier(uc, *, default: str = "AC") -> str:
    """'AC' if Air Canada is the last/handling carrier, else 'OAL' (another airline). Read from the
    title: "Air Canada is last carrier" -> AC; "another airline was the last carrier",
    "OAL", "requires a different airline" -> OAL."""
    t = (getattr(uc, "title", "") or "").lower()
    if ("another airline" in t or "different airline" in t or "oal" in t
            or "star alliance" in t or "star partner" in t):
        return "OAL"
    if "air canada is last carrier" in t or "air canada" in t:
        return "AC"
    return default


def has_delayed_bag_report(uc) -> bool:
    """Whether a delayed-bag report (AHL / DPR) exists, read from the title. Absence-signals
    ("no delayed bag report", "no AHL found", "No AHL / DPR") win over presence-signals."""
    t = (getattr(uc, "title", "") or "").lower()
    if ("no delayed bag report" in t or "no ahl" in t or "no dpr" in t
            or "no delayed bag" in t or "not found" in t or "no record" in t):
        return False
    if ("report found" in t or "ahl exists" in t or "dpr exists" in t or "ahl created" in t
            or "report exists" in t or "delayed bag report found" in t):
        return True
    return True  # most mid-journey cases assume a report exists


def build_bag_event(kind: str, *, bag_tag: str, pnr: str, timestamp: str,
                    station: str = "YYZ", carrier: str = "AC") -> dict:
    """One SmartSuite bag-event record envelope. `kind` must be a member of BAG_EVENTS."""
    if kind not in BAG_EVENTS:
        raise ValueError(f"unknown bag event {kind!r}; expected one of {BAG_EVENTS}")
    status = "MISHANDLED" if kind == "BagMishandled" else "IN_TRANSIT"
    return {
        "record": {
            "eventType": kind,
            "bagTag": bag_tag,
            "pnr": pnr,
            "eventTimestamp": timestamp,
            "station": station,
            "lastCarrier": carrier,
            "status": status,
        }
    }


def _iso(dt: datetime.datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def build_event_sequence(uc, *, bag_tag: str, pnr: str,
                         now: datetime.datetime | None = None,
                         station: str = "YYZ") -> list[dict]:
    """Build the ordered BagReadyForLoading -> ... -> BagMishandled event stream for `uc`, with
    today-relative timestamps: the mishandle instant is `now - mishandle_age_days(uc)`, and the
    earlier lifecycle events precede it by fixed minute offsets. The last carrier is stamped on every
    record from the title. Returns the events in lifecycle order."""
    now = now or datetime.datetime.now(datetime.timezone.utc)
    carrier = last_carrier(uc)
    mishandle_dt = now - datetime.timedelta(days=mishandle_age_days(uc))
    events = []
    for kind in BAG_EVENTS:
        ts = _iso(mishandle_dt + datetime.timedelta(minutes=_EVENT_OFFSET_MIN[kind]))
        events.append(build_bag_event(kind, bag_tag=bag_tag, pnr=pnr, timestamp=ts,
                                      station=station, carrier=carrier))
    return events


def build_case_context(uc, *, now: datetime.datetime | None = None) -> dict:
    """The contextual facts the baggage-rules API evaluates alongside the event stream, all derived
    from the case title. This is what a live query would send/compare against."""
    return {
        "mishandle_age_days": mishandle_age_days(uc),
        "last_carrier": last_carrier(uc),
        "has_delayed_bag_report": has_delayed_bag_report(uc),
        "within_21_day_window": mishandle_age_days(uc) <= 21,
    }
