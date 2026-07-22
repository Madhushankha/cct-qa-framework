#!/usr/bin/env python3
"""Scenario engine — turn a declarative scenario document into a sequence of raw
Kafka payloads ready to inject onto `emh-dev.ALTEA-PNRDATA-UAT`.

Model
-----
A scenario is a single JSON document describing:
  1. Identity     — new PNR code + booking_date
  2. Point of sale — office, iata_number, login (agent) details
  3. Passengers   — typed list; each becomes a full Amadeus traveler object
  4. Segments     — typed list; each becomes an Amadeus `product` entry + a
                    flightItineraries/bound reference
  5. Timeline     — ordered version list. Each step produces ONE raw message.
                    Consecutive steps are diffed to produce `previousRecord`
                    (RFC 6902 JSON-Patch) and `events.events[]` COMPARISON events.
  6. Expected cascade — documentation of what should appear downstream
                    (DERIVED / TRANSFORMED / EVENT-DETECTION / RESULT-EVENT-DETECTION
                    / DB tables). Not enforced here; consumed by watchers.
  7. Metadata     — classification, tags, comparison keys (same as v1 schema).

The engine loads a **canvas** — a real `processedPnr` captured from production-like
data — and mutates it per scenario. This gives us coverage of Amadeus fields we
don't want to model (automatedProcesses, queuingOffice, financialValues, etc.)
without having to faithfully regenerate them.

The output is a newline-delimited JSON file (one raw Kafka record per line),
same shape as what `pull_topic.sh` would pull back from `emh-dev.ALTEA-PNRDATA-UAT`.
"""
from __future__ import annotations

import argparse
import copy
import json
import re
import secrets
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
SCHEMA_VERSION = 2


# =============================================================================
# JSON Pointer / JSON Patch (RFC 6901 / 6902 subset, pure stdlib)
# =============================================================================

def _pointer_parts(p: str) -> list[str]:
    if p == "" or p == "/":
        return []
    if not p.startswith("/"):
        raise ValueError(f"invalid JSON pointer: {p!r}")
    return [t.replace("~1", "/").replace("~0", "~") for t in p[1:].split("/")]


def _escape(t: str) -> str:
    return t.replace("~", "~0").replace("/", "~1")


def diff_patch(src: Any, dst: Any, path: str = "") -> list[dict]:
    """RFC 6902 JSON Patch from src → dst.

    Recurses into dicts; treats lists as atomic (replaces whole list on any
    change) — this matches the observed upstream behaviour in B45OZB's
    previousRecord, which doesn't use array-index patches.
    """
    if src == dst:
        return []
    if type(src) is not type(dst) or not isinstance(src, (dict, list)):
        return [{"op": "replace", "path": path or "", "value": copy.deepcopy(dst)}]
    if isinstance(src, dict):
        ops: list[dict] = []
        for k in src:
            if k not in dst:
                ops.append({"op": "remove", "path": f"{path}/{_escape(k)}"})
        for k, v in dst.items():
            sub = f"{path}/{_escape(k)}"
            if k not in src:
                ops.append({"op": "add", "path": sub, "value": copy.deepcopy(v)})
            elif src[k] != v:
                ops.extend(diff_patch(src[k], v, sub))
        return ops
    # list — replace wholesale
    return [{"op": "replace", "path": path or "", "value": copy.deepcopy(dst)}]


def reverse_patch(src: Any, dst: Any, path: str = "") -> list[dict]:
    """Build `previousRecord` — the patch that takes dst (new) back to src (old).

    Matches observed upstream behaviour: remove for added keys, add for
    removed keys, replace for changed values.
    """
    if src == dst:
        return []
    if type(src) is not type(dst) or not isinstance(src, (dict, list)):
        return [{"op": "replace", "path": path or "", "value": copy.deepcopy(src)}]
    if isinstance(src, dict):
        ops: list[dict] = []
        for k, v in src.items():
            sub = f"{path}/{_escape(k)}"
            if k not in dst:
                ops.append({"op": "add", "path": sub, "value": copy.deepcopy(v)})
            elif dst[k] != v:
                ops.extend(reverse_patch(v, dst[k], sub))
        for k in dst:
            if k not in src:
                ops.append({"op": "remove", "path": f"{path}/{_escape(k)}"})
        return ops
    return [{"op": "replace", "path": path or "", "value": copy.deepcopy(src)}]


