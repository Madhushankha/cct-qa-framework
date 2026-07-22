#!/usr/bin/env python3
"""
FD_UAT (Tiroshan) test-data for FD_TC_091..120 — INT.

EU 261 (No-Travel ELIGIBLE 091-094, NOT_ELIGIBLE 095-112, NO_DETERMINATION 113-115, PENDING 116)
and ASL/Israel ELIGIBLE 117-120 (flat ILS 3670). For ELIGIBLE cases the *selected* regime
(EU or ASL) is compensationEligibility[0]; APPR ($400 CAD) is a secondary eligible regime.
For NE/ND/PE the selected regime is compensationEligibility[0] with status + systemCode; the
other regimes are NOT_APPLICABLE. Bookings are simplified single AC legs on the case route
(origin drives the regime); the pinned DDS carries the verdict.

Email/auth mailbox (all PNR contacts): marizza.ranasinghe@aircanada.ca
"""
import json
from datetime import datetime, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
FD_SIT = HERE.parent / "scenarios" / "fd-sit"
DDS_DIR = FD_SIT / "_dds-templates"
DATE, ISSUE = "2026-06-15", "2026-06-01"
MAIL, OFFICE, DOB = "marizza.ranasinghe@aircanada.ca", "YULAC010V", "1986-04-23"

LOCS = ["BDMNWX","CVBXMF","DJFRDY","DKSGXT","FVPZWJ","HGDDNL","HMVBRW","JJRYDX","JPVGYS","LFHGPS",
        "LGRCCT","NPGTCD","NYHJBZ","QQMBWF","QYDLBJ","RQMBDS","SDCPNS","SNWHCT","THKWTH","TPGNRV",
        "VBGPHY","VGJXSF","VGLYJT","VYLFSN","WCYDNX","WPRYWX","WTQHFY","XZMLJW","ZHLKCG","ZPXHVX"]

