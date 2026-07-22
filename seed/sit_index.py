"""Load a reference-pipeline donor index (`_FD_*_index.json`) as a framework Catalog.

The FD SIT gap doc is a scenario SPECIFICATION — 132 titles, outcomes and checkpoints — with no
bookable data: no PNR, no route, no amount and, critically, no systemCode (its `system_code` column
parses as the Priority value). Seeding from it alone would mean inventing determination codes, and
a checkpoint that compares an invented code against our own pin certifies nothing.

The reference pipeline solves this by DONOR MAPPING: every SIT case is bound to a real, previously
proven scenario + DDS determination carrying the exact systemCode the case expects, and that donor
is cloned under a fresh identity. Its per-set index file is the result of that mapping, so reading
the index gives us the real codes/amounts/flags without duplicating the mapping logic.

What we take from the index: the case id, title, systemCode, expected status, amount/currency and
the group/oal flags. What we deliberately do NOT take: the locator, ticket and passenger names —
those are minted fresh per run by `seed.identity`, so a seed from this catalog creates a NEW set of
PNRs rather than colliding with the donor set already live in the environment.

Note `route` in a SIT index holds the regime label ("APPR", "Any", "EU/UK 261"), not a city pair;
the real origin/destination is read from the donor scenario JSON when it is available.
"""
from __future__ import annotations

import json
from pathlib import Path

from catalog.model import Catalog, SeedSpec, UseCase

_STATUS_TO_VERDICT = {
    "ELIGIBLE": "Eligible",
    "NOT_ELIGIBLE": "Not Eligible",
    "NO_DETERMINATION": "No Determination",
    "PENDING": "Pending",
}


def _route_from_donor(scenarios_dir: Path | None, src_scn: str | None) -> str:
    """`ORIGIN-DESTINATION` of the donor's first segment, or "" when unavailable."""
    if not (scenarios_dir and src_scn):
        return ""
    path = scenarios_dir / f"{src_scn}.json"
    if not path.exists():
        return ""
    try:
        segs = json.loads(path.read_text(encoding="utf-8")).get("segments") or []
    except (OSError, ValueError):
        return ""
    if not segs:
        return ""
    first = segs[0]
    o, d = first.get("origin"), first.get("destination")
    return f"{o}-{d}" if o and d else ""


def load_sit_index(index_path, *, feed_id: str = "fd", scenarios_dir=None,
                   default_route: str = "YUL-YYZ") -> Catalog:
    """Build a Catalog from a donor index JSON. `scenarios_dir` (the index's sibling scenario
    corpus) supplies each donor's real route; `default_route` is used when it is not readable."""
    index_path = Path(index_path)
    records = json.loads(index_path.read_text(encoding="utf-8"))
    scenarios_dir = Path(scenarios_dir) if scenarios_dir else index_path.parent
    cases = []
    for rec in records:
        case_id = rec.get("sit") or rec.get("tc") or rec.get("key") or ""
        status = (rec.get("status") or "").upper()
        syscode = rec.get("syscode") or ""
        amount = {}
        if rec.get("amount") is not None:
            amount = {"value": rec["amount"], "currency": rec.get("currency") or "CAD"}
        route = _route_from_donor(scenarios_dir, rec.get("src_scn")) or default_route
        extras = {"donor_scenario": rec.get("src_scn"), "donor_dds": rec.get("src_dds"),
                  "area": rec.get("area"), "outcome": rec.get("outcome"),
                  "priority": rec.get("prio"), "note": rec.get("note")}
        if rec.get("group"):
            extras["group"] = True
        if rec.get("oal"):
            extras["oal"] = True
        if rec.get("loyalty_id"):
            extras["loyalty_id"] = rec["loyalty_id"]
        pax_names = rec.get("pax_names") or []
        if len(pax_names) > 1:
            extras["npax"] = len(pax_names)
        cases.append(UseCase(
            id=case_id,
            regime=(syscode.split("-")[1] if syscode.count("-") >= 2 else ""),
            verdict=_STATUS_TO_VERDICT.get(status, ""),
            system_code=syscode,
            title=rec.get("title") or "",
            third_party=False,
            checkpoint_vector=[],
            customer_intent="",
            expected_transcript=[],
            # `pnr` carries the donor locator only so the seeder's "has bookable data" gate passes;
            # run_seed_all replaces it (and the passenger) with a freshly minted identity.
            seed=SeedSpec(pnr=rec.get("loc") or "", pnr_id=rec.get("pnr_id") or "",
                          passenger=rec.get("pax") or "", ticket=rec.get("ticket") or "",
                          status=status, system_code=syscode, route=route, amount=amount,
                          extras=extras),
            seed_pending=False,
            content_hash=f"sit-index:{case_id}",
        ))
    return Catalog(feed_id=feed_id, checkpoints=[], cases=cases, uncovered=[])
