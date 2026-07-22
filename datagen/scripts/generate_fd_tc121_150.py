#!/usr/bin/env python3
"""
FD_UAT (Tiroshan) test-data for FD_TC_121..150 — INT.

ASL/Israel NOT_ELIGIBLE (121-138), ASL NO_DETERMINATION (139-144), ASL PENDING (145),
and MIXED-regime dual-eligibility (146-150, EU/APPR/ASL "most-generous" with FD-MIXED codes).
For ELIGIBLE/MIXED cases the *selected* regime is compensationEligibility[0]; the pinned DDS
carries the verdict. Bookings are simplified single AC legs on the case route.

Email/auth mailbox (all PNR contacts): chamalka.prabodh@ext.aircanada.ca
"""
import json
from datetime import datetime, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
FD_SIT = HERE.parent / "scenarios" / "fd-sit"
DDS_DIR = FD_SIT / "_dds-templates"
DATE, ISSUE = "2026-06-15", "2026-06-01"
MAIL, OFFICE, DOB = "chamalka.prabodh@ext.aircanada.ca", "YULAC010V", "1986-04-23"

LOCS = ["BJMKZQ","BTHSHM","DGMKBP","DHLSYY","DTYVSF","DZMDCJ","FFTHYZ","GNCRYD","GNNRKD","HLVMYF",
        "HWJPQT","JVPKGN","KXBSBF","LNVKHG","MKCSGV","NKHPSC","PRSNTT","PZDKQF","QQJNHN","SHVJWX",
        "SKXVBL","VHZKPX","VJQVSS","VJYSXW","VTRCHZ","WJHFJR","XNLYMM","XTKKLD","YKZVCK","ZBTFWB"]