# n, (first,last), kind, status, primary, origin, dest, prom_dest, flt, delay, code, dtype, cur, amt, sys, label
C = [
 (91,("CHRISTOPHE","RENAUD"),"EU_EL","ELIGIBLE","EU","CDG","YVR","YVR","121",0,"CREW","CONTROLLABLE","EUR",600,"FD-EU-EL-31","EU Mainland No Travel Return"),
 (92,("OLIVER","BENNETT"),"EU_EL","ELIGIBLE","EU","LHR","YVR","YVR","121",0,"CREW","CONTROLLABLE","GBP",520,"FD-EU-EL-33","EU-UK No Travel Incomplete"),
 (93,("MAXIME","THEODORE"),"EU_EL","ELIGIBLE","EU","PTP","YYZ","YYZ","422",0,"CREW","CONTROLLABLE","EUR",400,"FD-EU-EL-35","EU Guadeloupe No Travel Incomplete"),
 (94,("ETIENNE","MARCHAND"),"EU_EL","ELIGIBLE","EU","CDG","YVR","YVR","121",0,"CREW","CONTROLLABLE","EUR",600,"FD-EU-EL-37","EU Mainland No Travel Incomplete"),
 (95,("JOHN","SMITH"),"EU_NE","NOT_ELIGIBLE","EU","LHR","YYZ","YYZ","858",240,"42","CONTROLLABLE","GBP",0,"FD-EU-NE-01","Not Eligible — Employee AC"),
 (96,("KLAUS","FISCHER"),"EU_NE","NOT_ELIGIBLE","EU","LHR","YYZ","YYZ","850",240,"42","CONTROLLABLE","GBP",0,"FD-EU-NE-02","Not Eligible — Employee OAL"),
 (97,("KLAUS","WEBER"),"EU_NE","NOT_ELIGIBLE","EU","YYZ","LHR","LHR","860",240,"42","CONTROLLABLE","GBP",0,"FD-EU-NE-05","Not Eligible — non-EU carrier arrival"),
 (98,("SOPHIE","LAURENT"),"EU_NE","NOT_ELIGIBLE","EU","LHR","YYZ","YYZ","858",240,"VOL_DB","OTHER","EUR",0,"FD-EU-NE-06","Not Eligible — Voluntary Denied Boarding"),
 (99,("ALICE","WHITFIELD"),"EU_NE","NOT_ELIGIBLE","EU","LHR","YYZ","YYZ","849",0,"WEAT","UNCONTROLLABLE","GBP",0,"FD-EU-NE-07","No Travel Origin — Extraordinary (weather)"),
 (100,("FREDERIC","GAUTHIER"),"EU_NE","NOT_ELIGIBLE","EU","CDG","YYZ","YYZ","871",0,"WEAT","UNCONTROLLABLE","EUR",0,"FD-EU-NE-09","No Travel Return — Extraordinary"),
 (101,("RAPHAEL","DUFRESNE"),"EU_NE","NOT_ELIGIBLE","EU","CDG","YVR","YVR","121",0,"WEAT","UNCONTROLLABLE","EUR",0,"FD-EU-NE-11","No Travel Incomplete — Extraordinary"),
 (102,("ARNAUD","PICARD"),"EU_NE","NOT_ELIGIBLE","EU","CDG","YYZ","YYZ","871",120,"CREW","CONTROLLABLE","EUR",0,"FD-EU-NE-13","No Travel Origin — Delay <3h"),
 (103,("MIREILLE","CARON"),"EU_NE","NOT_ELIGIBLE","EU","CDG","YVR","YVR","121",120,"CREW","CONTROLLABLE","EUR",0,"FD-EU-NE-14","No Travel Return — Delay <3h"),
 (104,("DAMIEN","LEROY"),"EU_NE","NOT_ELIGIBLE","EU","CDG","YVR","YVR","121",120,"CREW","CONTROLLABLE","EUR",0,"FD-EU-NE-15","No Travel Incomplete — Delay <3h"),
 (105,("SYLVAIN","MERCIER"),"EU_NE","NOT_ELIGIBLE","EU","CDG","YYZ","YYZ","871",0,"NONE","OTHER","EUR",0,"FD-EU-NE-16","No Travel Origin — No Cancellation"),
 (106,("HELENE","BOUVIER"),"EU_NE","NOT_ELIGIBLE","EU","CDG","YVR","YVR","121",0,"NONE","OTHER","EUR",0,"FD-EU-NE-17","No Travel Return — No Cancellation"),
 (107,("CLEMENT","ROUSSEAU"),"EU_NE","NOT_ELIGIBLE","EU","CDG","YVR","YVR","121",0,"NONE","OTHER","EUR",0,"FD-EU-NE-18","No Travel Incomplete — No Cancellation"),
 (108,("ROBERT","TREMBLAY"),"EU_NE","NOT_ELIGIBLE","EU","YYZ","CDG","CDG","870",240,"42","CONTROLLABLE","EUR",0,"FD-EU-NE-19","Not EU Origin (YYZ->CDG)"),
 (109,("CATHERINE","WALSH"),"EU_NE","NOT_ELIGIBLE","EU","YYZ","LHR","LHR","848",240,"42","CONTROLLABLE","GBP",0,"FD-EU-NE-20","Not UK Origin (YYZ->LHR)"),
 (110,("ADRIEN","COLBERT"),"EU_NE","NOT_ELIGIBLE","EU","CDG","YVR","YVR","121",120,"42","CONTROLLABLE","EUR",0,"FD-EU-NE-21","Arrival <3h despite MSL >3h"),
 (111,("JOSEPHINE","LAMBERT"),"EU_NE","NOT_ELIGIBLE","EU","CDG","YVR","YVR","121",90,"42","CONTROLLABLE","EUR",0,"FD-EU-NE-22","Both MSL & arrival <3h"),
 (112,("JULIEN","MARCHAND"),"EU_NE","NOT_ELIGIBLE","EU","CDG","YYZ","YYZ","871",240,"72","UNCONTROLLABLE","EUR",0,"FD-EU-NE-23","Extraordinary (weather) delay"),
 (113,("ANNETTE","BEAUMONT"),"EU_ND","NO_DETERMINATION","EU","LHR","YEG","YVR","121",0,"42","CONTROLLABLE","GBP",0,"FD-EU-ND-03","No Determination — New Destination (YVR->YEG)"),
 (114,("FRANCOIS","GIRARD"),"EU_ND","NO_DETERMINATION","EU","CDG","YYZ","YYZ","879",0,"NULL","UNKNOWN","EUR",0,"FD-EU-ND-05","No Determination — MSL Data Missing (14d)"),
 (115,("REGINALD","THORNTON"),"EU_ND","NO_DETERMINATION","EU","LHR","MUC","MUC","471",240,"NULL","UNKNOWN","EUR",0,"FD-EU-ND-06","No Determination — OAL Data Not Available (14d)"),
 (116,("BENEDICT","HARRINGTON"),"EU_PE","PENDING","EU","LHR","YYZ","YYZ","858",240,"42","CONTROLLABLE","GBP",0,"FD-EU-PE-01","Pending — within 72h window"),
 (117,("DAVID","COHEN"),"ASL_EL","ELIGIBLE","ASL","YYZ","TLV","TLV","082",540,"42","CONTROLLABLE","ILS",3670,"FD-ASL-EL-01","ASL 9h delay ILS3670"),
 (118,("YAEL","LEVI"),"ASL_EL","ELIGIBLE","ASL","YYZ","TLV","TLV","082",0,"CREW","CONTROLLABLE","ILS",3670,"FD-ASL-EL-05","ASL No Travel Origin"),
 (119,("NOA","SHAPIRO"),"ASL_EL","ELIGIBLE","ASL","YYZ","TLV","TLV","084",0,"CREW","CONTROLLABLE","ILS",3670,"FD-ASL-EL-07","ASL No Travel Return"),
 (120,("AVI","GOLDSTEIN"),"ASL_EL","ELIGIBLE","ASL","YYZ","TLV","TLV","084",0,"CREW","CONTROLLABLE","ILS",3670,"FD-ASL-EL-09","ASL No Travel Incomplete"),
]


