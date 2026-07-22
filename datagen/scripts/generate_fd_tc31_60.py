#!/usr/bin/env python3
"""
FD_UAT (Tiroshan) test-data for FD_TC_031..060 — INT. Status-aware (EL/NE/ND/PE).

Bookings are kept simple (single AC leg YUL->YYZ for identification); the pinned DDS
response.json carries the verdict (eligibilityStatus + systemCode + amount), which is
what the Ask AC bot reads. EL cases are high-confidence; NE/ND/PE shapes are best-effort
(no live working reference of those statuses to validate against).

Email/auth mailbox (all PNR contacts): sithmina.hettiarachchi@aircanada.ca
"""
import json
from datetime import datetime, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
FD_SIT = HERE.parent / "scenarios" / "fd-sit"
DDS_DIR = FD_SIT / "_dds-templates"
DATE, ISSUE = "2026-06-15", "2026-06-01"
MAIL = "sithmina.hettiarachchi@aircanada.ca"
OFFICE, DOB = "YULAC010V", "1986-04-23"

LOCATORS = ["CHCYCR","CPMMRV","CPPCSP","CVFYJP","DGFHNT","DGZWCG","FQVKGJ","HJJRKY","JFWYWF","JPPPPK",
            "JWCBKK","JYCYCP","KGBQHS","KGTGMW","MTMQQL","NCTXWP","RCMYVX","SCLHCF","SSMTVX","THKSXV",
            "VHZRDJ","VRNDDK","WJNSPK","WWQGYB","XDGSVC","YDMJDB","YJHMXZ","YYQPTL","ZKBTWD","ZPXFZG"]