# n, (first,last), kind, status, primary, origin, dest, prom, flt, delay, code, dtype, cur, amt, sys, label
# kind: ASL_NE | ASL_ND | ASL_PE | MIXED_EU | MIXED_APPR | MIXED_EUNE
C = [
 (121,("DANIEL","MIZRAHI"),"ASL_NE","NOT_ELIGIBLE","ASL","YYZ","TLV","TLV","085",240,"42","CONTROLLABLE","ILS",0,"FD-ASL-NE-01","Not Eligible — Employee AC"),
 (122,("RUTH","KAPLAN"),"ASL_NE","NOT_ELIGIBLE","ASL","YYZ","TLV","TLV","085",240,"42","CONTROLLABLE","ILS",0,"FD-ASL-NE-02","Not Eligible — Employee OAL"),
 (123,("DAVID","LEVY"),"ASL_NE","NOT_ELIGIBLE","ASL","TLV","YYZ","YYZ","9050",240,"OAL","OTHER","ILS",0,"FD-ASL-NE-05","Not Eligible — All-OAL itinerary"),
 (124,("SARAH","BARUCH"),"ASL_NE","NOT_ELIGIBLE","ASL","YYZ","TLV","TLV","085",0,"DENIED_BOARDING","OTHER","ILS",0,"FD-ASL-NE-06","Not Eligible — Denied Boarding"),
 (125,("AMIR","SEGAL"),"ASL_NE","NOT_ELIGIBLE","ASL","TLV","YYZ","YYZ","084",0,"WEAT","UNCONTROLLABLE","ILS",0,"FD-ASL-NE-08","No Travel Origin — Extraordinary"),
 (126,("ELI","NAVON"),"ASL_NE","NOT_ELIGIBLE","ASL","FRA","TLV","TLV","9042",0,"WEAT","UNCONTROLLABLE","ILS",0,"FD-ASL-NE-10","No Travel Return — Extraordinary"),
 (127,("TALIA","FRIEDMAN"),"ASL_NE","NOT_ELIGIBLE","ASL","FRA","TLV","TLV","9042",0,"WEAT","UNCONTROLLABLE","ILS",0,"FD-ASL-NE-12","No Travel Incomplete — Extraordinary"),
 (128,("HADAS","MOR"),"ASL_NE","NOT_ELIGIBLE","ASL","YYZ","TLV","TLV","085",120,"CREW","CONTROLLABLE","ILS",0,"FD-ASL-NE-14","No Travel Origin — Delay <3h"),
 (129,("ITAI","BERGMAN"),"ASL_NE","NOT_ELIGIBLE","ASL","FRA","TLV","TLV","9042",120,"CREW","CONTROLLABLE","ILS",0,"FD-ASL-NE-15","No Travel Return — Delay <3h"),
 (130,("NIRIT","GOLAN"),"ASL_NE","NOT_ELIGIBLE","ASL","FRA","TLV","TLV","9042",120,"CREW","CONTROLLABLE","ILS",0,"FD-ASL-NE-16","No Travel Incomplete — Delay <3h"),
 (131,("YOAV","SHAMIR"),"ASL_NE","NOT_ELIGIBLE","ASL","YYZ","TLV","TLV","085",0,"NONE","OTHER","ILS",0,"FD-ASL-NE-17","No Travel Origin — No Cancellation"),
 (132,("KEREN","ZILBER"),"ASL_NE","NOT_ELIGIBLE","ASL","FRA","TLV","TLV","9042",0,"NONE","OTHER","ILS",0,"FD-ASL-NE-18","No Travel Return — No Cancellation"),
 (133,("RAZ","ELIYAHU"),"ASL_NE","NOT_ELIGIBLE","ASL","FRA","TLV","TLV","9042",0,"NONE","OTHER","ILS",0,"FD-ASL-NE-19","No Travel Incomplete — No Cancellation"),
 (134,("ADAM","ROSEN"),"ASL_NE","NOT_ELIGIBLE","ASL","YYZ","TLV","TLV","085",240,"42","CONTROLLABLE","ILS",0,"FD-ASL-NE-20","Not Israel origin + <8h"),
 (135,("MAYA","STEIN"),"ASL_NE","NOT_ELIGIBLE","ASL","TLV","YYZ","YYZ","084",240,"42","CONTROLLABLE","ILS",0,"FD-ASL-NE-21","Not Israel dest + <8h"),
 (136,("LIOR","HADAD"),"ASL_NE","NOT_ELIGIBLE","ASL","FRA","TLV","TLV","9042",120,"42","CONTROLLABLE","ILS",0,"FD-ASL-NE-22","Arrival <8h despite MSL >3h"),
 (137,("SHAI","BENVENISTI"),"ASL_NE","NOT_ELIGIBLE","ASL","FRA","TLV","TLV","9042",90,"42","CONTROLLABLE","ILS",0,"FD-ASL-NE-23","Both MSL & arrival <8h"),
 (138,("BENJAMIN","WEISS"),"ASL_NE","NOT_ELIGIBLE","ASL","YYZ","TLV","TLV","084",240,"72","UNCONTROLLABLE","ILS",0,"FD-ASL-NE-24","Extraordinary (weather) delay"),
 (139,("YOSSI","BARAK"),"ASL_ND","NO_DETERMINATION","ASL","TLV","YVR","YVR","9060",240,"OAL","OTHER","ILS",0,"FD-ASL-ND-01","No Determination — disruption on OAL"),
 (140,("DANA","PERETZ"),"ASL_ND","NO_DETERMINATION","ASL","TLV","MUC","MUC","9061",240,"OAL","OTHER","ILS",0,"FD-ASL-ND-02","No Determination — Star Alliance partner"),
 (141,("OMER","KATZ"),"ASL_ND","NO_DETERMINATION","ASL","TLV","YOW","YOW","086",0,"42","CONTROLLABLE","ILS",0,"FD-ASL-ND-03","No Determination — New destination"),
 (142,("TAMAR","WEISS"),"ASL_ND","NO_DETERMINATION","ASL","YYZ","TLV","TLV","085",240,"NULL","UNKNOWN","ILS",0,"FD-ASL-ND-04","No Determination — No code (14d)"),
 (143,("OREN","NAVON"),"ASL_ND","NO_DETERMINATION","ASL","YYZ","TLV","TLV","084",0,"NULL","UNKNOWN","ILS",0,"FD-ASL-ND-05","No Determination — MSL data missing (14d)"),
 (144,("SHIRA","ABRAMOV"),"ASL_ND","NO_DETERMINATION","ASL","FRA","TLV","TLV","694",240,"NULL","UNKNOWN","ILS",0,"FD-ASL-ND-06","No Determination — OAL data not available (14d)"),
 (145,("YONIT","ADLER"),"ASL_PE","PENDING","ASL","YYZ","TLV","TLV","085",240,"42","CONTROLLABLE","ILS",0,"FD-ASL-PE-01","Pending — within 72h window"),
 (146,("MARIE","LEFEVRE"),"MIXED_EU","ELIGIBLE","EU","CDG","YYZ","YYZ","870",240,"42","CONTROLLABLE","EUR",600,"FD-MIXED-EL-01","Mixed APPR+EU (EU most generous EUR600)"),
 (147,("JEAN-MARC","ROUSSEAU"),"MIXED_EU","ELIGIBLE","EU","CDG","YYZ","YYZ","871",600,"42","CONTROLLABLE","EUR",600,"FD-MIXED-EL-02","Mixed APPR+EU (EU first, no flip EUR600)"),
 (148,("CLAUDETTE","BEAUREGARD"),"MIXED_EU","ELIGIBLE","EU","CDG","YYZ","YYZ","870",240,"42","CONTROLLABLE","EUR",600,"FD-MIXED-EL-03","Mixed APPR+EU AC Wallet (EU EUR600)"),
 (149,("NOAM","GOLAN"),"MIXED_APPR","ELIGIBLE","APPR","YYZ","TLV","TLV","082",240,"42","CONTROLLABLE","CAD",400,"FD-MIXED-EL-04","Mixed APPR+ASL (APPR $400; ASL <8h NE)"),
 (150,("BRIDGET","CARMICHAEL"),"MIXED_EUNE","ELIGIBLE","EU","LHR","YYZ","YYZ","858",240,"42","CONTROLLABLE","GBP",520,"FD-MIXED-NE-01","Mixed EU EL (GBP520) but APPR NE"),
]