def band_for(kind, delay):
    if not kind.endswith("_EL"):
        return "NOT_APPLICABLE"
    if kind.startswith("ASL"):
        return "DELAY_8_HOURS_OR_MORE" if delay else "NOT_APPLICABLE"
    if delay == 0:
        return "NOT_APPLICABLE"
    return "DELAY_GTE_4_HOURS" if delay >= 240 else "DELAY_3_TO_LT_4_HOURS"


def hh(h, m=0):
    return datetime.fromisoformat(f"{DATE}T{h:02d}:00:00") + timedelta(minutes=m)


def build(rec):
    n, (fn, ln), kind, status, primary, org, dst, prom, flt, delay, code, dtype, cur, amt, sys, label = rec
    loc = LOCS[n - 91]
    pid = f"{loc}-{DATE}"
    fnum = int(flt)
    dep, arr = hh(10), hh(14)
    seg = {"carrier": "AC", "operating_carrier": "AC", "flight_number": flt, "operating_flight_number": flt,
           "origin": org, "destination": dst,
           "dep_local": dep.strftime("%Y-%m-%dT%H:%M:%S"), "arr_local": arr.strftime("%Y-%m-%dT%H:%M:%S"),
           "dep_utc": (dep + timedelta(hours=4)).strftime("%Y-%m-%dT%H:%M:%SZ"),
           "arr_utc": (arr + timedelta(hours=4)).strftime("%Y-%m-%dT%H:%M:%SZ"),
           "booking_datetime": None, "aircraft": "320", "cabin": "Y", "status": "HK", "arrival_terminal": "1"}
    pax = {"type": "ADT", "first_name": fn, "last_name": ln, "gender": "U", "date_of_birth": DOB,
           "email": MAIL, "phone": f"+1416555{4000+n:04d}"}
    scen = {
        "$schema_version": 2, "scenario_id": pid,
        "title": f"FD_TC_{n:03d}: {label} - {fn} {ln} [{loc}]",
        "description": f"FD_TC_{n:03d} | {primary} {status} | {label} | {sys}",
        "canvas": "_canvas/pnr_creation_domestic_ac.json", "contains_pii": False,
        "identity": {"pnr": loc, "booking_date": DATE, "type": "PNR"},
        "point_of_sale": {"office_id": OFFICE, "iata_number": "01424012", "system_code": "1A",
                          "agent_type": "AIRLINE", "agent_numeric_sign": "0001", "agent_initials": "FD",
                          "duty_code": "SU", "agent_country": "CA", "agent_city": "YUL"},
        "last_modification_comment": f"SIM-FD-TC-{n:03d}-INT", "creation_comment": f"SIM-FD-TC-{n:03d}-INT",
        "passengers": [pax], "segments": [seg],
        "ticketing": {"issuance_local_date": ISSUE, "fare": {"amount": "350.00", "currency": "CAD"},
                      "ticket_numbers": [f"014248{n:03d}0001"]},
        "timeline": [{"version": 0, "at": f"{ISSUE}T10:00:00Z", "action": "bootstrap", "description": "Pre-ticketing stub"},
                     {"version": 1, "at": f"{ISSUE}T10:00:01Z", "action": "ticketing_added", "description": "Ticketing reference attached"}],
        "expected_cascade": {"db_end_state": {"trip": {"rows": 1, "status": "ACTIVE", "pnr": loc, "pnr_id": pid},
                                              "passenger": {"rows": 1}, "flight_segment": {"rows": 1}},
                             "total_cascade_budget_ms": 30000},
        "classification": {"primary_code": f"FD-TC-{n:03d}", "primary_name": f"Flight Disruption FD_TC_{n:03d} INT", "confidence": "high"},
        "tags": ["synthetic", f"fd-tc-{n:03d}", primary.lower(), status.lower()],
    }

    def dseg(o, d):
        return {"segmentId": f"{pid}-ST-1", "segmentStatus": "HK",
                "departureDatetime": dep.strftime("%Y-%m-%dT%H:%M:00+00:00"), "arrivalDatetime": arr.strftime("%Y-%m-%dT%H:%M:00+00:00"),
                "departureAirport": o, "arrivalAirport": d, "marketingFlightNumber": fnum, "marketingCarrierCode": "AC",
                "operatingFlightNumber": fnum, "operatingCarrierCode": "AC", "flightId": f"AC#{flt}#{DATE}#{o}"}

    def block(regime, st, sc, a, c, band):
        cd = {"amount": a, "currency": c, "delayBand": band}
        if st == "ELIGIBLE":
            cd["expiryDate"] = "2027-06-15"
        return {"regime": regime, "boundRph": 1,
                "mslFlight": {"segmentId": f"{pid}-ST-1", "carrierCode": "AC", "flightNumber": flt, "departureAirport": org,
                              "arrivalAirport": dst, "isStarSegment": False, "isOalSegment": False},
                "disruptionType": "INVOLUNTARY", "delayMinutes": delay, "delayType": dtype, "delayCode": code,
                "customerFriendlyDisruptionReason": "Your flight was disrupted.", "disruptionReason": "MECHANICAL",
                "passengerEligibility": [{"passengerId": f"{pid}-PT-1", "passengerType": "ADT", "eligibilityStatus": st,
                                          "systemCode": sc, "reason": label, "compensationDetails": cd}]}

    def na(regime):
        return {"regime": regime, "boundRph": 1,
                "passengerEligibility": [{"passengerId": f"{pid}-PT-1", "passengerType": "ADT",
                                          "eligibilityStatus": "NOT_ELIGIBLE", "systemCode": f"FD-{regime}-NA-01",
                                          "compensationDetails": {"amount": 0, "currency": "CAD", "delayBand": "NOT_APPLICABLE"}}]}

    primary_block = block(primary, status, sys, amt, cur, band_for(kind, delay))
    appr_block = block("APPR", "ELIGIBLE", "FD-APPR-EL-400", 400, "CAD", "DELAY_3_TO_LT_6_HOURS") if kind.endswith("_EL") else na("APPR")
    third = "ASL" if primary == "EU" else "EU"
    comp = [primary_block, appr_block, na(third)]

    dds = {
        "eventMetadata": {"trigger": "DISRUPTION_DETECTION_SERVICE", "timestamp": f"{DATE}T09:05:34.000Z"},
        "pnrIdentifier": {"pnrId": pid, "pnr": loc},
        "itineraryDetails": [{"bound": 1, "boundRph": 1, "isOAL": False,
                              "promisedItinerary": {"origin": org, "destination": prom, "associatedSegments": [dseg(org, prom)]},
                              "actualItinerary": {"origin": org, "destination": dst, "associatedSegments": [dseg(org, dst)]}}],
        "compensationEligibility": comp,
        "socFlightEligibility": [{"regime": primary, "boundRph": 1, "segmentId": f"{pid}-ST-1", "carrierCode": "AC",
                                  "flightNumber": fnum, "departureAirport": org, "arrivalAirport": dst, "segmentStatus": "HK",
                                  "disruptionType": "INVOLUNTARY", "delayType": "OTHER", "delayCode": "", "disruptionReason": "",
                                  "customerFriendlyDisruptionReason": "", "delayMinutes": 0, "delayCategory": "DELAY_LT_2_HOURS",
                                  "passengerEligibility": [{"passengerId": f"{pid}-PT-1", "passengerType": "ADT",
                                                            "bookingClass": None, "cabinClass": "ECONOMY",
                                                            "eligibilityStatus": "NO_DETERMINATION", "systemCode": "SoC-APPR-ND-04",
                                                            "reason": "Data missing - 14 days", "expiryDate": "", "expenseCategories": []}]}],
        "seatFeeRefundEligibility": [],
    }
    meta = dict(loc=loc, pnr_id=pid, tc=f"FD_TC_{n:03d}", pax=f"{fn} {ln}", status=status, regime=primary, syscode=sys,
                amount=amt, currency=cur, route=f"{org}-{dst}", label=label, ticket=f"014248{n:03d}0001", pin=True)
    return scen, dds, meta


def main():
    DDS_DIR.mkdir(parents=True, exist_ok=True)
    rows = []
    for rec in C:
        scen, dds, meta = build(rec)
        (FD_SIT / f"{meta['pnr_id']}.json").write_text(json.dumps(scen, indent=2) + "\n")
        (DDS_DIR / f"{meta['pnr_id']}.dds.json").write_text(json.dumps(dds, indent=2) + "\n")
        rows.append(meta)
        amt = f"{meta['currency']} {meta['amount']}" if meta["amount"] else "—"
        print(f"  {meta['tc']} {meta['loc']} {meta['regime']:4} {meta['status']:16} {meta['syscode']:14} {amt:>9} {meta['route']:8} {meta['pax']}")
    (FD_SIT / "_FD_TC91_120_index.json").write_text(json.dumps(rows, indent=2) + "\n")
    print(f"\nWrote {len(rows)} scenarios + DDS; index -> _FD_TC91_120_index.json")


if __name__ == "__main__":
    main()