def forward_patch_to_comparison_events(ops: list[dict]) -> list[dict]:
    """Map forward JSON-Patch ops to the `events.events[]` COMPARISON list.

    Observed upstream shapes:
      add     → {origin:COMPARISON, eventType:CREATED, currentPath}
      remove  → {origin:COMPARISON, eventType:DELETED, previousPath}
      replace → {origin:COMPARISON, eventType:UPDATED, currentPath, previousPath}
    """
    out: list[dict] = []
    for op in ops:
        if op["op"] == "add":
            out.append({"origin": "COMPARISON", "eventType": "CREATED",
                        "currentPath": op["path"]})
        elif op["op"] == "remove":
            out.append({"origin": "COMPARISON", "eventType": "DELETED",
                        "previousPath": op["path"]})
        elif op["op"] == "replace":
            out.append({"origin": "COMPARISON", "eventType": "UPDATED",
                        "currentPath": op["path"], "previousPath": op["path"]})
    return out


# =============================================================================
# ID & timestamp helpers
# =============================================================================

def gen_trigger_log_id() -> str:
    """Format observed in the raw feed: 32 hex '-' 16 hex."""
    return f"{secrets.token_hex(16)}-{secrets.token_hex(8)}"


def ddmmmyy(iso_date: str) -> str:
    return datetime.strptime(iso_date, "%Y-%m-%d").strftime("%d%b%y").upper()


def pack_passport_text(passport: dict, pax: dict, first_name: str, last_name: str) -> str:
    """Rebuild the compact passport 'text' field: P/<nat>/<num>/<issueCountry>/<dobDDMMMYY>/<sex>/<expDDMMMYY>/<LAST>/<FIRST>/H"""
    sex = {"MALE": "M", "FEMALE": "F", "UNKNOWN": "U"}.get(
        passport.get("gender", "UNKNOWN").upper(), "U"
    )
    return "/".join([
        "P",
        passport.get("nationality", "CAN"),
        passport["number"],
        passport.get("issuance_country", "CAN"),
        ddmmmyy(pax["date_of_birth"]),
        sex,
        ddmmmyy(passport.get("expiry", "2040-01-01")),
        last_name.upper(), first_name.upper(), "H",
    ])


# =============================================================================
# State builders — scenario → Amadeus processedPnr subtree
# =============================================================================

def build_pos(pos: dict, include_duty: bool = True) -> dict:
    """Build an Amadeus pointOfSale block from the scenario's POS spec."""
    login = {
        "numericSign": pos["agent_numeric_sign"],
        "initials": pos["agent_initials"],
        "countryCode": pos.get("agent_country", "CA"),
        "cityCode": pos.get("agent_city", "YYZ"),
    }
    if include_duty and pos.get("duty_code"):
        login["dutyCode"] = pos["duty_code"]
    return {
        "office": {
            "id": pos["office_id"],
            "iataNumber": pos["iata_number"],
            "systemCode": pos.get("system_code", "AC"),
            "agentType": pos.get("agent_type", "AIRLINE"),
        },
        "login": login,
    }


