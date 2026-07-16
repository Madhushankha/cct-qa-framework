"""CREATE-prelude for UPDATE feeds (nc, seatchange) — this framework's port of contrail's proven
`pnr_lifecycle.py` (`../cct-cascade/contrail/src/contrail/feeds/pnr_lifecycle.py`).

Why a prelude is needed (contrail's finding, CRT-verified 2026-06, ported here — see
docs/superpowers/plans/2026-07-17-nc-seatchange-seed.md "The CREATE-prelude mechanism"): a bare
UPDATE message on a fresh (never-seen) locator produces NO Aurora write. The change detector
(PassengerNameChangeDetector for a name change, SeatingDetector for a seat change) emits its derived
event, but the downstream ingestion INSERT is FK-blocked — there is no parent `passenger` /
`trip_details` row for it to attach to yet. Worse, a single message can EITHER create the PNR OR
fire a per-element change detector, never both: `PNRCreationDetector`/`GroupPNRDetector` short-
circuit the detector chain the moment either of them fires (kb/source-code/flink/pnr/cctpnr/
detectors/PNRDetectorFactory.java, per contrail's inline comments). So NC/SeatChange's seed path
needs TWO messages: a synthetic CREATE (this module's `build_create_payload`) with the changing
field reverted to a pre-change value, THEN the real UPDATE at the case's actual to-value.

Detector paths this module recognizes (the two this framework's UPDATE feeds use — contrail also
covers segment-status/flight-number/group-size/keyword paths this repo does not yet seed):

| feed       | UPDATE path                                                          |
|------------|-----------------------------------------------------------------------|
| nc         | `^/travelers/(\\d+)/names/(\\d+)/(firstName|middleName|lastName)$`    |
| seatchange | `^/products/(\\d+)/seating$` (the field actually reverted is         |
|            | `seating.seats[0].number`, per contrail — NOT a `subType` discriminator) |

Unlike contrail's `synthesize_create_payload` (which bakes in fixed JOAO/MAIA name and 14C seat
defaults), `build_create_payload` here takes an explicit `revert_fields` map of
{dotted/bracket path -> value} — the caller (a future manifest-driven seed step) decides what the
pre-change value is per case; this module only knows HOW to revert a payload, not WHAT feed-specific
value to revert it to. Path application reuses `seed.engine.set_dotpath` (the same dotted/`[n]`/`[*]`
mutator the generic manifest engine already uses for `apply manifest mutations` elsewhere) rather
than a second hand-rolled path-walker, so a `revert_fields` path is written in exactly the same
syntax a manifest's `mutable` block already uses.

`wait_for` is this framework's equivalent of contrail's `wait_for_passenger_row` /
`wait_for_trip_details`, built on `seed/source.py`'s existing `AuroraSource`/`TripTracerSource`
(a `passengers(pnr)` / `trip(pnr)` read-only surface) instead of contrail's separate
`aurora_adapter.query_dicts`. CAVEAT: `AuroraSource` has no dedicated `trip_details` probe today (it
exposes `trip()`, which reads the `trip` table, not `trip_details`) — `wait_for(..., "trip_details",
...)` uses `trip()` as the nearest available proxy. Per the plan doc, a true `trip_details` probe
(needed because `journey_updates` FKs to `trip_details`, not `passenger`, for the seating family)
would need a new `AuroraSource` method; that is an open item, not resolved by this module — treat a
seatchange `wait_for(..., "trip_details", ...)` result as best-effort until that lands.

All functions here are pure / offline except `wait_for`, which only needs `source` to expose the
`TripTracerSource` protocol (fake or live) — no direct boto3/psycopg2 import in this module.
"""
from __future__ import annotations

import copy
import re
import time

from seed.engine import set_dotpath

# ^/travelers/N/names/M/(firstName|middleName|lastName)$ — PassengerNameChangeDetector's path guard
# (PNRPathUtils.NAME_CHANGE_PATTERN in contrail's source notes).
NAME_CHANGE_PATH = re.compile(r"^/travelers/(\d+)/names/(\d+)/(firstName|middleName|lastName)$")

# ^/products/N/seating$ — SeatingDetector's SEATING_UPDATED path guard
# (PNRPathUtils.SEATING_PATH_PATTERN in contrail's source notes).
SEATING_PATH = re.compile(r"^/products/(\d+)/seating$")

# The two change-detector paths this framework's UPDATE feeds (nc, seatchange) exercise. contrail's
# pnr_lifecycle.py also recognizes segment-status/flight-number/group-size/keyword paths; those
# belong to feeds this framework has not onboarded yet, so are intentionally not ported here.
_PRELUDE_PATHS = (NAME_CHANGE_PATH, SEATING_PATH)


