#!/usr/bin/env python3
"""
Generate FD_UAT (Tiroshan) test-data artifacts for FD_TC_001..005 — INT env.

For each test case this emits TWO files (the two sources the Ask AC bot reads,
per docs/fd-int-e2e-data-creation.md):

  1. BOOKING side  -> scenarios/fd-sit/<PNR>-<date>.json
       declarative v2 scenario consumed by scenario_engine.py render
       (current/flown itinerary; rebooking history is summarised in tags/notes).

  2. DISRUPTION side -> scenarios/fd-sit/_dds-templates/<PNR>-<date>.dds.json
       the DDS response.json that gets PUT to S3 and pinned via execution_traces.
       Bot reads the cash amount ONLY from
       compensationEligibility[].passengerEligibility[].compensationDetails.amount.

All 5 cases are APPR / ELIGIBLE / CAD 400 / DELAY_3_TO_LT_6_HOURS (Tier 1);
they differ in passenger, itinerary shape (rebooking pattern) and MSL delay code.

Identity: spec names from the FD_UAT sheet; email/phone use the QA mailbox with
+sub-addressing so OTP/auth works for the tester. 6-char ZZ-prefix locators
(real-style, not UA#### which the bot parses as a flight number).

Usage:  python3 scripts/generate_fd_tc_data.py
        (idempotent; rewrites the 10 files)
"""
import json
from datetime import datetime, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
FD_SIT = HERE.parent / "scenarios" / "fd-sit"
DDS_DIR = FD_SIT / "_dds-templates"

DATE = "2026-06-15"            # flight date == part of pnrId
ISSUE = "2026-06-01"
QA_MAIL = "Chathuranga.VirajThennakoon@aircanada.ca"   # OTP/auth mailbox on every PNR contact
UTC_OFFSET_H = 4               # all airports here are Eastern (YUL/YYZ/YOW/YKF) => local+4h = UTC


def utc(date, hhmm):
    dt = datetime.fromisoformat(f"{date}T{hhmm}:00") + timedelta(hours=UTC_OFFSET_H)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def iso(date, hhmm):
    return f"{date}T{hhmm}:00+00:00"