def build_traveler(pax: dict, pnr_id: str, index: int, at: str, pos: dict) -> dict:
    """Build a raw Amadeus traveler object.

    Shape (from observed emh-dev.ALTEA-PNRDATA-UAT):
      type: "stakeholder"
      id: "{pnr_id}-PT-N"
      sourceId: Amadeus internal hex id
      passengerTypeCode: ADT/CHD/INF
      names: [{firstName, lastName}]
      dateOfBirth: YYYY-MM-DD (top-level, NOT inside passport doc)
      gender: UNKNOWN/MALE/FEMALE
      identityDocuments: [passport doc]
      contacts: {collection: [refs to processedPnr.contacts[]]}

    NOTE: previously I built the post-Flink DERIVED-PNR shape
    (travelerId/firstName/lastName/travelerDocuments/contacts:[])
    by mistake — Flink extracted empty strings because none of those keys
    existed in the real raw schema. Fixed to emit the pre-Flink raw shape.
    """
    tid = f"{pnr_id}-PT-{index}"
    first = pax["first_name"].upper()
    last = pax["last_name"].upper()
    traveler: dict = {
        "type": "stakeholder",
        "id": tid,
        "sourceId": secrets.token_hex(8).upper(),
        "passengerTypeCode": pax.get("type", "ADT"),
        "names": [{"firstName": first, "lastName": last}],
        "dateOfBirth": pax["date_of_birth"],
        "gender": pax.get("gender", "UNKNOWN"),
        "identityDocuments": [],
        "contacts": {"collection": []},
    }
    passport = pax.get("passport")
    if passport:
        traveler["identityDocuments"].append({
            "type": "service",
            "id": f"{pnr_id}-OT-{100 + index}",
            "code": "DOCS",
            "subType": "SPECIAL_SERVICE_REQUEST",
            "serviceProvider": {"code": "AC"},
            "status": "HK",
            "nip": 1,
            "creation": {"dateTime": at, "pointOfSale": build_pos(pos, include_duty=False)},
            "document": {
                "documentType": "PASSPORT",
                "number": passport["number"],
                "expiryDate": passport.get("expiry", "2040-01-01"),
                "issuanceCountry": passport.get("issuance_country", "CAN"),
                "nationality": passport.get("nationality", "CAN"),
                "gender": passport.get("gender", "UNKNOWN"),
                "name": {"fullName": f"{first} {last}", "firstName": first, "lastName": last},
                "birthDate": pax["date_of_birth"],
            },
            "text": pack_passport_text(passport, pax, first, last),
        })
    # Contact refs are populated by build_contacts() below after all contact
    # ids are minted; easier to resolve once than thread through here.
    return traveler


def build_contacts(scenario: dict, pnr_id: str) -> tuple[list[dict], dict[int, list[str]]]:
    """Build the top-level processedPnr.contacts[] array.

    Returns (contacts_list, per_pax_contact_ids) where per_pax_contact_ids[i]
    is the list of contact ids referencing passenger at index i (1-based).
    """
    contacts: list[dict] = []
    per_pax: dict[int, list[str]] = {}
    pax_specs = scenario.get("passengers", [])
    counter = 200
    for i, pax in enumerate(pax_specs, start=1):
        per_pax[i] = []
        pax_id = f"{pnr_id}-PT-{i}"
        if pax.get("email"):
            counter += 1
            cid = f"{pnr_id}-OT-{counter}"
            contacts.append({
                "type": "contact",
                "id": cid,
                "email": {"address": pax["email"]},
                "language": pax.get("language", "EN"),
                "purpose": ["NOTIFICATION"],
                "travelers": {"collection": [
                    {"type": "stakeholder", "id": pax_id, "ref": "processedPnr.travelers"}
                ]},
            })
            per_pax[i].append(cid)
        if pax.get("phone"):
            counter += 1
            cid = f"{pnr_id}-OT-{counter}"
            contacts.append({
                "type": "contact",
                "id": cid,
                "phone": {"category": pax.get("phone_category", "PERSONAL"),
                          "deviceType": pax.get("phone_device", "MOBILE"),
                          "number": pax["phone"]},
                "language": pax.get("language", "EN"),
                "purpose": ["NOTIFICATION"],
                "travelers": {"collection": [
                    {"type": "stakeholder", "id": pax_id, "ref": "processedPnr.travelers"}
                ]},
            })
            per_pax[i].append(cid)
    return contacts, per_pax


