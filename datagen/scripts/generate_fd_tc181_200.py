#!/usr/bin/env python3
"""
FD_UAT (Tiroshan) test-data for FD_TC_181..200 — INT (completes the 200-case sheet).

181 bus-segment NE, 182 No-Travel cancellation EL $400, 183 PAL-airlines-MSL EL $400,
184 denied-boarding EL $900 (FD-APPR-DB-01), 185-200 third-party caller scenarios
(pre-DDS caller-authorization flows — the sheet's expected is empty; each gets a standard
claimable APPR $400 booking and the caller-type is exercised in the chat, not the data).

Email/auth mailbox (all PNR contacts): isuru.lakmal@ext.aircanada.ca
"""
import json
from datetime import datetime, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
FD_SIT = HERE.parent / "scenarios" / "fd-sit"
DDS_DIR = FD_SIT / "_dds-templates"
DATE, ISSUE = "2026-06-15", "2026-06-01"
MAIL, OFFICE, DOB = "isuru.lakmal@ext.aircanada.ca", "YULAC010V", "1986-04-23"

LOCS = ["CNBVSN","GCFWXS","JKQSBS","KHGBDY","KWQNKJ","LCRKVH","LGHSXB","LKVSPJ","NFFTCX","RGPYPF",
        "RRTXMC","RRWDYD","SSNWYW","VKLGNG","WFTRQQ","WVGMVX","XSTQXK","XZGMZS","YFPWMH","ZYDYWC"]

TP = "Standard APPR $400 booking behind 3rd-party scenario: "
# n, (first,last), kind, status, origin, dest, flt, delay, code, dtype, amt, sys, label
C = [
 (181,("MARC-ANDRE","PELLETIER"),"APPR_NE","NOT_ELIGIBLE","YUL","CDG","870",180,"BUS","OTHER",0,"FD-APPR-NE-31","Bus segment disrupted (non-flight, all regimes NE)"),
 (182,("MATHIEU","PELLETIER"),"APPR_EL","ELIGIBLE","YUL","YYZ","430",240,"CREW","CONTROLLABLE",400,"FD-APPR-EL-400","No Travel — INVOL cancellation (refund + $400)"),
 (183,("ELISE","BEAUMONT"),"APPR_EL","ELIGIBLE","MNL","CEB","102",240,"42","CONTROLLABLE",400,"FD-APPR-EL-400","PAL Airlines as MSL (coding present)"),
 (184,("ANTOINE","LAVOIE"),"APPR_DB","ELIGIBLE","MNL","CEB","207",300,"DB","OTHER",900,"FD-APPR-DB-01","Denied Boarding (PAL) — $900 APPR DB"),
 (185,("HELENE","TREMBLAY"),"APPR_EL","ELIGIBLE","YUL","YYZ","301",240,"42","CONTROLLABLE",400,"FD-APPR-EL-400",TP+"Claims Company, not in CS, Canada (rejected)"),
 (186,("PIERRE","MARTIN"),"APPR_EL","ELIGIBLE","YUL","YYZ","301",240,"42","CONTROLLABLE",400,"FD-APPR-EL-400",TP+"Claims Company, not in CS, France EU (manual handoff)"),
 (187,("GERARD","DUBOIS"),"APPR_EL","ELIGIBLE","YUL","YYZ","301",240,"42","CONTROLLABLE",400,"FD-APPR-EL-400",TP+"Claims Company, not in CS, US, dispute (manual)"),
 (188,("MARIE","LAURENT"),"APPR_EL","ELIGIBLE","YUL","YYZ","301",240,"42","CONTROLLABLE",400,"FD-APPR-EL-400",TP+"Claims Company, claim NOT opened, Canada (rejected)"),
 (189,("LUC","BERTRAND"),"APPR_EL","ELIGIBLE","YUL","YYZ","301",240,"42","CONTROLLABLE",400,"FD-APPR-EL-400",TP+"Claims Company, NOT opened, Belgium EU (manual)"),
 (190,("SARAH","JOHNSON"),"APPR_EL","ELIGIBLE","YUL","YYZ","301",240,"42","CONTROLLABLE",400,"FD-APPR-EL-400",TP+"Claims Company, NOT opened, US, dispute (manual)"),
 (191,("PAUL","LEFEBVRE"),"APPR_EL","ELIGIBLE","YUL","YYZ","301",240,"42","CONTROLLABLE",400,"FD-APPR-EL-400",TP+"Claims Company, exists in CS <30d, no resolution (wait)"),
 (192,("ANNE","ROY"),"APPR_EL","ELIGIBLE","YUL","YYZ","301",240,"42","CONTROLLABLE",400,"FD-APPR-EL-400",TP+"Claims Company, exists <30d, dispute (manual)"),
 (193,("DAVID","CHEN"),"APPR_EL","ELIGIBLE","YUL","YYZ","301",240,"42","CONTROLLABLE",400,"FD-APPR-EL-400",TP+"Travel Agency (rejected — customer must submit)"),
 (194,("LISA","WONG"),"APPR_EL","ELIGIBLE","YUL","YYZ","301",240,"42","CONTROLLABLE",400,"FD-APPR-EL-400",TP+"Travel Agency, user disputes (manual)"),
 (195,("ROBERT","KING"),"APPR_EL","ELIGIBLE","YUL","YYZ","301",240,"42","CONTROLLABLE",400,"FD-APPR-EL-400",TP+"Executive Assistant (rejected)"),
 (196,("EMMA","WILSON"),"APPR_EL","ELIGIBLE","YUL","YYZ","301",240,"42","CONTROLLABLE",400,"FD-APPR-EL-400",TP+"Family/Friend, OTP passed (automated — allowed)"),
 (197,("JAMES","BROWN"),"APPR_EL","ELIGIBLE","YUL","YYZ","301",240,"42","CONTROLLABLE",400,"FD-APPR-EL-400",TP+"Family/Friend, OTP failed, upload POA (manual)"),
 (198,("CLAIRE","MOREAU"),"APPR_EL","ELIGIBLE","YUL","YYZ","301",240,"42","CONTROLLABLE",400,"FD-APPR-EL-400",TP+"Individual with POA (Legal/Tutor/Insurer) — manual"),
 (199,("MARK","TAYLOR"),"APPR_EL","ELIGIBLE","YUL","YYZ","301",240,"42","CONTROLLABLE",400,"FD-APPR-EL-400",TP+"POA, no document provided (denied)"),
 (200,("SOPHIE","GAGNON"),"APPR_EL","ELIGIBLE","YUL","YYZ","301",240,"42","CONTROLLABLE",400,"FD-APPR-EL-400",TP+"Parent claiming for Minor (UMNR), OTP passed (automated)"),
]