def hh(h, m=0):
    return datetime.fromisoformat(f"{DATE}T{h:02d}:00:00") + timedelta(minutes=m)


def build(rec):
    n, (fn, ln), kind, status, primary, org, dst, prom, flt, delay, code, dtype, cur, amt, sys, label = rec
    loc = LOCS[n - 121]
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
           "email": MAIL, "phone": f"+1416555{5000+n:04d}"}
    scen = {
        "$schema_version": 2, "scenario_id": pid,
        "title": f"FD_TC_{n:03d}: {label} - {fn} {ln} [{loc}]",
        "description": f"FD_TC_{n:03d} | {status} | {label} | {sys}",
        "canvas": "_canvas/pnr_creation_domestic_ac.json", "contains_pii": False,
        "identity": {"pnr": loc, "booking_date": DATE, "type": "PNR"},
        "point_of_sale": {"office_id": OFFICE, "iata_number": "01424012", "system_code": "1A",
                          "agent_type": "AIRLINE", "agent_numeric_sign": "0001", "agent_initials": "FD",
                          "duty_code": "SU", "agent_country": "CA", "agent_city": "YUL"},
        "last_modification_comment": f"SIM-FD-TC-{n:03d}-INT", "creation_comment": f"SIM-FD-TC-{n:03d}-INT",
        "passengers": [pax], "segments": [seg],
        "ticketing": {"issuance_local_date": ISSUE, "fare": {"amount": "350.00", "currency": "CAD"},
                      "ticket_numbers": [f"014249{n:03d}0001"]},
        "timeline": [{"version": 0, "at": f"{ISSUE}T10:00:00Z", "action": "bootstrap", "description": "Pre-ticketing stub"},
                     {"version": 1, "at": f"{ISSUE}T10:00:01Z", "action": "ticketing_added", "description": "Ticketing reference attached"}],
        "expected_cascade": {"db_end_state": {"trip": {"rows": 1, "status": "ACTIVE", "pnr": loc, "pnr_id": pid},
                                              "passenger": {"rows": 1}, "flight_segment": {"rows": 1}},
                             "total_cascade_budget_ms": 30000},
        "classification": {"primary_code": f"FD-TC-{n:03d}", "primary_name": f"Flight Disruption FD_TC_{n:03d} INT", "confidence": "high"},
        "tags": ["synthetic", f"fd-tc-{n:03d}", primary.lower(), status.lower(), "mixed" if kind.startswith("MIXED") else "asl"],
    }

    def dseg():
        return {"segmentId": f"{pid}-ST-1", "segmentStatus": "HK",
                "departureDatetime": dep.strftime("%Y-%m-%dT%H:%M:00+00:00"), "arrivalDatetime": arr.strftime("%Y-%m-%dT%H:%M:00+00:00"),
                "departureAirport": org, "arrivalAirport": dst, "marketingFlightNumber": fnum, "marketingCarrierCode": "AC",
                "operatingFlightNumber": fnum, "operatingCarrierCode": "AC", "flightId": f"AC#{flt}#{DATE}#{org}"}

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

    appr400 = lambda: block("APPR", "ELIGIBLE", "FD-APPR-EL-400", 400, "CAD", "DELAY_3_TO_LT_6_HOURS")
    if kind in ("ASL_NE", "ASL_ND", "ASL_PE"):
        comp = [block("ASL", status, sys, 0, "ILS", "NOT_APPLICABLE"), na("APPR"), na("EU")]
    elif kind == "MIXED_EU":  # EU selected, APPR also eligible $400
        comp = [block("EU", "ELIGIBLE", sys, amt, cur, "DELAY_GTE_4_HOURS"), appr400(), na("ASL")]
    elif kind == "MIXED_APPR":  # APPR selected $400, ASL not eligible (<8h)
        comp = [block("APPR", "ELIGIBLE", sys, amt, cur, "DELAY_3_TO_LT_6_HOURS"),
                block("ASL", "NOT_ELIGIBLE", "FD-ASL-NE-22", 0, "ILS", "NOT_APPLICABLE"), na("EU")]
    else:  # MIXED_EUNE — EU eligible, APPR not eligible (controllability divergence)
        comp = [block("EU", "ELIGIBLE", sys, amt, cur, "DELAY_GTE_4_HOURS"),
                block("APPR", "NOT_ELIGIBLE", "FD-APPR-NE-28", 0, "CAD", "NOT_APPLICABLE"), na("ASL")]

    dds = {
        "eventMetadata": {"trigger": "DISRUPTION_DETECTION_SERVICE", "timestamp": f"{DATE}T09:05:34.000Z"},
        "pnrIdentifier": {"pnrId": pid, "pnr": loc},
        "itineraryDetails": [{"bound": 1, "boundRph": 1, "isOAL": False,
                              "promisedItinerary": {"origin": org, "destination": prom, "associatedSegments": [dseg()]},
                              "actualItinerary": {"origin": org, "destination": dst, "associatedSegments": [dseg()]}}],
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
                amount=amt, currency=cur, route=f"{org}-{dst}", label=label, ticket=f"014249{n:03d}0001", pin=True)
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
        print(f"  {meta['tc']} {meta['loc']} {meta['regime']:4} {meta['status']:16} {meta['syscode']:15} {amt:>9} {meta['route']:8} {meta['pax']}")
    (FD_SIT / "_FD_TC121_150_index.json").write_text(json.dumps(rows, indent=2) + "\n")
    print(f"\nWrote {len(rows)} scenarios + DDS; index -> _FD_TC121_150_index.json")


if __name__ == "__main__":
    main()