# ---- test-case specs -------------------------------------------------------
# seg: (flight_no, origin, dest, dep_local, sched_arr_local)
TCS = [
    {
        "pnr": "ZZTC01", "tc": "FD_TC_001", "sub": "tc001",
        "name": ("CATHERINE", "BOUCHARD"), "gender": "FEMALE", "aeroplan": None,
        "phone": "+14165551001",
        "title": "FD_TC_001: APPR 4hr delay CAD 400 cash - Catherine Bouchard (single pax, 1 leg, no changes)",
        "desc": "Travel Completed | APPR | Controllable code 64 | Delay 3-<6h | Cash | Single Pax | 1 Leg | No Changes. Bot quotes CAD 400.",
        "segs": [("301", "YUL", "YYZ", "10:00", "14:00")],
        "promised": [("301", "YUL", "YYZ", "10:00", "14:00")],   # promise == scheduled (no changes)
        "actual_arr": "18:00", "delay_min": 240, "msl_idx": 0, "delay_code": "64",
        "reason_text": "Your flight arrived more than 3 hours late due to a reason within Air Canada's control.",
        "reason": "FLIGHT_CREW_SHORTAGE",
        "tags": ["single-pax", "single-leg", "no-changes", "cash"],
    },
    {
        "pnr": "ZZTC02", "tc": "FD_TC_002", "sub": "tc002",
        "name": ("MARIE-CLAIRE", "DUBOIS"), "gender": "FEMALE", "aeroplan": "9876543210",
        "phone": "+14165551002",
        "title": "FD_TC_002: APPR 4hr delay CAD 400 (AC Wallet $480) - Marie-Claire Dubois",
        "desc": "Same disruption as TC001 but Aeroplan linked -> AC Wallet offered (+20% => $480 at payment). DDS base amount stays CAD 400.",
        "segs": [("302", "YUL", "YYZ", "10:00", "14:00")],
        "promised": [("302", "YUL", "YYZ", "10:00", "14:00")],
        "actual_arr": "18:00", "delay_min": 240, "msl_idx": 0, "delay_code": "64",
        "reason_text": "Your flight arrived more than 3 hours late due to a reason within Air Canada's control.",
        "reason": "FLIGHT_CREW_SHORTAGE",
        "tags": ["single-pax", "single-leg", "ac-wallet", "aeroplan"],
    },
    {
        "pnr": "ZZTC03", "tc": "FD_TC_003", "sub": "tc003",
        "name": ("HUGO", "VILLENEUVE"), "gender": "MALE", "aeroplan": None,
        "phone": "+14165551003",
        "title": "FD_TC_003: APPR VOL->INVOL ONE_TO_MANY (1->2 legs) 4hr CAD 400 - Hugo Villeneuve",
        "desc": "VOL (D-10 direct->direct, promise=13:00) then INVOL (D-3 direct->connecting YUL-YOW-YYZ). Promise=last VOL (NOT 14-day mark). Delay measured at final dest YYZ.",
        "segs": [("8101", "YUL", "YOW", "14:00", "15:00"), ("8201", "YOW", "YYZ", "16:00", "17:00")],
        "promised": [("425", "YUL", "YYZ", "10:00", "13:00")],   # last VOL direct, arr 13:00
        "actual_arr": "17:00", "delay_min": 240, "msl_idx": 1, "delay_code": "67",
        "reason_text": "Your flight arrived more than 3 hours late due to a reason within Air Canada's control.",
        "reason": "CABIN_CREW_SHORTAGE",
        "tags": ["single-pax", "multi-leg", "vol-then-invol", "one-to-many", "rebooking"],
    },
    {
        "pnr": "ZZTC04", "tc": "FD_TC_004", "sub": "tc004",
        "name": ("CAMILLE", "BROSSEAU"), "gender": "FEMALE", "aeroplan": None,
        "phone": "+14165551004",
        "title": "FD_TC_004: APPR INVOL->VOL(+ve) MANY_TO_ONE (2->1 leg) net 4hr CAD 400 - Camille Brosseau",
        "desc": "INVOL (D-3 connecting->direct) then VOL(+2h later, D-1). Positive VOL DEDUCTED: total 6h - 2h = net 4h. Promise=14-day mark 10:00.",
        "segs": [("427", "YUL", "YYZ", "12:00", "16:00")],
        "promised": [("8102", "YUL", "YOW", "08:00", "09:00"), ("8202", "YOW", "YYZ", "09:30", "10:00")],
        "actual_arr": "16:00", "delay_min": 240, "msl_idx": 0, "delay_code": "63",
        "reason_text": "Your flight arrived more than 3 hours late due to a reason within Air Canada's control.",
        "reason": "LATE_CREW_BOARDING",
        "tags": ["single-pax", "single-leg-after-consolidation", "invol-then-vol", "many-to-one",
                 "positive-deduction", "net-delay-4h"],
    },
    {
        "pnr": "ZZTC05", "tc": "FD_TC_005", "sub": "tc005",
        "name": ("VALERIE", "DUPONT"), "gender": "FEMALE", "aeroplan": None,
        "phone": "+14165551005",
        "title": "FD_TC_005: APPR INVOL->VOL(-ve) MANY_TO_MANY (2->2 legs) 5hr CAD 400 - Valerie Dupont",
        "desc": "INVOL (D-3 reroute via YKF) then VOL(-2h earlier, D-1). Negative VOL NOT deducted (pax was mitigating): full 5h delay. Promise=14-day mark 10:00.",
        "segs": [("8302", "YUL", "YKF", "10:00", "11:30"), ("8402", "YKF", "YYZ", "12:30", "15:00")],
        "promised": [("8103", "YUL", "YOW", "08:00", "09:00"), ("8203", "YOW", "YYZ", "09:30", "10:00")],
        "actual_arr": "15:00", "delay_min": 300, "msl_idx": 1, "delay_code": "62",
        "reason_text": "Your flight arrived more than 3 hours late due to a reason within Air Canada's control.",
        "reason": "OPERATIONAL_REQUIREMENTS",
        "tags": ["single-pax", "multi-leg", "invol-then-vol", "many-to-many", "negative-vol-not-deducted",
                 "delay-5h"],
    },
]

# Fresh PNR locators (override the default ZZTC0X ids). Set 2026-06-26 — record-style 6-char,
# not UA#### (which the bot parses as a flight number). To mint another fresh set, swap these.
LOCATORS = ["QMXVRT", "KBWPLF", "ZHNDCA", "TRWGYP", "VFLKBN"]
for _tc, _loc in zip(TCS, LOCATORS):
    _tc["pnr"] = _loc


