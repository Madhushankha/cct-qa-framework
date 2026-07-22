#!/usr/bin/env python3
"""
FD_UAT (Tiroshan) test-data for FD_TC_061..090 — INT.

Mostly EU 261 ELIGIBLE (UK / Rest-of-Europe / Guadeloupe; EU is the selected most-generous
regime so its block is compensationEligibility[0]), plus APPR NOT_ELIGIBLE / NO_DETERMINATION
(061/062/064/065) and one pre-travel rejection (063 — future flight, NO DDS pin / no case).

Bookings are single AC legs on the case route (origin drives the regime); the pinned DDS carries
the verdict (status + systemCode + amount + currency). EU shapes are best-effort.

Email/auth mailbox (all PNR contacts): wathsala.widanagamaachchi@aircanada.ca
"""
import json
from datetime import datetime, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
FD_SIT = HERE.parent / "scenarios" / "fd-sit"
DDS_DIR = FD_SIT / "_dds-templates"
DEF_DATE, ISSUE = "2026-06-15", "2026-06-01"
MAIL, OFFICE, DOB = "wathsala.widanagamaachchi@aircanada.ca", "YULAC010V", "1986-04-23"

LOCS = ["BGMHQB","BYRMFH","CKRDXK","DMLJXR","FNJRYZ","GQLQYP","GRXQCF","GSJXST","HGPLBV","JGKLBG",
        "LCGTHG","LHWRBB","LQCTTC","LSNCDR","NCCXLB","NZHRGD","QFGFSM","RMRLZD","RYXCRQ","SCVHBL",
        "TFPTTG","TNDQZP","TQCBTV","TXRFCZ","VRMRJY","VSJGMV","WKYHHF","YFXMBG","ZBDHGX","ZPJHJR"]

