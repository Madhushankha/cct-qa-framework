#!/usr/bin/env python3
"""
FD_UAT (Tiroshan) test-data for FD_TC_151..180 — INT.

Mostly APPR: VOL/INVOL tool classification + VOL<->INVOL deduction logic -> ELIGIBLE
($400 Tier1 / $700 Tier2 / $1000 Tier3), VOL-only & duplicate & train-segment -> NOT_ELIGIBLE.
Plus 2 MIXED-regime (151 both-NE, 152 EU-eligible). The selected regime is
compensationEligibility[0]; pinned DDS carries the verdict. Single AC leg per booking.

Email/auth mailbox (all PNR contacts): avishka.pramod@ext.aircanada.ca
"""
import json
from datetime import datetime, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
FD_SIT = HERE.parent / "scenarios" / "fd-sit"
DDS_DIR = FD_SIT / "_dds-templates"
DATE, ISSUE = "2026-06-15", "2026-06-01"
MAIL, OFFICE, DOB = "avishka.pramod@ext.aircanada.ca", "YULAC010V", "1986-04-23"

LOCS = ["BKRGJQ","BLWBPY","CJFKJZ","DDWPCD","DXHNTG","DXMRNS","FQPDYQ","GMCRXS","GXYLTT","JGMWHP",
        "KGSMFQ","LCGRYX","LXDYTH","MNPGRH","MPXWFC","MRKDGM","MWXTCH","NDHGTW","NNQHMS","PDMCJJ",
        "QPYKVW","SRHXHQ","SZKMYB","TJHNYC","VCMMHV","WBJTKL","WDBQTR","WGNLRC","YWHRCG","ZFWGYG"]