def band_for(amt):
    return ("DELAY_9_HOURS_OR_MORE" if amt >= 1000 else
            "DELAY_6_TO_LT_9_HOURS" if amt >= 700 else
            "DELAY_3_TO_LT_6_HOURS" if amt >= 400 else "NOT_APPLICABLE")


def hh(h, m=0):
    return datetime.fromisoformat(f"{DATE}T{h:02d}:00:00") + timedelta(minutes=m)


def build(rec):
    n, (fn, ln), kind, status, org, dst, flt, delay, code, dtype, amt, sys, label = rec
    loc = LOCS[n - 181]
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
           "email": MAIL, "phone": f"+1416555{7000+n:04d}"}
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
                      "ticket_numbers": [f"014251{n:03d}0001"]},
        "timeline": [{"version": 0, "at": f"{ISSUE}T10:00:00Z", "action": "bootstrap", "description": "Pre-ticketing stub"},
                     {"version": 1, "at": f"{ISSUE}T10:00:01Z", "action": "ticketing_added", "description": "Ticketing reference attached"}],
        "expected_cascade": {"db_end_state": {"trip": {"rows": 1, "status": "ACTIVE", "pnr": loc, "pnr_id": pid},
                                              "passenger": {"rows": 1}, "flight_segment": {"rows": 1}},
                             "total_cascade_budget_ms": 30000},
        "classification": {"primary_code": f"FD-TC-{n:03d}", "primary_name": f"Flight Disruption FD_TC_{n:03d} INT", "confidence": "high"},
        "tags": ["synthetic", f"fd-tc-{n:03d}", "appr", status.lower()] + (["third-party"] if n >= 185 else []),
    }

    def dseg():
        return {"segmentId": f"{pid}-ST-1", "segmentStatus": "HK",
                "departureDatetime": dep.strftime("%Y-%m-%dT%H:%M:00+00:00"), "arrivalDatetime": arr.strftime("%Y-%m-%dT%H:%M:00+00:00"),
                "departureAirport": org, "arrivalAirport": dst, "marketingFlightNumber": fnum, "marketingCarrierCode": "AC",
                "operatingFlightNumber": fnum, "operatingCarrierCode": "AC", "flightId": f"AC#{flt}#{DATE}#{org}"}

    def block(st, sc, a, band):
        cd = {"amount": a, "currency": "CAD", "delayBand": band}
        if st == "ELIGIBLE":
            cd["expiryDate"] = "2027-06-15"
        return {"regime": "APPR", "boundRph": 1,
                "mslFlight": {"segmentId": f"{pid}-ST-1", "carrierCode": "AC", "flightNumber": flt, "departureAirport": org,
                              "arrivalAirport": dst, "isStarSegment": False, "isOalSegment": False},
                "disruptionType": "INVOLUNTARY", "delayMinutes": delay, "delayType": dtype, "delayCode": code,
                "customerFriendlyDisruptionReason": "Your flight was disrupted.", "disruptionReason": "MECHANICAL",
                "passengerEligibility": [{"passengerId": f"{pid}-PT-1", "passengerType": "ADT", "eligibilityStatus": st,
                                          "systemCode": sc, "reason": label[:60], "compensationDetails": cd}]}

    def na(regime):
        return {"regime": regime, "boundRph": 1,
                "passengerEligibility": [{"passengerId": f"{pid}-PT-1", "passengerType": "ADT",
                                          "eligibilityStatus": "NOT_ELIGIBLE", "systemCode": f"FD-{regime}-NA-01",
                                          "compensationDetails": {"amount": 0, "currency": "CAD", "delayBand": "NOT_APPLICABLE"}}]}

    st = "ELIGIBLE" if kind in ("APPR_EL", "APPR_DB") else "NOT_ELIGIBLE"
    comp = [block(st, sys, amt, band_for(amt) if amt else "NOT_APPLICABLE"), na("EU"), na("ASL")]

    dds = {
        "eventMetadata": {"trigger": "DISRUPTION_DETECTION_SERVICE", "timestamp": f"{DATE}T09:05:34.000Z"},
        "pnrIdentifier": {"pnrId": pid, "pnr": loc},
        "itineraryDetails": [{"bound": 1, "boundRph": 1, "isOAL": False,
                              "promisedItinerary": {"origin": org, "destination": dst, "associatedSegments": [dseg()]},
                              "actualItinerary": {"origin": org, "destination": dst, "associatedSegments": [dseg()]}}],
        "compensationEligibility": comp,
        "socFlightEligibility": [{"regime": "APPR", "boundRph": 1, "segmentId": f"{pid}-ST-1", "carrierCode": "AC",
                                  "flightNumber": fnum, "departureAirport": org, "arrivalAirport": dst, "segmentStatus": "HK",
                                  "disruptionType": "INVOLUNTARY", "delayType": "OTHER", "delayCode": "", "disruptionReason": "",
                                  "customerFriendlyDisruptionReason": "", "delayMinutes": 0, "delayCategory": "DELAY_LT_2_HOURS",
                                  "passengerEligibility": [{"passengerId": f"{pid}-PT-1", "passengerType": "ADT",
                                                            "bookingClass": None, "cabinClass": "ECONOMY",
                                                            "eligibilityStatus": "NO_DETERMINATION", "systemCode": "SoC-APPR-ND-04",
                                                            "reason": "Data missing - 14 days", "expiryDate": "", "expenseCategories": []}]}],
        "seatFeeRefundEligibility": [],
    }
    meta = dict(loc=loc, pnr_id=pid, tc=f"FD_TC_{n:03d}", pax=f"{fn} {ln}", status=st, regime="APPR", syscode=sys,
                amount=amt, currency="CAD", route=f"{org}-{dst}", label=label, ticket=f"014251{n:03d}0001", pin=True)
    return scen, dds, meta


def main():
    DDS_DIR.mkdir(parents=True, exist_ok=True)
    rows = []
    for rec in C:
        scen, dds, meta = build(rec)
        (FD_SIT / f"{meta['pnr_id']}.json").write_text(json.dumps(scen, indent=2) + "\n")
        (DDS_DIR / f"{meta['pnr_id']}.dds.json").write_text(json.dumps(dds, indent=2) + "\n")
        rows.append(meta)
        amt = f"CAD {meta['amount']}" if meta["amount"] else "—"
        print(f"  {meta['tc']} {meta['loc']} {meta['status']:16} {meta['syscode']:14} {amt:>8} {meta['route']:8} {meta['pax']}")
    (FD_SIT / "_FD_TC181_200_index.json").write_text(json.dumps(rows, indent=2) + "\n")
    print(f"\nWrote {len(rows)} scenarios + DDS; index -> _FD_TC181_200_index.json")


if __name__ == "__main__":
    main()