# n, (first,last), kind, status, origin, actual_dest, prom_dest, flt, delay, code, dtype,
#   eu_cur, eu_amt, eu_sys, label
# kind: APPR_NE | APPR_ND | EU_EL | PRE
C = [
 (61,("ANNE-MARIE","PARADIS"),"APPR_NE","NOT_ELIGIBLE","YUL","YYZ","YYZ","428",0,"NONE","OTHER",None,0,"FD-APPR-NE-27","VOL only, no delay"),
 (62,("MICHEL","LAFLEUR"),"APPR_NE","NOT_ELIGIBLE","YUL","YYZ","YYZ","424",0,"NONE","OTHER",None,0,"FD-APPR-NE-27","INVOL earlier flight (arrived early)"),
 (63,("SYLVIE","COTE"),"PRE","PRE_TRAVEL","YUL","YYZ","YYZ","427",0,"NONE","OTHER",None,0,"N/A","Pre-travel rejection (future flight, no case)"),
 (64,("CLAUDINE","VEZINA"),"APPR_NE","NOT_ELIGIBLE","YUL","YYZ","YYZ","301",240,"72","UNCONTROLLABLE",None,0,"FD-APPR-NE-28","Welcome Back -> NE (weather)"),
 (65,("GAETAN","RIVARD"),"APPR_ND","NO_DETERMINATION","YUL","YYZ","YYZ","301",240,"NULL","UNKNOWN",None,0,"FD-APPR-ND-09","14-day exhausted -> agent"),
 (66,("OLIVER","BENNETT"),"EU_EL","ELIGIBLE","LHR","YYZ","YYZ","858",210,"42","CONTROLLABLE","GBP",260,"FD-EU-EL-01","EU-UK 3-<4h GBP260"),
 (67,("HARRY","CLARKE"),"EU_EL","ELIGIBLE","LHR","YYZ","YYZ","858",300,"42","CONTROLLABLE","GBP",520,"FD-EU-EL-02","EU-UK 4+h GBP520"),
 (68,("EMILY","WATSON"),"EU_EL","ELIGIBLE","LHR","YTZ","YYZ","858",210,"42","CONTROLLABLE","GBP",260,"FD-EU-EL-03","EU-UK 3-<4h Sister City GBP260"),
 (69,("MARIE","DUPUIS"),"EU_EL","ELIGIBLE","CDG","YTZ","YYZ","870",240,"42","CONTROLLABLE","EUR",600,"FD-EU-EL-04","EU Rest 4+h Sister City EUR600"),
 (70,("JACK","TURNER"),"EU_EL","ELIGIBLE","LHR","YYZ","YYZ","858",210,"42","CONTROLLABLE","GBP",260,"FD-EU-EL-05","EU-UK 3-<4h Fallback GBP260"),
 (71,("SOPHIE","HUGHES"),"EU_EL","ELIGIBLE","LHR","YYZ","YYZ","858",300,"42","CONTROLLABLE","GBP",520,"FD-EU-EL-06","EU-UK 4+h Fallback GBP520"),
 (72,("GEORGE","MORGAN"),"EU_EL","ELIGIBLE","LHR","YTZ","YYZ","858",210,"42","CONTROLLABLE","GBP",260,"FD-EU-EL-07","EU-UK 3-<4h Sister+Fallback GBP260"),
 (73,("THOMAS","WRIGHT"),"EU_EL","ELIGIBLE","LHR","YTZ","YYZ","858",300,"42","CONTROLLABLE","GBP",520,"FD-EU-EL-08","EU-UK 4+h Sister+Fallback GBP520"),
 (74,("MARIE-CLAIRE","JOSEPH"),"EU_EL","ELIGIBLE","PTP","YUL","YUL","1840",210,"42","CONTROLLABLE","EUR",400,"FD-EU-EL-09","EU Guadeloupe 3+h EUR400"),
 (75,("JEAN-PIERRE","DUBOIS"),"EU_EL","ELIGIBLE","PTP","YOW","YUL","1840",210,"42","CONTROLLABLE","EUR",400,"FD-EU-EL-10","EU Guadeloupe Sister City EUR400"),
 (76,("ISABELLE","FONTAINE"),"EU_EL","ELIGIBLE","PTP","YUL","YUL","1840",210,"42","CONTROLLABLE","EUR",400,"FD-EU-EL-11","EU Guadeloupe Fallback EUR400"),
 (77,("LAURENT","MERCIER"),"EU_EL","ELIGIBLE","PTP","YOW","YUL","1840",210,"42","CONTROLLABLE","EUR",400,"FD-EU-EL-12","EU Guadeloupe Sister+Fallback EUR400"),
 (78,("ANTOINE","DUPONT"),"EU_EL","ELIGIBLE","CDG","YYZ","YYZ","870",210,"42","CONTROLLABLE","EUR",300,"FD-EU-EL-13","EU Rest 3-<4h EUR300"),
 (79,("CLAUDE","FONTAINE"),"EU_EL","ELIGIBLE","CDG","YYZ","YYZ","871",285,"42","CONTROLLABLE","EUR",600,"FD-EU-EL-14","EU Rest 4+h EUR600"),
 (80,("MARIE-CLAIRE","DUBOIS"),"EU_EL","ELIGIBLE","CDG","YTZ","YYZ","870",205,"42","CONTROLLABLE","EUR",300,"FD-EU-EL-15","EU Rest 3-<4h Sister City EUR300"),
 (81,("JEAN-LUC","MOREAU"),"EU_EL","ELIGIBLE","CDG","YTZ","YYZ","870",290,"42","CONTROLLABLE","EUR",600,"FD-EU-EL-16","EU Rest 4+h Sister City EUR600"),
 (82,("CAMILLE","LEFEVRE"),"EU_EL","ELIGIBLE","CDG","YYZ","YYZ","870",220,"19","CONTROLLABLE","EUR",300,"FD-EU-EL-17","EU Rest 3-<4h Fallback EUR300"),
 (83,("ETIENNE","BEAUMONT"),"EU_EL","ELIGIBLE","CDG","YYZ","YYZ","870",275,"11","CONTROLLABLE","EUR",600,"FD-EU-EL-18","EU Rest 4+h Fallback EUR600"),
 (84,("NOEMIE","GIRARD"),"EU_EL","ELIGIBLE","CDG","YTZ","YYZ","870",205,"25","CONTROLLABLE","EUR",300,"FD-EU-EL-19","EU Rest 3-<4h Sister+Fallback EUR300"),
 (85,("JULIEN","MARCHAND"),"EU_EL","ELIGIBLE","CDG","YTZ","YYZ","870",290,"37","CONTROLLABLE","EUR",600,"FD-EU-EL-20","EU Rest 4+h Sister+Fallback EUR600"),
 (86,("HENRY","WHITFIELD"),"EU_EL","ELIGIBLE","LHR","YYZ","YYZ","849",0,"CREW","CONTROLLABLE","GBP",520,"FD-EU-EL-21","EU-UK No Travel Origin GBP520"),
 (87,("BENOIT","LECLERC"),"EU_EL","ELIGIBLE","CDG","YYZ","YYZ","871",0,"CREW","CONTROLLABLE","EUR",600,"FD-EU-EL-25","EU Mainland No Travel Origin EUR600"),
 (88,("MAXIME","THEODORE"),"EU_EL","ELIGIBLE","PTP","YYZ","YYZ","422",0,"CREW","CONTROLLABLE","EUR",400,"FD-EU-EL-35","EU Guadeloupe No Travel Incomplete EUR400"),
 (89,("THOMAS","HARRINGTON"),"EU_EL","ELIGIBLE","LHR","YVR","YVR","121",0,"CREW","CONTROLLABLE","GBP",520,"FD-EU-EL-27","EU-UK No Travel Return GBP520"),
 (90,("REGIS","BARTHELEMY"),"EU_EL","ELIGIBLE","PTP","YYZ","YYZ","422",0,"CREW","CONTROLLABLE","EUR",400,"FD-EU-EL-29","EU Guadeloupe No Travel Return EUR400"),
]