def build_product(seg: dict, pnr_id: str, index: int, pax_count: int) -> dict:
    """Build one entry of `processedPnr.products[]` from a segment spec."""
    sid = f"{pnr_id}-ST-{index}"
    air = {
        "departure": {"iataCode": seg["origin"],
                      "localDateTime": seg["dep_local"]},
        "arrival":   {"iataCode": seg["destination"],
                      "localDateTime": seg["arr_local"]},
        "carrierCode": seg["carrier"],
        "number": str(seg["flight_number"]),
        "aircraft": {"code": seg.get("aircraft", "")},
        "class": seg.get("cabin", "Y"),
        "cabin": seg.get("cabin", "Y"),
        "operating": {
            "carrierCode": seg.get("operating_carrier", seg["carrier"]),
            "number": str(seg.get("operating_flight_number", seg["flight_number"])),
            "class": seg.get("cabin", "Y"),
        },
        "bookingDateTime": seg["booking_datetime"],
        "status": seg.get("status", "HK"),
        "isOpenNumber": False,
        "isInformational": False,
        "yieldData": {
            "subClass": {"value": 0,
                         "pointOfSale": {"office": {"systemCode": seg["carrier"]},
                                         "login": {"countryCode": "CA"}}},
            "bidPrice": 0, "effectiveYield": 0,
            "ondYield": {"origin": seg["origin"], "destination": seg["destination"], "yield": 0}
        }
    }
    if seg.get("dep_utc"):
        air["departure"]["utcDateTime"] = seg["dep_utc"]
    if seg.get("arr_utc"):
        air["arrival"]["utcDateTime"] = seg["arr_utc"]
    if seg.get("arrival_terminal"):
        air["arrival"]["terminal"] = seg["arrival_terminal"]
    product: dict = {
        "type": "product", "subType": "AIR", "id": sid,
        "airSegment": air,
        "travelers": {"collection": [
            {"type": "stakeholder", "id": f"{pnr_id}-PT-{i + 1}", "ref": "processedPnr.travelers"}
            for i in range(pax_count)
        ]},
    }
    return product


def build_itineraries(segments: list[dict], pnr_id: str) -> list[dict]:
    """Collapse consecutive segments sharing origin/destination into bounds.

    A "bound" is one directional journey (e.g. YYZ→YVR outbound). Sequential
    segments after a ground break become a new bound. For simple single-segment
    or round-trip scenarios, we group by contiguous progression: if segment[i]
    origin matches segment[i-1] destination, it's part of the same bound.
    """
    if not segments:
        return []
    bounds: list[list[int]] = []
    if any("bound" in s for s in segments):
        # Explicit bound override: group segments by their declared "bound" value
        # (stable first-seen order). Lets round-trips model a true outbound +
        # return as two bounds, which the airport-contiguity heuristic below
        # cannot (the turnaround airport is shared, e.g. YUL->YYZ ... YYZ->YUL).
        order: list = []
        groups: dict = {}
        for i, s in enumerate(segments):
            b = s.get("bound", 1)
            if b not in groups:
                groups[b] = []
                order.append(b)
            groups[b].append(i)
        bounds = [groups[b] for b in order]
    else:
        cur: list[int] = [0]
        for i in range(1, len(segments)):
            if segments[i]["origin"] == segments[i - 1]["destination"]:
                cur.append(i)
            else:
                bounds.append(cur)
                cur = [i]
        bounds.append(cur)

    out: list[dict] = []
    for b in bounds:
        first, last = b[0], b[-1]
        out.append({
            "type": "JOURNEY_SERVER_BOUND",
            "originIataCode": segments[first]["origin"],
            "destinationIataCode": segments[last]["destination"],
            "flights": [{"flightSegment": {
                "type": "product",
                "id": f"{pnr_id}-ST-{i + 1}",
                "ref": "processedPnr.products"}} for i in b],
        })
    return out


# =============================================================================
# Canvas application
# =============================================================================

def _rewrite_by_string_sub(node: Any, old_to_new: dict[str, str]) -> Any:
    """Walk a JSON tree; for every string leaf, apply longest-first substring
    replacement. Used to scrub residual identifiers inherited from the canvas
    (e.g. `B45OZB-2026-04-22-OT-25` embedded in automatedProcesses).
    """
    if isinstance(node, str):
        s = node
        for old in sorted(old_to_new, key=len, reverse=True):
            if old and old in s:
                s = s.replace(old, old_to_new[old])
        return s
    if isinstance(node, dict):
        return {k: _rewrite_by_string_sub(v, old_to_new) for k, v in node.items()}
    if isinstance(node, list):
        return [_rewrite_by_string_sub(v, old_to_new) for v in node]
    return node