def build_scenario(tc):
    pnr = tc["pnr"]
    pnr_id = f"{pnr}-{DATE}"
    first, last = tc["name"]
    segs = []
    tickets = []
    for i, (fn, org, dst, dep, arr) in enumerate(tc["segs"], 1):
        segs.append({
            "carrier": "AC", "operating_carrier": "AC",
            "flight_number": fn, "operating_flight_number": fn,
            "origin": org, "destination": dst,
            "dep_local": f"{DATE}T{dep}:00", "arr_local": f"{DATE}T{arr}:00",
            "dep_utc": utc(DATE, dep), "arr_utc": utc(DATE, arr),
            "booking_datetime": None,   # match working set (null) → promised window anchors to 14-day mark
            "aircraft": "320", "cabin": "Y", "status": "HK", "arrival_terminal": "1",
        })
    tickets = [f"014240100{tc['sub'][-1]}00{n}" for n in range(1, 2)]  # one ticket, single pax
    pax = {
        "type": "ADT", "first_name": first, "last_name": last, "gender": tc["gender"],
        "date_of_birth": "1986-04-23",   # match working set (NB: inject doesn't map DOB; set in DB too)
        "email": QA_MAIL, "phone": tc["phone"],
    }
    if tc["aeroplan"]:
        pax["aeroplan"] = tc["aeroplan"]
    return {
        "$schema_version": 2,
        "scenario_id": pnr_id,
        "title": tc["title"],
        "description": tc["desc"],
        "canvas": "_canvas/pnr_creation_domestic_ac.json",
        "contains_pii": False,
        "identity": {"pnr": pnr, "booking_date": DATE, "type": "PNR"},
        "point_of_sale": {
            "office_id": "YULAC010V", "iata_number": "01424012", "system_code": "1A",
            "agent_type": "AIRLINE", "agent_numeric_sign": "0001", "agent_initials": "FD",
            "duty_code": "SU", "agent_country": "CA", "agent_city": "YUL",
        },
        "last_modification_comment": f"SIM-{tc['tc']}-INT",
        "creation_comment": f"SIM-{tc['tc']}-INT",
        "passengers": [pax],
        "segments": segs,
        "ticketing": {
            "issuance_local_date": ISSUE,
            "fare": {"amount": "350.00", "currency": "CAD"},
            "ticket_numbers": tickets,
        },
        "timeline": [
            {"version": 0, "at": f"{ISSUE}T10:00:00Z", "action": "bootstrap",
             "description": "Pre-ticketing stub"},
            {"version": 1, "at": f"{ISSUE}T10:00:01Z", "action": "ticketing_added",
             "description": "Ticketing reference attached"},
        ],
        "expected_cascade": {
            "db_end_state": {
                "trip": {"rows": 1, "status": "ACTIVE", "pnr": pnr, "pnr_id": pnr_id},
                "passenger": {"rows": 1},
                "flight_segment": {"rows": len(segs)},
            },
            "total_cascade_budget_ms": 30000,
        },
        "classification": {"primary_code": tc["tc"].replace("_", "-"),
                           "primary_name": f"Flight Disruption {tc['tc']} INT", "confidence": "high"},
        "tags": ["synthetic", tc["tc"].lower().replace("_", "-"), "appr", "tier1",
                 "controllable", f"code-{tc['delay_code']}", "cad-400"] + tc["tags"],
    }


def dds_segments(tc, legs, kind):
    pnr_id = f"{tc['pnr']}-{DATE}"
    out = []
    for i, (fn, org, dst, dep, arr) in enumerate(legs, 1):
        out.append({
            "segmentId": f"{pnr_id}-ST-{i}", "segmentStatus": "HK",
            "departureDatetime": iso(DATE, dep), "arrivalDatetime": iso(DATE, arr),
            "departureAirport": org, "arrivalAirport": dst,
            "marketingFlightNumber": int(fn), "marketingCarrierCode": "AC",
            "operatingFlightNumber": int(fn), "operatingCarrierCode": "AC",
            "flightId": f"AC#{fn}#{DATE}#{org}",
        })
    return out