# n, (first,last), kind, status, primary, origin, dest, flt, delay, code, dtype, cur, amt, sys, label
C = [
 (151,("ROGER","WHITEHALL"),"MIXED_NE","NOT_ELIGIBLE","EU","LHR","YYZ","858",240,"72","UNCONTROLLABLE","GBP",0,"FD-MIXED-NE-02","Mixed EU+APPR both NE (extraordinary)"),
 (152,("SYLVAIN","MOREAU"),"MIXED_EL","ELIGIBLE","EU","CDG","TLV","9070",240,"42","CONTROLLABLE","EUR",400,"FD-MIXED-ND-01","Mixed EU EL EUR400 (ASL ND)"),
 (153,("CATHERINE","BOUCHARD"),"APPR_NE","NOT_ELIGIBLE","APPR","YUL","YYZ","301",240,"42","CONTROLLABLE","CAD",0,"FD-DUP-NE-01","Duplicate claim (same pax/flight)"),
 (154,("CATHERINE","BOUCHARD"),"APPR_NE","NOT_ELIGIBLE","APPR","YUL","YYZ","301",240,"42","CONTROLLABLE","CAD",0,"FD-DUP-NE-02","Duplicate passenger (already compensated)"),
 (155,("ANDRE","PELLETIER"),"APPR_NE","NOT_ELIGIBLE","APPR","YUL","YYZ","301",0,"NONE","OTHER","CAD",0,"FD-APPR-NE-27","VOL-only Pre-Move (no delay)"),
 (156,("BRIGITTE","LAVOIE"),"APPR_NE","NOT_ELIGIBLE","APPR","YUL","YYZ","301",0,"NONE","OTHER","CAD",0,"FD-APPR-NE-27","VOL-only Volantio (no delay)"),
 (157,("MARC-ANTOINE","GAGNON"),"APPR_NE","NOT_ELIGIBLE","APPR","YUL","YYZ","301",0,"NONE","OTHER","CAD",0,"FD-APPR-NE-27","VOL-only Contact Center (no delay)"),
 (158,("NATHALIE","COTE"),"APPR_NE","NOT_ELIGIBLE","APPR","YUL","YYZ","301",0,"NONE","OTHER","CAD",0,"FD-APPR-NE-27","VOL-only Airport Agent (no delay)"),
 (159,("PHILIPPE","BOUDREAU"),"APPR_NE","NOT_ELIGIBLE","APPR","YUL","YYZ","301",0,"NONE","OTHER","CAD",0,"FD-APPR-NE-27","VOL-only ATC (no delay)"),
 (160,("LAURENT","TREMBLAY"),"APPR_EL","ELIGIBLE","APPR","YUL","YYZ","301",270,"42","CONTROLLABLE","CAD",400,"FD-APPR-EL-400","INVOL REACC 4.5h"),
 (161,("CELINE","FOURNIER"),"APPR_EL","ELIGIBLE","APPR","YUL","YYZ","301",300,"42","CONTROLLABLE","CAD",400,"FD-APPR-EL-400","INVOL SELFREACC 5h"),
 (162,("ETIENNE","LAPOINTE"),"APPR_EL","ELIGIBLE","APPR","YUL","YYZ","301",420,"42","CONTROLLABLE","CAD",700,"FD-APPR-EL-700","INVOL DT/COP 7h"),
 (163,("DOMINIQUE","HEBERT"),"APPR_EL","ELIGIBLE","APPR","YUL","YYZ","301",570,"42","CONTROLLABLE","CAD",1000,"FD-APPR-EL-1000","INVOL OPR 9.5h"),
 (164,("GENEVIEVE","ROY"),"APPR_EL","ELIGIBLE","APPR","YUL","YYZ","301",360,"42","CONTROLLABLE","CAD",700,"FD-APPR-EL-700","INVOL Agent+ACNP 6h"),
 (165,("ANDRE","PELLETIER"),"APPR_EL","ELIGIBLE","APPR","YUL","YYZ","301",240,"42","CONTROLLABLE","CAD",400,"FD-APPR-EL-400","VOL->INVOL (last VOL promise) 4h"),
 (166,("JULIE","BERGERON"),"APPR_EL","ELIGIBLE","APPR","YUL","YYZ","301",240,"42","CONTROLLABLE","CAD",400,"FD-APPR-EL-400","VOL->INVOL SELFREACC 4h"),
 (167,("NICOLAS","CHARTRAND"),"APPR_EL","ELIGIBLE","APPR","YUL","YYZ","301",270,"42","CONTROLLABLE","CAD",400,"FD-APPR-EL-400","VOL->INVOL DT 4.5h"),
 (168,("ISABELLE","FORTIER"),"APPR_EL","ELIGIBLE","APPR","YUL","YYZ","301",300,"42","CONTROLLABLE","CAD",400,"FD-APPR-EL-400","VOL->INVOL OPR 5h"),
 (169,("VERONIQUE","LAMBERT"),"APPR_EL","ELIGIBLE","APPR","YUL","YYZ","301",270,"42","CONTROLLABLE","CAD",400,"FD-APPR-EL-400","VOL->INVOL Agent+ACNP 4.5h"),
 (170,("SOPHIE","TREMBLAY"),"APPR_EL","ELIGIBLE","APPR","YUL","YYZ","301",240,"42","CONTROLLABLE","CAD",400,"FD-APPR-EL-400","INVOL->VOL(+ve) net 4h"),
 (171,("FREDERIC","MORIN"),"APPR_EL","ELIGIBLE","APPR","YUL","YYZ","301",240,"42","CONTROLLABLE","CAD",400,"FD-APPR-EL-400","INVOL->VOL(+ve) net 4h"),
 (172,("MELANIE","DUFOUR"),"APPR_EL","ELIGIBLE","APPR","YUL","YYZ","301",240,"42","CONTROLLABLE","CAD",400,"FD-APPR-EL-400","INVOL->VOL(+ve) net 4h"),
 (173,("GABRIEL","LACHANCE"),"APPR_EL","ELIGIBLE","APPR","YUL","YYZ","301",300,"42","CONTROLLABLE","CAD",400,"FD-APPR-EL-400","INVOL->VOL(+ve) net 5h"),
 (174,("CAROLINE","BELANGER"),"APPR_EL","ELIGIBLE","APPR","YUL","YYZ","301",240,"42","CONTROLLABLE","CAD",400,"FD-APPR-EL-400","INVOL->VOL(+ve) net 4h"),
 (175,("ALAIN","BOUCHARD"),"APPR_EL","ELIGIBLE","APPR","YUL","YYZ","301",300,"42","CONTROLLABLE","CAD",400,"FD-APPR-EL-400","INVOL->VOL(-ve) full 5h"),
 (176,("RENEE","CLOUTIER"),"APPR_EL","ELIGIBLE","APPR","YUL","YYZ","301",240,"42","CONTROLLABLE","CAD",400,"FD-APPR-EL-400","INVOL->VOL(-ve) full 4h"),
 (177,("PASCAL","DESCHENES"),"APPR_EL","ELIGIBLE","APPR","YUL","YYZ","301",300,"42","CONTROLLABLE","CAD",400,"FD-APPR-EL-400","INVOL->VOL(-ve) full 5h"),
 (178,("MATHIEU","ARSENAULT"),"APPR_EL","ELIGIBLE","APPR","YUL","YYZ","301",240,"42","CONTROLLABLE","CAD",400,"FD-APPR-EL-400","INVOL->VOL(-ve) full 4h"),
 (179,("ERIC","BEAULIEU"),"APPR_EL","ELIGIBLE","APPR","YUL","YYZ","301",240,"42","CONTROLLABLE","CAD",400,"FD-APPR-EL-400","INVOL->VOL(-ve) full 4h"),
 (180,("ELISE","BEAUCHEMIN"),"APPR_NE","NOT_ELIGIBLE","APPR","YUL","LHR","848",240,"TRAIN","OTHER","CAD",0,"FD-APPR-NE-30","Train segment disrupted (non-flight)"),
]