def apply_scenario(canvas: dict, scenario: dict, booking_at: str, modified_at: str) -> dict:
    """Render the baseline processedPnr from canvas + scenario identity/pax/seg/POS.

    `booking_at`  — the PNR's original creation timestamp (constant across versions).
                    Used for creation.dateTime, traveler doc creation, etc.
    `modified_at` — timestamp of the CURRENT timeline step. Used for
                    lastModification.dateTime and nothing else.
    """
    canvas_processed = canvas["processedPnr"]
    canvas_pnr_id = canvas_processed["id"]
    canvas_pnr = canvas_processed["bookingIdentifier"]
    # Capture canvas POS identifiers so we can scrub any occurrences that are
    # baked into nested fields (products[].airSegment.yieldData.pointOfSale,
    # automatedProcesses[], fareElements, etc.)
    canvas_office_id = canvas_processed.get("lastModification", {}).get("pointOfSale", {}).get("office", {}).get("id")
    canvas_iata = canvas_processed.get("lastModification", {}).get("pointOfSale", {}).get("office", {}).get("iataNumber")

    pnr = scenario["identity"]["pnr"].upper()
    booking_date = scenario["identity"]["booking_date"]
    pnr_id = f"{pnr}-{booking_date}"

    pp = copy.deepcopy(canvas_processed)
    pp["bookingIdentifier"] = pnr
    pp["id"] = pnr_id
    pp["type"] = scenario["identity"].get("type", "PNR")
    pp["version"] = "1"  # overridden per timeline step

    # ticketingReferences is fully scenario-driven (if the scenario's timeline
    # triggers ticketing). Strip it from canvas so we never inherit stale
    # traveler/document references from the source PNR.
    pp.pop("ticketingReferences", None)

    pos = scenario["point_of_sale"]
    pp["lastModification"] = {
        "dateTime": modified_at,
        "pointOfSale": build_pos(pos, include_duty=True),
        "comment": scenario.get("last_modification_comment", f"SCN-{scenario['scenario_id']}"),
    }
    pp["creation"] = {
        "dateTime": booking_at,
        "pointOfSale": build_pos(pos, include_duty=False),
        "comment": scenario.get("creation_comment", f"SCN-{scenario['scenario_id']}"),
    }
    pp["owner"] = {"office": build_pos(pos, include_duty=False)["office"],
                   "login": build_pos(pos, include_duty=False)["login"]}
    pp["queuingOffice"] = build_pos(pos, include_duty=False)["office"]

    # Rebuild travelers, products, itineraries from scenario spec — use
    # booking_at so the traveler doc creation timestamps stay constant across
    # versions (a pax document added at booking doesn't get re-created just
    # because the PNR's version number bumps)
    pax_specs = scenario.get("passengers", [])
    seg_specs = scenario.get("segments", [])
    pp["travelers"] = [build_traveler(pax, pnr_id, i + 1, booking_at, pos)
                       for i, pax in enumerate(pax_specs)]
    pp["products"] = [build_product(seg, pnr_id, i + 1, len(pax_specs))
                      for i, seg in enumerate(seg_specs)]
    pp["flightItineraries"] = build_itineraries(seg_specs, pnr_id)

    # Build top-level contacts[] and wire each traveler's contacts.collection
    # to reference them (Amadeus raw model is ref-based, not inline).
    contacts, per_pax_contact_ids = build_contacts(scenario, pnr_id)
    pp["contacts"] = contacts
    for i, t in enumerate(pp["travelers"], start=1):
        t["contacts"] = {"collection": [
            {"type": "contact", "id": cid, "ref": "processedPnr.contacts"}
            for cid in per_pax_contact_ids.get(i, [])
        ]}

    # Scrub any residual canvas-specific identifiers embedded in
    # automatedProcesses, paymentMethods, fareElements, yieldData.pointOfSale, etc.
    scrub = {canvas_pnr_id: pnr_id, canvas_pnr: pnr}
    if canvas_office_id and canvas_office_id != pos["office_id"]:
        scrub[canvas_office_id] = pos["office_id"]
    if canvas_iata and canvas_iata != pos["iata_number"]:
        scrub[canvas_iata] = pos["iata_number"]
    pp = _rewrite_by_string_sub(pp, scrub)

    return pp