# n, (first,last), status, syscode, amount, delay(min), code, dtype, flt, label
C = [
    (31,("BERNARD","LEVESQUE"),   "EL","FD-APPR-EL-12",1000,600,"67","CONTROLLABLE","444","Sister City+Fallback 9+h"),
    (32,("HELENE","BOUCHARD"),    "EL","FD-APPR-EL-13", 400,  0,"TECH","CONTROLLABLE","301","No Travel Origin (cancel, controllable)"),
    (33,("SYLVIE","PELLETIER"),   "EL","FD-APPR-EL-15", 400,  0,"TECH","CONTROLLABLE","447","No Travel Return (cancel, controllable)"),
    (34,("EMILE","GAGNON"),       "EL","FD-APPR-EL-17", 400,  0,"EQUI","CONTROLLABLE","451","No Travel Incomplete (cancel, controllable)"),
    (35,("ROBERT","SIMARD"),      "NE","FD-APPR-NE-01",   0,240,"42","CONTROLLABLE","326","Not Eligible — AC Employee"),
    (36,("THOMAS","WEBER"),       "NE","FD-APPR-NE-02",   0,240,"42","CONTROLLABLE","327","Not Eligible — OAL Employee"),
    (37,("MICHEL","TANGUAY"),     "NE","FD-APPR-NE-05",   0,300,"OAL","OTHER","4521","Not Eligible — All-OAL itinerary (UA)"),
    (38,("STEPHANE","BOUCHER"),   "NE","FD-APPR-NE-06",   0,  0,"DENIED_BOARDING","OTHER","330","Not Eligible — Denied Boarding"),
    (39,("YVES","CHAMPAGNE"),     "NE","FD-APPR-NE-07",   0,300,"42","CONTROLLABLE","331","Not Eligible — Outside 366-day limit"),
    (40,("GASTON","RIOUX"),       "NE","FD-APPR-NE-08",   0,  0,"WEAT","UNCONTROLLABLE","301","No Travel Origin — Uncontrollable (weather)"),
    (41,("ARMAND","TESSIER"),     "NE","FD-APPR-NE-10",   0,  0,"AIRS","UNCONTROLLABLE","447","No Travel Return — Uncontrollable (ATC)"),
    (42,("REJEAN","FORTIER"),     "NE","FD-APPR-NE-12",   0,  0,"POLI","UNCONTROLLABLE","451","No Travel Incomplete — Uncontrollable (political)"),
    (43,("EMILE","GAGNON"),       "NE","FD-APPR-NE-14",   0,  0,"PERF","SAFETY","470","No Travel Origin — Safety"),
    (44,("LAURENT","MERCIER"),    "NE","FD-APPR-NE-16",   0,  0,"PERF","SAFETY","473","No Travel Return — Safety"),
    (45,("FRANCINE","OUELLET"),   "NE","FD-APPR-NE-18",   0,  0,"PERF","SAFETY","349","No Travel Incomplete — Safety"),
    (46,("CAROLE","MENARD"),      "NE","FD-APPR-NE-20",   0,150,"42","CONTROLLABLE","480","No Travel Origin — Delay <3h"),
    (47,("NATHALIE","FORTIN"),    "NE","FD-APPR-NE-21",   0,120,"42","CONTROLLABLE","483","No Travel Return — Delay <3h"),
    (48,("SERGE","BLANCHETTE"),   "NE","FD-APPR-NE-22",   0, 90,"TECH","CONTROLLABLE","451","No Travel Incomplete — Delay <3h"),
    (49,("GINETTE","CHARRON"),    "NE","FD-APPR-NE-23",   0,  0,"NONE","OTHER","301","No Travel Origin — No Cancellation (flight operated)"),
    (50,("OLIVIER","DESCHAMPS"),  "NE","FD-APPR-NE-26",   0, 30,"42","CONTROLLABLE","492","Travel Completed — final-dest delay <3h"),
    (51,("LISE","CHARRON"),       "NE","FD-APPR-NE-27",   0,  0,"NONE","OTHER","364","Travel Completed — no delay (early)"),
    (52,("DANIEL","OUIMET"),      "NE","FD-APPR-NE-28",   0,300,"71","UNCONTROLLABLE","365","Delay 5h — Uncontrollable (weather)"),
    (53,("CLAIRE","FONTAINE"),    "NE","FD-APPR-NE-29",   0,360,"81","SAFETY","366","Delay 6h — Safety"),
    (54,("PATRICK","LALONDE"),    "ND","FD-APPR-ND-01",   0,300,"OAL","OTHER","3456","No Determination — disruption on OAL (WestJet)"),
    (55,("FRANCINE","DUBE"),      "ND","FD-APPR-ND-02",   0,240,"OAL","OTHER","471","No Determination — Star Alliance partner (LH)"),
    (56,("REGIS","CHAMPOUX"),     "ND","FD-APPR-ND-03",   0,  0,"42","CONTROLLABLE","447","No Determination — New destination (YVR→YEG)"),
    (57,("DIANE","BRISSON"),      "ND","FD-APPR-ND-04",   0,240,"NULL","UNKNOWN","301","No Determination — No disruption code (14 days)"),
    (58,("SOPHIE","BELANGER"),    "ND","FD-APPR-ND-05",   0,  0,"NULL","UNKNOWN","377","No Determination — Data missing (14 days)"),
    (59,("DENISE","TREMBLAY"),    "ND","FD-APPR-ND-06",   0,  0,"NULL","UNKNOWN","848","No Determination — OAL data not available (BA)"),
    (60,("JEAN-FRANCOIS","MORIN"),"PE","FD-APPR-PE-01",   0,240,"64","CONTROLLABLE","301","Pending — within 72h window"),
]

STATUS = {"EL": "ELIGIBLE", "NE": "NOT_ELIGIBLE", "ND": "NO_DETERMINATION", "PE": "PENDING"}


def band_for(amount, status):
    if status != "EL":
        return "NOT_APPLICABLE"
    return ("DELAY_9_HOURS_OR_MORE" if amount >= 1000 else
            "DELAY_6_TO_LT_9_HOURS" if amount >= 700 else "DELAY_3_TO_LT_6_HOURS")


def hh(h, m=0):
    return (datetime.fromisoformat(f"{DATE}T{h:02d}:00:00") + timedelta(minutes=m))