def band_for(amt):
    return ("DELAY_9_HOURS_OR_MORE" if amt >= 1000 else
            "DELAY_6_TO_LT_9_HOURS" if amt >= 700 else
            "DELAY_3_TO_LT_6_HOURS" if amt >= 400 else "NOT_APPLICABLE")


def hh(h, m=0):
    return datetime.fromisoformat(f"{DATE}T{h:02d}:00:00") + timedelta(minutes=m)


def build(rec):
    n, (fn, ln), kind, status, primary, org, dst, flt, delay, code, dtype, cur, amt, sys, label = rec
    loc = LOCS[n - 151]
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
           "email": MAIL, "phone": f"+1416555{6000+n:04d}"}
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
                      "ticket_numbers": [f"014250{n:03d}0001"]},
        "timeline": [{"version": 0, "at": f"{ISSUE}T10:00:00Z", "action": "bootstrap", "description": "Pre-ticketing stub"},
                     {"version": 1, "at": f"{ISSUE}T10:00:01Z", "action": "ticketing_added", "description": "Ticketing reference attached"}],
        "expected_cascade": {"db_end_state": {"trip": {"rows": 1, "status": "ACTIVE", "pnr": loc, "pnr_id": pid},
                                              "passenger": {"rows": 1}, "flight_segment": {"rows": 1}},
                             "total_cascade_budget_ms": 30000},
        "classification": {"primary_code": f"FD-TC-{n:03d}", "primary_name": f"Flight Disruption FD_TC_{n:03d} INT", "confidence": "high"},
        "tags": ["synthetic", f"fd-tc-{n:03d}", primary.lower(), status.lower()],
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

    if kind == "APPR_EL":
        comp = [block("APPR", "ELIGIBLE", sys, amt, "CAD", band_for(amt)), na("EU"), na("ASL")]
    elif kind == "APPR_NE":
        comp = [block("APPR", "NOT_ELIGIBLE", sys, 0, "CAD", "NOT_APPLICABLE"), na("EU"), na("ASL")]
    elif kind == "MIXED_EL":  # EU selected EUR, APPR also eligible $400, ASL NA
        comp = [block("EU", "ELIGIBLE", sys, amt, cur, "DELAY_GTE_4_HOURS"),
                block("APPR", "ELIGIBLE", "FD-APPR-EL-400", 400, "CAD", "DELAY_3_TO_LT_6_HOURS"), na("ASL")]
    else:  # MIXED_NE — EU NE primary, APPR NE
        comp = [block("EU", "NOT_ELIGIBLE", sys, 0, cur, "NOT_APPLICABLE"),
                block("APPR", "NOT_ELIGIBLE", "FD-APPR-NE-28", 0, "CAD", "NOT_APPLICABLE"), na("ASL")]

    dds = {
        "eventMetadata": {"trigger": "DISRUPTION_DETECTION_SERVICE", "timestamp": f"{DATE}T09:05:34.000Z"},
        "pnrIdentifier": {"pnrId": pid, "pnr": loc},
        "itineraryDetails": [{"bound": 1, "boundRph": 1, "isOAL": False,
                              "promisedItinerary": {"origin": org, "destination": dst, "associatedSegments": [dseg()]},
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
                amount=amt, currency=cur, route=f"{org}-{dst}", label=label, ticket=f"014250{n:03d}0001", pin=True)
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
    (FD_SIT / "_FD_TC151_180_index.json").write_text(json.dumps(rows, indent=2) + "\n")
    print(f"\nWrote {len(rows)} scenarios + DDS; index -> _FD_TC151_180_index.json")


if __name__ == "__main__":
    main()