def build_ticketing_references(scenario: dict, pnr_id: str, at: str, pos: dict) -> list[dict]:
    """Build scenario-driven ticketingReferences (one entry per passenger).

    Uses ETicket numbers from scenario.ticketing.tickets (if provided) or
    generates placeholder numbers. Each reference is linked to the
    corresponding traveler and to all segment products.
    """
    pax_specs = scenario.get("passengers", [])
    seg_specs = scenario.get("segments", [])
    ticketing_cfg = scenario.get("ticketing") or {}
    issuance_date = ticketing_cfg.get("issuance_local_date", at[:10])
    fare = ticketing_cfg.get("fare", {"amount": "0.00", "currency": "CAD"})
    ticket_numbers = ticketing_cfg.get("ticket_numbers") or []

    refs = []
    for i, _pax in enumerate(pax_specs, start=1):
        tkt_num = ticket_numbers[i - 1] if len(ticket_numbers) >= i else f"0000000000{i:03d}"
        refs.append({
            "type": "ticketing-reference",
            "id": f"{pnr_id}-OT-{30 + i}",
            "referenceTypeCode": "FA",
            "documents": [{
                "documentType": "ETICKET",
                "primaryDocumentNumber": tkt_num,
                "status": "ISSUED",
                "issuanceLocalDate": issuance_date,
                "issuingOriginatorOffice": {
                    "id": pos["office_id"],
                    "iataNumber": pos["iata_number"],
                    "systemCode": pos.get("system_code", "AC"),
                },
                "quotationTotalFare": fare,
                "coupons": [{"sequenceNumber": j + 1,
                             "product": {"type": "product",
                                         "id": f"{pnr_id}-ST-{j + 1}",
                                         "ref": "processedPnr.products"}}
                            for j in range(len(seg_specs))],
            }],
            "isInfant": False,
            "traveler": {"type": "stakeholder",
                         "id": f"{pnr_id}-PT-{i}",
                         "ref": "processedPnr.travelers"},
            "products": {"collection": [{"type": "product",
                                         "id": f"{pnr_id}-ST-{j + 1}",
                                         "ref": "processedPnr.products"}
                                        for j in range(len(seg_specs))]},
        })
    return refs


def _rewrite_contacts(contacts: list, pnr_id: str) -> list:
    out = []
    for i, c in enumerate(contacts, start=1):
        c2 = copy.deepcopy(c)
        if "id" in c2 and isinstance(c2["id"], str):
            c2["id"] = f"{pnr_id}-OC-{i}"
        out.append(c2)
    return out


def apply_timeline_step(pp_baseline: dict, step: dict) -> dict:
    """Take the baseline processedPnr and return the version-specific variant
    for this timeline step.

    Supports:
      - bootstrap: remove ticketingReferences (pre-ticketing stub)
      - ticketing_added: baseline + ensure ticketingReferences present
      - custom: arbitrary JSON-Pointer-style overrides in `step.overrides`
                (`__DELETE__` as value removes the pointer target)
    """
    pp = copy.deepcopy(pp_baseline)
    pp["version"] = str(step["version"])
    if "at" in step and "lastModification" in pp:
        pp["lastModification"]["dateTime"] = step["at"]

    action = step.get("action", "custom")
    if action == "bootstrap":
        pp.pop("ticketingReferences", None)
    elif action == "ticketing_added":
        scenario = step.get("_scenario")  # threaded in by render_scenario
        if scenario is not None:
            pp["ticketingReferences"] = build_ticketing_references(
                scenario, pp["id"], pp["lastModification"]["dateTime"],
                scenario["point_of_sale"],
            )
    elif action == "cancel_pnr":
        for prod in pp.get("products", []):
            if "airSegment" in prod:
                prod["airSegment"]["status"] = step.get("cancelled_status", "XX")
    elif action == "custom":
        pass
    else:
        raise ValueError(f"unknown step.action: {action!r}")

    for pointer, value in (step.get("overrides") or {}).items():
        if value == "__DELETE__":
            _pointer_delete(pp, pointer)
        else:
            _pointer_set(pp, pointer, value)
    return pp