def eu_band(delay):
    if delay == 0: return "NOT_APPLICABLE"
    return "DELAY_GTE_4_HOURS" if delay >= 240 else "DELAY_3_TO_LT_4_HOURS"


def hh(h, m=0):
    return datetime.fromisoformat(f"2026-06-15T{h:02d}:00:00") + timedelta(minutes=m)


def build(rec):
    n, (fn, ln), kind, status, org, dst, prom, flt, delay, code, dtype, eu_cur, eu_amt, sys, label = rec
    loc = LOCS[n - 61]
    date = "2026-08-15" if kind == "PRE" else DEF_DATE
    pid = f"{loc}-{date}"
    dep, arr = hh(10), hh(14)
    seg = {"carrier": "AC", "operating_carrier": "AC", "flight_number": flt, "operating_flight_number": flt,
           "origin": org, "destination": dst,
           "dep_local": dep.strftime(f"{date}T%H:%M:%S"), "arr_local": arr.strftime(f"{date}T%H:%M:%S"),
           "dep_utc": (dep + timedelta(hours=4)).strftime(f"{date}T%H:%M:%SZ"),
           "arr_utc": (arr + timedelta(hours=4)).strftime(f"{date}T%H:%M:%SZ"),
           "booking_datetime": None, "aircraft": "320", "cabin": "Y", "status": "HK", "arrival_terminal": "1"}
    pax = {"type": "ADT", "first_name": fn, "last_name": ln, "gender": "U", "date_of_birth": DOB,
           "email": MAIL, "phone": f"+1416555{3000+n:04d}"}
    scen = {
        "$schema_version": 2, "scenario_id": pid,
        "title": f"FD_TC_{n:03d}: {label} - {fn} {ln} [{loc}]",
        "description": f"FD_TC_{n:03d} | {status} | {label} | {sys}",
        "canvas": "_canvas/pnr_creation_domestic_ac.json", "contains_pii": False,
        "identity": {"pnr": loc, "booking_date": date, "type": "PNR"},
        "point_of_sale": {"office_id": OFFICE, "iata_number": "01424012", "system_code": "1A",
                          "agent_type": "AIRLINE", "agent_numeric_sign": "0001", "agent_initials": "FD",
                          "duty_code": "SU", "agent_country": "CA", "agent_city": "YUL"},
        "last_modification_comment": f"SIM-FD-TC-{n:03d}-INT", "creation_comment": f"SIM-FD-TC-{n:03d}-INT",
        "passengers": [pax], "segments": [seg],
        "ticketing": {"issuance_local_date": ISSUE, "fare": {"amount": "350.00", "currency": "CAD"},
                      "ticket_numbers": [f"014247{n:03d}0001"]},
        "timeline": [{"version": 0, "at": f"{ISSUE}T10:00:00Z", "action": "bootstrap", "description": "Pre-ticketing stub"},
                     {"version": 1, "at": f"{ISSUE}T10:00:01Z", "action": "ticketing_added", "description": "Ticketing reference attached"}],
        "expected_cascade": {"db_end_state": {"trip": {"rows": 1, "status": "ACTIVE", "pnr": loc, "pnr_id": pid},
                                              "passenger": {"rows": 1}, "flight_segment": {"rows": 1}},
                             "total_cascade_budget_ms": 30000},
        "classification": {"primary_code": f"FD-TC-{n:03d}", "primary_name": f"Flight Disruption FD_TC_{n:03d} INT", "confidence": "high"},
        "tags": ["synthetic", f"fd-tc-{n:03d}", "eu" if kind == "EU_EL" else "appr", status.lower()],
    }

    def dseg(o, d, fl):
        dp, ar = hh(10), hh(14)
        return {"segmentId": f"{pid}-ST-1", "segmentStatus": "HK",
                "departureDatetime": dp.strftime(f"{date}T%H:%M:00+00:00"), "arrivalDatetime": ar.strftime(f"{date}T%H:%M:00+00:00"),
                "departureAirport": o, "arrivalAirport": d, "marketingFlightNumber": int(fl), "marketingCarrierCode": "AC",
                "operatingFlightNumber": int(fl), "operatingCarrierCode": "AC", "flightId": f"AC#{fl}#{date}#{o}"}

    actual_segs = [dseg(org, dst, flt)]
    prom_segs = [dseg(org, prom, flt)]

    def msl(reg):
        return {"segmentId": f"{pid}-ST-1", "carrierCode": "AC", "flightNumber": flt, "departureAirport": org,
                "arrivalAirport": dst, "isStarSegment": False, "isOalSegment": False}

    def block(regime, st, sc, amt, cur, band):
        cd = {"amount": amt, "currency": cur, "delayBand": band}
        if st == "ELIGIBLE":
            cd["expiryDate"] = "2027-06-15"
        pe = [{"passengerId": f"{pid}-PT-1", "passengerType": "ADT", "eligibilityStatus": st, "systemCode": sc,
               "reason": label, "compensationDetails": cd}]
        return {"regime": regime, "boundRph": 1, "mslFlight": msl(regime), "disruptionType": "INVOLUNTARY",
                "delayMinutes": delay, "delayType": dtype, "delayCode": code,
                "customerFriendlyDisruptionReason": "Your flight was disrupted.", "disruptionReason": "MECHANICAL",
                "passengerEligibility": pe}

    def na(regime):
        return {"regime": regime, "boundRph": 1,
                "passengerEligibility": [{"passengerId": f"{pid}-PT-1", "passengerType": "ADT",
                                          "eligibilityStatus": "NOT_ELIGIBLE", "systemCode": f"FD-{regime}-NA-01",
                                          "compensationDetails": {"amount": 0, "currency": "CAD", "delayBand": "NOT_APPLICABLE"}}]}

    if kind == "EU_EL":
        comp = [block("EU", "ELIGIBLE", sys, eu_amt, eu_cur, eu_band(delay)),
                block("APPR", "ELIGIBLE", "FD-APPR-EL-400", 400, "CAD", "DELAY_3_TO_LT_6_HOURS"), na("ASL")]
    elif kind in ("APPR_NE", "APPR_ND"):
        comp = [block("APPR", status, sys, 0, "CAD", "NOT_APPLICABLE"), na("EU"), na("ASL")]
    else:  # PRE — no DDS pinned
        comp = None

    dds = None
    if comp is not None:
        dds = {
            "eventMetadata": {"trigger": "DISRUPTION_DETECTION_SERVICE", "timestamp": f"{date}T09:05:34.000Z"},
            "pnrIdentifier": {"pnrId": pid, "pnr": loc},
            "itineraryDetails": [{"bound": 1, "boundRph": 1, "isOAL": False,
                                  "promisedItinerary": {"origin": org, "destination": prom, "associatedSegments": prom_segs},
                                  "actualItinerary": {"origin": org, "destination": dst, "associatedSegments": actual_segs}}],
            "compensationEligibility": comp,
            "socFlightEligibility": [{"regime": "APPR", "boundRph": 1, "segmentId": f"{pid}-ST-1", "carrierCode": "AC",
                                      "flightNumber": int(flt), "departureAirport": org, "arrivalAirport": dst,
                                      "segmentStatus": "HK", "disruptionType": "INVOLUNTARY", "delayType": "OTHER",
                                      "delayCode": "", "disruptionReason": "", "customerFriendlyDisruptionReason": "",
                                      "delayMinutes": 0, "delayCategory": "DELAY_LT_2_HOURS",
                                      "passengerEligibility": [{"passengerId": f"{pid}-PT-1", "passengerType": "ADT",
                                                                "bookingClass": None, "cabinClass": "ECONOMY",
                                                                "eligibilityStatus": "NO_DETERMINATION", "systemCode": "SoC-APPR-ND-04",
                                                                "reason": "Data missing - 14 days", "expiryDate": "", "expenseCategories": []}]}],
            "seatFeeRefundEligibility": [],
        }
    cur = eu_cur or "CAD"
    amt = eu_amt if kind == "EU_EL" else 0
    meta = dict(loc=loc, pnr_id=pid, tc=f"FD_TC_{n:03d}", pax=f"{fn} {ln}", status=status, syscode=sys,
                amount=amt, currency=cur, route=f"{org}-{dst}", delay=delay, code=code, label=label,
                ticket=f"014247{n:03d}0001", date=date, pin=(dds is not None))
    return scen, dds, meta


def main():
    DDS_DIR.mkdir(parents=True, exist_ok=True)
    rows = []
    for rec in C:
        scen, dds, meta = build(rec)
        (FD_SIT / f"{meta['pnr_id']}.json").write_text(json.dumps(scen, indent=2) + "\n")
        if dds is not None:
            (DDS_DIR / f"{meta['pnr_id']}.dds.json").write_text(json.dumps(dds, indent=2) + "\n")
        rows.append(meta)
        amt = f"{meta['currency']} {meta['amount']}" if meta["amount"] else "—"
        print(f"  {meta['tc']} {meta['loc']} {meta['status']:16} {meta['syscode']:14} {amt:>9} {meta['route']:8} {meta['pax']}")
    (FD_SIT / "_FD_TC61_90_index.json").write_text(json.dumps(rows, indent=2) + "\n")
    print(f"\nWrote {len(rows)} scenarios ({sum(1 for r in rows if r['pin'])} with DDS); index -> _FD_TC61_90_index.json")


if __name__ == "__main__":
    main()