def build_dds(tc):
    pnr = tc["pnr"]
    pnr_id = f"{pnr}-{DATE}"
    legs = tc["segs"]
    promised = tc["promised"]
    msl_fn, msl_org, msl_dst = legs[tc["msl_idx"]][0], legs[tc["msl_idx"]][1], legs[tc["msl_idx"]][2]
    overall_org = legs[0][1]
    overall_dst = legs[-1][2]

    def regime_block(regime, eligible):
        if eligible:
            pe = [{
                "passengerId": f"{pnr_id}-PT-1", "passengerType": "ADT",
                "eligibilityStatus": "ELIGIBLE", "systemCode": "FD-APPR-EL-400",
                "reason": "arrival delay 3 to less than 6 hours, within carrier control",
                "compensationDetails": {"amount": 400, "currency": "CAD",
                                        "delayBand": "DELAY_3_TO_LT_6_HOURS", "expiryDate": "2027-06-15"},
            }]
            return {
                "regime": regime, "boundRph": 1,
                "mslFlight": {"segmentId": f"{pnr_id}-ST-{tc['msl_idx']+1}", "carrierCode": "AC",
                              "flightNumber": msl_fn, "departureAirport": msl_org,
                              "arrivalAirport": msl_dst, "isStarSegment": False, "isOalSegment": False},
                "disruptionType": "INVOLUNTARY", "delayMinutes": tc["delay_min"],
                "delayType": "CONTROLLABLE", "delayCode": tc["delay_code"],
                "customerFriendlyDisruptionReason": tc["reason_text"],
                "disruptionReason": tc["reason"],
                "passengerEligibility": pe,
            }
        else:
            return {
                "regime": regime, "boundRph": 1,
                "passengerEligibility": [{
                    "passengerId": f"{pnr_id}-PT-1", "passengerType": "ADT",
                    "eligibilityStatus": "NOT_ELIGIBLE", "systemCode": f"FD-{regime}-NA-01",
                    "compensationDetails": {"amount": 0, "currency": "CAD", "delayBand": "NOT_APPLICABLE"},
                }],
            }

    return {
        "eventMetadata": {"trigger": "DISRUPTION_DETECTION_SERVICE",
                          "timestamp": f"{DATE}T09:05:34.000Z"},
        "pnrIdentifier": {"pnrId": pnr_id, "pnr": pnr},
        "itineraryDetails": [{
            "bound": 1, "boundRph": 1, "isOAL": False,
            "promisedItinerary": {"origin": promised[0][1], "destination": promised[-1][2],
                                  "associatedSegments": dds_segments(tc, promised, "promised")},
            "actualItinerary": {"origin": overall_org, "destination": overall_dst,
                                "associatedSegments": dds_segments(tc, legs, "actual")},
        }],
        "compensationEligibility": [
            regime_block("APPR", True),
            regime_block("EU", False),
            regime_block("ASL", False),
        ],
        # SoC block must be FULLY shaped (matches working RFEUXR) — a stub here makes the
        # bot fail to process the claim ("claims cannot be processed").
        "socFlightEligibility": [{
            "regime": "APPR", "boundRph": 1,
            "segmentId": f"{pnr_id}-ST-{tc['msl_idx']+1}", "carrierCode": "AC",
            "flightNumber": int(msl_fn), "departureAirport": msl_org, "arrivalAirport": msl_dst,
            "segmentStatus": "HK", "disruptionType": "INVOLUNTARY", "delayType": "OTHER",
            "delayCode": "", "disruptionReason": "", "customerFriendlyDisruptionReason": "",
            "delayMinutes": 0, "delayCategory": "DELAY_LT_2_HOURS",
            "passengerEligibility": [{
                "passengerId": f"{pnr_id}-PT-1", "passengerType": "ADT",
                "bookingClass": None, "cabinClass": "ECONOMY",
                "eligibilityStatus": "NO_DETERMINATION", "systemCode": "SoC-APPR-ND-04",
                "reason": "Data missing - 14 days", "expiryDate": "", "expenseCategories": [],
            }],
        }],
        "seatFeeRefundEligibility": [],
    }


def main():
    DDS_DIR.mkdir(parents=True, exist_ok=True)
    print(f"{'PNR':8} {'pnrId':22} {'TC':10} pax / itinerary / code / amount")
    print("-" * 90)
    for tc in TCS:
        pnr_id = f"{tc['pnr']}-{DATE}"
        scen = build_scenario(tc)
        dds = build_dds(tc)
        (FD_SIT / f"{pnr_id}.json").write_text(json.dumps(scen, indent=2) + "\n")
        (DDS_DIR / f"{pnr_id}.dds.json").write_text(json.dumps(dds, indent=2) + "\n")
        route = "-".join([tc["segs"][0][1]] + [s[2] for s in tc["segs"]])
        print(f"{tc['pnr']:8} {pnr_id:22} {tc['tc']:10} "
              f"{tc['name'][0]} {tc['name'][1]} / {route} / code {tc['delay_code']} / CAD 400")
    print("\nWrote 5 booking scenarios -> scenarios/fd-sit/")
    print("Wrote 5 DDS response.json  -> scenarios/fd-sit/_dds-templates/")


if __name__ == "__main__":
    main()