def _pointer_delete(obj: Any, pointer: str) -> None:
    parts = _pointer_parts(pointer)
    if not parts:
        return
    cur = obj
    for p in parts[:-1]:
        if isinstance(cur, list):
            cur = cur[int(p)]
        else:
            cur = cur[p]
    last = parts[-1]
    if isinstance(cur, list):
        del cur[int(last)]
    elif isinstance(cur, dict) and last in cur:
        del cur[last]


def _pointer_set(obj: Any, pointer: str, value: Any) -> None:
    parts = _pointer_parts(pointer)
    cur = obj
    for p in parts[:-1]:
        if isinstance(cur, list):
            cur = cur[int(p)]
        else:
            if p not in cur:
                cur[p] = {}
            cur = cur[p]
    last = parts[-1]
    if isinstance(cur, list):
        idx = int(last)
        while len(cur) <= idx:
            cur.append(None)
        cur[idx] = value
    else:
        cur[last] = value


# =============================================================================
# Raw Kafka record assembly
# =============================================================================

def assemble_raw_record(
    pnr_id: str,
    pp: dict,
    previous_pp: dict | None,
    at_utc: datetime,
    topic: str = "emh-dev.ALTEA-PNRDATA-UAT",
) -> dict:
    """Produce the full raw Kafka record shape that matches emh-dev.ALTEA-PNRDATA-UAT."""
    if previous_pp is None:
        forward = [{"op": "add", "path": "", "value": copy.deepcopy(pp)}]
        prev_record: list[dict] = []
        events = [{"origin": "COMPARISON", "eventType": "CREATED", "currentPath": ""}]
    else:
        forward = diff_patch(previous_pp, pp)
        prev_record = reverse_patch(previous_pp, pp)
        events = forward_patch_to_comparison_events(forward)

    origin_ts = at_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
    ts_ms = int(at_utc.timestamp() * 1000)
    return {
        "__meta": {
            "topic": topic, "offset": None, "partition": None,
            "ts_ms": ts_ms, "key": "",
        },
        "payload": {
            "meta": {
                "triggerEventLog": {"id": gen_trigger_log_id()},
                "version": "1.13.0",
            },
            "events": {
                "recordDomain": "PNR",
                "recordId": pnr_id,
                "originFeedTimeStamp": origin_ts,
                "events": events,
            },
            **({"previousRecord": prev_record} if prev_record else {}),
            "processedPnr": pp,
        },
    }


# =============================================================================
# Orchestration
# =============================================================================

def render_scenario(scenario: dict, canvas: dict) -> list[dict]:
    """Run the scenario timeline; return a list of raw Kafka records.

    Each record in the list corresponds to one version. Emit all of them to
    `emh-dev.ALTEA-PNRDATA-UAT` (in order) to replay the scenario.
    """
    pnr = scenario["identity"]["pnr"].upper()
    booking_date = scenario["identity"]["booking_date"]
    pnr_id = f"{pnr}-{booking_date}"

    timeline = scenario.get("timeline") or []
    if not timeline:
        raise ValueError("scenario.timeline is empty — need at least one step")

    # The first step's `at` is the PNR's booking moment — all creation
    # timestamps (PNR, traveler docs, segment bookingDateTime echoes, etc.) use
    # it consistently, so version bumps don't spuriously diff those fields.
    booking_at = timeline[0]["at"]

    records: list[dict] = []
    previous_pp: dict | None = None
    for step in timeline:
        at_str = step["at"]
        at_utc = datetime.fromisoformat(at_str.replace("Z", "+00:00")).astimezone(timezone.utc)
        baseline = apply_scenario(canvas, scenario, booking_at, at_str)
        step_with_scenario = {**step, "_scenario": scenario}
        pp = apply_timeline_step(baseline, step_with_scenario)
        records.append(assemble_raw_record(pnr_id, pp, previous_pp, at_utc))
        previous_pp = pp
    return records