def _events(payload: dict) -> list[dict]:
    ev = (payload.get("events") or {}).get("events") or []
    return [e for e in ev if isinstance(e, dict)]


def needs_create_prelude(payload: dict) -> bool:
    """True if `payload` is an UPDATE at a recognized change-detector path (name-change or seating)
    AND carries no root CREATE (`{eventType:CREATED, currentPath:""}`). A root CREATE would make
    PNRCreationDetector (or GroupPNRDetector) ingest the PNR on its own — no prelude needed then.
    Mirrors contrail's `needs_create_prelude`, restricted to the two paths above."""
    evs = _events(payload)
    has_root_create = any(
        e.get("eventType") == "CREATED" and e.get("currentPath", None) == "" for e in evs)
    if has_root_create:
        return False
    return any(
        e.get("eventType") == "UPDATED"
        and isinstance(e.get("currentPath"), str)
        and any(p.match(e["currentPath"]) for p in _PRELUDE_PATHS)
        for e in evs)


def build_create_payload(payload: dict, revert_fields: dict) -> dict:
    """Derive a CREATE payload from an UPDATE `payload` (this framework's port of contrail's
    `synthesize_create_payload`):

      1. replace `events.events[]` with a single root `{origin: COMPARISON, eventType: CREATED,
         currentPath: ""}` — the PNRCreationDetector "alternative" criterion fires on one CREATED
         event when `ticketingReferences` is non-empty (true for a complete ticketed PNR body);
      2. drop `previousRecord` — only meaningful on an UPDATE's COMPARISON diff, inert (at best) on a
         root CREATE;
      3. set every `revert_fields` path (e.g. `processedPnr.travelers[0].names[0].firstName` ->
         `"JOAO"`) to its given pre-change value, so the LATER real UPDATE is a genuine transition
         and not a no-op.

    Returns a NEW dict — `payload` is not mutated. Paths that don't resolve in `payload` (e.g. a
    revert_fields entry for a traveler index the base template doesn't carry) are silently skipped by
    `set_dotpath` — no exception is raised; inspect the return separately if you need to assert every
    path hit."""
    doc = copy.deepcopy(payload)
    doc.setdefault("events", {})
    doc["events"]["events"] = [{"origin": "COMPARISON", "eventType": "CREATED", "currentPath": ""}]
    doc.pop("previousRecord", None)
    for path, value in (revert_fields or {}).items():
        set_dotpath(doc, path, value)
    return doc


def _locator(pnr_id: str) -> str:
    """`<locator>-<date>` (or a bare locator) -> the 6-char locator every TripTracerSource method is
    keyed on (they already do `substring(pnr_id from 1 for 6)` server-side — see seed/source.py)."""
    return (pnr_id or "")[:6]


# table name -> a (source, locator) -> bool probe. "trip_details" is a PROXY onto trip() — see the
# module docstring's CAVEAT; there is no dedicated trip_details read in AuroraSource today.
_PROBES = {
    "passenger": lambda src, loc: bool(src.passengers(loc)),
    "trip_details": lambda src, loc: src.trip(loc) is not None,
    "trip": lambda src, loc: src.trip(loc) is not None,
}


def wait_for(source, table: str, pnr_id: str, *, timeout_seconds: float = 30,
            poll_seconds: float = 2.0) -> bool:
    """Poll `source` (a `seed.source.TripTracerSource`-shaped object — `FakeSource` offline,
    `AuroraSource` live) until `table`'s row for `pnr_id` materializes, or `timeout_seconds` elapses.
    `table` is one of "passenger" (the name-change prelude's FK target) or "trip_details"/"trip" (the
    seating prelude's — see caveat above). Returns True on materialization, False on timeout.
    Exceptions from a single probe attempt are swallowed and retried (mirrors contrail's
    wait_for_passenger_row/wait_for_trip_details, which likewise treat a transient query error as
    'not yet' rather than a hard failure)."""
    probe = _PROBES.get(table)
    if probe is None:
        raise ValueError(f"wait_for: unknown table '{table}' (known: {sorted(_PROBES)})")
    loc = _locator(pnr_id)
    deadline = time.time() + timeout_seconds
    while True:
        try:
            if probe(source, loc):
                return True
        except Exception:  # noqa: BLE001 — a transient read error is "not yet", not fatal
            pass
        if time.time() >= deadline:
            return False
        time.sleep(poll_seconds)