def build(rec, loc):
    n, (fn, ln), st, sys, amt, delay, code, dtype, flt, label = rec
    pid = f"{loc}-{DATE}"
    status = STATUS[st]
    band = band_for(amt, st)
    dep, arr = hh(10), hh(14)
    seg = {"carrier": "AC", "operating_carrier": "AC", "flight_number": flt, "operating_flight_number": flt,
           "origin": "YUL", "destination": "YYZ",
           "dep_local": dep.strftime("%Y-%m-%dT%H:%M:%S"), "arr_local": arr.strftime("%Y-%m-%dT%H:%M:%S"),
           "dep_utc": (dep + timedelta(hours=4)).strftime("%Y-%m-%dT%H:%M:%SZ"),
           "arr_utc": (arr + timedelta(hours=4)).strftime("%Y-%m-%dT%H:%M:%SZ"),
           "booking_datetime": None, "aircraft": "320", "cabin": "Y", "status": "HK", "arrival_terminal": "1"}
    pax = {"type": "ADT", "first_name": fn, "last_name": ln, "gender": "U", "date_of_birth": DOB,
           "email": MAIL, "phone": f"+1416555{2000+n:04d}"}
    scen = {
        "$schema_version": 2, "scenario_id": pid,
        "title": f"FD_TC_{n:03d}: APPR {label} - {fn} {ln} [{loc}]",
        "description": f"FD_TC_{n:03d} | APPR {status} | {label} | {sys} | CAD {amt}",
        "canvas": "_canvas/pnr_creation_domestic_ac.json", "contains_pii": False,
        "identity": {"pnr": loc, "booking_date": DATE, "type": "PNR"},
        "point_of_sale": {"office_id": OFFICE, "iata_number": "01424012", "system_code": "1A",
                          "agent_type": "AIRLINE", "agent_numeric_sign": "0001", "agent_initials": "FD",
                          "duty_code": "SU", "agent_country": "CA", "agent_city": "YUL"},
        "last_modification_comment": f"SIM-FD-TC-{n:03d}-INT", "creation_comment": f"SIM-FD-TC-{n:03d}-INT",
        "passengers": [pax], "segments": [seg],
        "ticketing": {"issuance_local_date": ISSUE, "fare": {"amount": "350.00", "currency": "CAD"},
                      "ticket_numbers": [f"014246{n:03d}0001"]},
        "timeline": [{"version": 0, "at": f"{ISSUE}T10:00:00Z", "action": "bootstrap", "description": "Pre-ticketing stub"},
                     {"version": 1, "at": f"{ISSUE}T10:00:01Z", "action": "ticketing_added", "description": "Ticketing reference attached"}],
        "expected_cascade": {"db_end_state": {"trip": {"rows": 1, "status": "ACTIVE", "pnr": loc, "pnr_id": pid},
                                              "passenger": {"rows": 1}, "flight_segment": {"rows": 1}},
                             "total_cascade_budget_ms": 30000},
        "classification": {"primary_code": f"FD-TC-{n:03d}", "primary_name": f"Flight Disruption FD_TC_{n:03d} INT", "confidence": "high"},
        "tags": ["synthetic", f"fd-tc-{n:03d}", "appr", st.lower(), f"code-{code.lower()}"],
    }

    def dseg(i, org, dst, fl):
        d, a = hh(10 + 2 * (i - 1)), hh(12 + 2 * (i - 1))
        return {"segmentId": f"{pid}-ST-{i}", "segmentStatus": "HK",
                "departureDatetime": d.strftime("%Y-%m-%dT%H:%M:00+00:00"),
                "arrivalDatetime": a.strftime("%Y-%m-%dT%H:%M:00+00:00"),
                "departureAirport": org, "arrivalAirport": dst,
                "marketingFlightNumber": int(fl) if fl.isdigit() else 0, "marketingCarrierCode": "AC",
                "operatingFlightNumber": int(fl) if fl.isdigit() else 0, "operatingCarrierCode": "AC",
                "flightId": f"AC#{fl}#{DATE}#{org}"}

    segs = [dseg(1, "YUL", "YYZ", flt)]
    pe = [{"passengerId": f"{pid}-PT-1", "passengerType": "ADT", "eligibilityStatus": status,
           "systemCode": sys,
           "compensationDetails": {"amount": amt, "currency": "CAD", "delayBand": band,
                                   **({"expiryDate": "2027-06-15"} if st == "EL" else {})}}]
    if st in ("EL", "NE", "PE"):
        pe[0]["reason"] = "arrival delay within carrier control" if st == "EL" else f"{label}"
    appr = {"regime": "APPR", "boundRph": 1,
            "mslFlight": {"segmentId": f"{pid}-ST-1", "carrierCode": "AC", "flightNumber": flt,
                          "departureAirport": "YUL", "arrivalAirport": "YYZ", "isStarSegment": False, "isOalSegment": False},
            "disruptionType": "INVOLUNTARY", "delayMinutes": delay, "delayType": dtype, "delayCode": code,
            "customerFriendlyDisruptionReason": "Your flight was disrupted.", "disruptionReason": "MECHANICAL",
            "passengerEligibility": pe}

    def na(reg):
        return {"regime": reg, "boundRph": 1,
                "passengerEligibility": [{"passengerId": f"{pid}-PT-1", "passengerType": "ADT",
                                          "eligibilityStatus": "NOT_ELIGIBLE", "systemCode": f"FD-{reg}-NA-01",
                                          "compensationDetails": {"amount": 0, "currency": "CAD", "delayBand": "NOT_APPLICABLE"}}]}

    dds = {
        "eventMetadata": {"trigger": "DISRUPTION_DETECTION_SERVICE", "timestamp": f"{DATE}T09:05:34.000Z"},
        "pnrIdentifier": {"pnrId": pid, "pnr": loc},
        "itineraryDetails": [{"bound": 1, "boundRph": 1, "isOAL": False,
                              "promisedItinerary": {"origin": "YUL", "destination": "YYZ", "associatedSegments": segs},
                              "actualItinerary": {"origin": "YUL", "destination": "YYZ", "associatedSegments": segs}}],
        "compensationEligibility": [appr, na("EU"), na("ASL")],
        "socFlightEligibility": [{"regime": "APPR", "boundRph": 1, "segmentId": f"{pid}-ST-1", "carrierCode": "AC",
                                  "flightNumber": int(flt) if flt.isdigit() else 0, "departureAirport": "YUL",
                                  "arrivalAirport": "YYZ", "segmentStatus": "HK", "disruptionType": "INVOLUNTARY",
                                  "delayType": "OTHER", "delayCode": "", "disruptionReason": "",
                                  "customerFriendlyDisruptionReason": "", "delayMinutes": 0, "delayCategory": "DELAY_LT_2_HOURS",
                                  "passengerEligibility": [{"passengerId": f"{pid}-PT-1", "passengerType": "ADT",
                                                            "bookingClass": None, "cabinClass": "ECONOMY",
                                                            "eligibilityStatus": "NO_DETERMINATION", "systemCode": "SoC-APPR-ND-04",
                                                            "reason": "Data missing - 14 days", "expiryDate": "", "expenseCategories": []}]}],
        "seatFeeRefundEligibility": [],
    }
    meta = dict(loc=loc, pnr_id=pid, tc=f"FD_TC_{n:03d}", pax=f"{fn} {ln}", status=status, syscode=sys,
                amount=amt, delay=delay, code=code, dtype=dtype, label=label, ticket=f"014246{n:03d}0001")
    return scen, dds, meta


def main():
    DDS_DIR.mkdir(parents=True, exist_ok=True)
    rows = []
    for rec, loc in zip(C, LOCATORS):
        scen, dds, meta = build(rec, loc)
        (FD_SIT / f"{meta['pnr_id']}.json").write_text(json.dumps(scen, indent=2) + "\n")
        (DDS_DIR / f"{meta['pnr_id']}.dds.json").write_text(json.dumps(dds, indent=2) + "\n")
        rows.append(meta)
        print(f"  {meta['tc']} {meta['loc']} {meta['status']:16} {meta['syscode']:15} CAD {meta['amount']:<4} {meta['pax']}")
    (FD_SIT / "_FD_TC31_60_index.json").write_text(json.dumps(rows, indent=2) + "\n")
    print(f"\nWrote {len(rows)} scenarios + DDS; index -> _FD_TC31_60_index.json")


if __name__ == "__main__":
    main()