def validate_scenario(scenario: dict, canvas: dict) -> list[str]:
    """Lightweight schema checks — returns list of issue strings (empty = OK)."""
    issues: list[str] = []
    required_top = ["scenario_id", "identity", "point_of_sale", "passengers",
                    "segments", "timeline"]
    for k in required_top:
        if k not in scenario:
            issues.append(f"missing required top-level key: {k}")
    ident = scenario.get("identity", {})
    if "pnr" not in ident or "booking_date" not in ident:
        issues.append("identity must have pnr and booking_date")
    else:
        if not re.match(r"^[A-Z0-9]{6}$", ident["pnr"].upper()):
            issues.append(f"identity.pnr must be 6 alphanumerics, got {ident['pnr']!r}")
        if not re.match(r"^\d{4}-\d{2}-\d{2}$", ident["booking_date"]):
            issues.append(f"identity.booking_date must be YYYY-MM-DD, got {ident['booking_date']!r}")
    if not scenario.get("timeline"):
        issues.append("timeline must have at least one step")
    if not canvas.get("processedPnr"):
        issues.append("canvas has no processedPnr — invalid canvas file")
    return issues


def resolve_canvas_path(scenario: dict, scenario_dir: Path) -> Path:
    cp = scenario.get("canvas")
    if not cp:
        raise ValueError("scenario.canvas is required (path to canvas .json)")
    p = Path(cp)
    if not p.is_absolute():
        # try relative to scenarios/ root first, then the scenario file's directory
        for base in [REPO_ROOT / "scenarios", scenario_dir]:
            cand = (base / p).resolve()
            if cand.exists():
                return cand
    return p


# =============================================================================
# CLI
# =============================================================================

def _cli() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    render = sub.add_parser("render", help="render a scenario to raw-event ndjson")
    render.add_argument("--scenario", required=True)
    render.add_argument("--canvas", help="override scenario.canvas")
    render.add_argument("--out", required=True, help="output ndjson path")
    render.add_argument("--pretty", action="store_true",
                        help="pretty-print JSON (one pretty record per blank-line-separated block)")

    validate = sub.add_parser("validate", help="sanity-check a scenario")
    validate.add_argument("--scenario", required=True)
    validate.add_argument("--canvas", help="override scenario.canvas")

    args = ap.parse_args()

    scenario_path = Path(args.scenario).resolve()
    scenario = json.loads(scenario_path.read_text())
    canvas_path = Path(args.canvas).resolve() if args.canvas \
        else resolve_canvas_path(scenario, scenario_path.parent)
    canvas = json.loads(canvas_path.read_text())

    issues = validate_scenario(scenario, canvas)
    if issues:
        for i in issues:
            print(f"[scenario_engine] ERR: {i}", file=sys.stderr)
        return 2

    if args.cmd == "validate":
        print(f"[scenario_engine] OK: {scenario_path.name} (canvas={canvas_path.name})")
        return 0

    records = render_scenario(scenario, canvas)
    with open(args.out, "w") as f:
        for r in records:
            if args.pretty:
                f.write(json.dumps(r, indent=2) + "\n\n")
            else:
                f.write(json.dumps(r, separators=(",", ":")) + "\n")
    print(f"[scenario_engine] rendered {len(records)} records → {args.out}")
    for i, r in enumerate(records):
        pp = r["payload"]["processedPnr"]
        ev = r["payload"]["events"]["events"]
        prev = r["payload"].get("previousRecord", [])
        print(f"    step {i}: version={pp['version']}  events={len(ev)}  previousRecord_ops={len(prev)}")
    return 0


if __name__ == "__main__":
    sys.exit(_cli())
