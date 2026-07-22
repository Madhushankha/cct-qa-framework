#!/usr/bin/env python3
"""
Generate FD_UAT (Tiroshan) test-data artifacts for FD_TC_001..030 — INT env.

Per test case, emits TWO files (the two sources the Ask AC bot reads):
  scenarios/fd-sit/<LOC>-2026-06-15.json           booking (scenario_engine v2)
  scenarios/fd-sit/_dds-templates/<LOC>-...dds.json DDS response.json (S3 + execution_traces)

All 30 are APPR / ELIGIBLE / controllable. They vary by delay→tier→amount, delay code,
pax count, sister-city (YHM destination), and fallback codes. Tier derives from delay:
  180–359 min → CAD 400 (FD-APPR-EL-400, DELAY_3_TO_LT_6_HOURS)
  360–539 min → CAD 700 (FD-APPR-EL-700, DELAY_6_TO_LT_9_HOURS)
  540+   min → CAD 1000 (FD-APPR-EL-1000, DELAY_9_HOURS_OR_MORE)

Email/auth mailbox (all PNR contacts): sagarika.weerasundara@aircanada.ca
DOB is set separately in trip-tracer (inject doesn't map it).
"""
import json
from datetime import datetime, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
FD_SIT = HERE.parent / "scenarios" / "fd-sit"
DDS_DIR = FD_SIT / "_dds-templates"

DATE = "2026-06-15"
ISSUE = "2026-06-01"
MAIL = "sagarika.weerasundara@aircanada.ca"
OFFICE = "YULAC010V"
DOB = "1986-04-23"

LOCATORS = ["BCNRDY","BWDKZW","CCPSGM","CHPXPP","CMBRYG","DQKZDZ","FHRBFF","FJJNGV","GBLPDV","HJLDSC",
            "JYNRPM","JYYTYR","LKPYCK","LQXSJG","NFTWBG","PGXVLN","QCNGSC","QMJHLG","QPZWRQ","QTMZZP",
            "RFXNMT","TMVLQG","TZNCQH","VSMXWV","WBJQRP","WCNYDG","WFRRCH","XFBBDQ","XYMGLC","ZKFKZC"]


def reason_text(controllable=True):
    return "Your flight arrived more than 3 hours late due to a reason within Air Canada's control."


# Each entry: n, pax (list of (first,last)), aeroplan, legs (actual/flown), promised (orig; None=same),
# delay (min), code, msl (0-based idx into legs), claim_pax (# eligible pax in DDS), group, label
def P(*names): return [tuple(x.split(" ", 1)) for x in names]

TC30 = [
    dict(n=1,  pax=P("CATHERINE BOUCHARD"), aero=False, legs=[("301","YUL","YYZ")], prom=None, delay=240, code="64", msl=0, label="Controllable Delay 3-<6h Cash"),
    dict(n=2,  pax=P("MARIE-CLAIRE DUBOIS"), aero=True, legs=[("302","YUL","YYZ")], prom=None, delay=240, code="64", msl=0, label="AC Wallet (20%)"),
    dict(n=3,  pax=P("HUGO VILLENEUVE"), aero=False, legs=[("8101","YUL","YOW"),("8201","YOW","YYZ")], prom=[("425","YUL","YYZ")], delay=240, code="67", msl=1, label="VOL->INVOL ONE_TO_MANY"),
    dict(n=4,  pax=P("CAMILLE BROSSEAU"), aero=False, legs=[("427","YUL","YYZ")], prom=[("8102","YUL","YOW"),("8202","YOW","YYZ")], delay=240, code="63", msl=0, label="INVOL->VOL(+ve) MANY_TO_ONE"),
    dict(n=5,  pax=P("VALERIE DUPONT"), aero=False, legs=[("8302","YUL","YKF"),("8402","YKF","YYZ")], prom=[("8103","YUL","YOW"),("8203","YOW","YYZ")], delay=300, code="62", msl=1, label="INVOL->VOL(-ve) MANY_TO_MANY"),
    dict(n=6,  pax=P("LAURENT GOSSELIN"), aero=False, legs=[("301","YUL","YYZ")], prom=None, delay=240, code="96", msl=0, label="Standard INVOL"),
    dict(n=7,  pax=P("SIMON LACROIX"), aero=False, legs=[("301","YUL","YYZ")], prom=None, delay=240, code="36", msl=0, label="SELFREACC (=INVOL)"),
    dict(n=8,  pax=P("OLIVIER MENARD"), aero=False, legs=[("301","YUL","YYZ")], prom=None, delay=300, code="32", msl=0, label="Double INVOL 5h"),
    dict(n=9,  pax=P("NADIA FORTIN"), aero=False, legs=[("301","YUL","YYZ")], prom=None, delay=270, code="37", msl=0, label="DT Schedule Change 4.5h"),
    dict(n=10, pax=P("ISABELLE TREMBLAY"), aero=False, legs=[("301","YUL","YYZ")], prom=None, delay=270, code="61", msl=0, label="React Auto-Rebook 4.5h"),
    dict(n=11, pax=P("CATHERINE BOUCHARD","MARC BOUCHARD","SOPHIE BOUCHARD"), aero=False, legs=[("301","YUL","YYZ")], prom=None, delay=240, code="56", msl=0, claim_pax=3, label="3 Pax all eligible ($1200)"),
    dict(n=12, pax=P("JEAN-PIERRE MARTIN")+[("GROUP",f"MEMBER{i:02d}") for i in range(2,13)], aero=False, legs=[("301","YUL","YYZ")], prom=None, delay=240, code="19", msl=0, group=True, label="Group Booking (claim self only)"),
    dict(n=13, pax=P("MICHEL GAGNON"), aero=False, legs=[("301","YUL","YYZ")], prom=None, delay=240, code="25", msl=0, label="CyberSource GREEN"),
    dict(n=14, pax=P("FRANCOIS PELLETIER"), aero=False, legs=[("301","YUL","YYZ")], prom=None, delay=240, code="64", msl=0, label="CyberSource YELLOW (held)"),
    dict(n=15, pax=P("ALAIN MOREAU"), aero=False, legs=[("301","YUL","YYZ")], prom=None, delay=240, code="13", msl=0, label="CyberSource RED (reject+dispute)"),
    dict(n=16, pax=P("DIANE LEFEBVRE"), aero=False, legs=[("301","YUL","YYZ")], prom=None, delay=240, code="14", msl=0, label="RDS override (manual review)"),
    dict(n=17, pax=P("MATHIEU ROY"), aero=False, legs=[("301","YUL","YYZ")], prom=None, delay=240, code="64", msl=0, label="Welcome Back (resolved EL)"),
    dict(n=18, pax=P("JULIEN BERGERON"), aero=False, legs=[("301","YUL","YYZ")], prom=None, delay=420, code="14", msl=0, label="Delay 6-<9h Cash ($700)"),
    dict(n=19, pax=P("PIERRE LAVIGNE"), aero=True, legs=[("301","YUL","YYZ")], prom=None, delay=420, code="11", msl=0, label="Delay 6-<9h AC Wallet ($840)"),
    dict(n=20, pax=P("LUCAS GIRARD"), aero=False, legs=[("301","YUL","YYZ")], prom=None, delay=420, code="67", msl=0, label="VOL->VOL->INVOL 7h ($700)"),
    dict(n=21, pax=P("ANTOINE CARON"), aero=False, legs=[("301","YUL","YYZ")], prom=None, delay=600, code="15", msl=0, label="Delay 9+h Cash ($1000)"),
    dict(n=22, pax=P("SYLVIE ROY"), aero=True, legs=[("301","YUL","YYZ")], prom=None, delay=600, code="15", msl=0, label="Delay 9+h AC Wallet ($1200)"),
    dict(n=23, pax=P("PAUL LEMIEUX"), aero=False, legs=[("436","YUL","YHM")], prom=[("435","YUL","YYZ")], delay=240, code="31", msl=0, sister=True, label="Sister City 3-<6h ($400)"),
    dict(n=24, pax=P("CHANTAL DUBE"), aero=False, legs=[("436","YUL","YHM")], prom=[("435","YUL","YYZ")], delay=420, code="31", msl=0, sister=True, label="Sister City 6-<9h ($700)"),
    dict(n=25, pax=P("LUC BERGERON"), aero=False, legs=[("438","YUL","YHM")], prom=[("437","YUL","YYZ")], delay=600, code="18", msl=0, sister=True, label="Sister City 9+h ($1000)"),
    dict(n=26, pax=P("ROBERT CLOUTIER"), aero=False, legs=[("301","YUL","YYZ")], prom=None, delay=240, code="64", msl=0, fallback=True, label="Fallback code 3-<6h ($400)"),
    dict(n=27, pax=P("MANON BELANGER"), aero=False, legs=[("301","YUL","YYZ")], prom=None, delay=420, code="42", msl=0, fallback=True, label="Fallback code 6-<9h ($700)"),
    dict(n=28, pax=P("YVES TREMBLAY"), aero=False, legs=[("301","YUL","YYZ")], prom=None, delay=600, code="67", msl=0, fallback=True, label="Fallback code 9+h ($1000)"),
    dict(n=29, pax=P("JULIEN MOREAU"), aero=False, legs=[("442","YUL","YHM")], prom=[("442","YUL","YYZ")], delay=300, code="64", msl=0, sister=True, fallback=True, label="Sister City + Fallback 5h ($400)"),
    dict(n=30, pax=P("MARC-ANDRE LAVOIE"), aero=False, legs=[("443","YUL","YHM")], prom=[("442","YUL","YYZ")], delay=420, code="42", msl=0, sister=True, fallback=True, label="Sister City + Fallback 7h ($700)"),
]


def tier(d):
    if d >= 540: return 1000, "FD-APPR-EL-1000", "DELAY_9_HOURS_OR_MORE"
    if d >= 360: return 700, "FD-APPR-EL-700", "DELAY_6_TO_LT_9_HOURS"
    return 400, "FD-APPR-EL-400", "DELAY_3_TO_LT_6_HOURS"


def hhmm(base_h, add_min=0):
    dt = datetime.fromisoformat(f"{DATE}T{base_h:02d}:00:00") + timedelta(minutes=add_min)
    return dt


def build(tc, loc):
    pnr_id = f"{loc}-{DATE}"
    legs = tc["legs"]
    prom = tc["prom"] or legs
    amount, syscode, band = tier(tc["delay"])
    # --- booking scenario ---
    segs = []
    for i, (fn, org, dst) in enumerate(legs):
        dep = hhmm(10 + 2 * i); arr = hhmm(12 + 2 * i)
        segs.append({
            "carrier": "AC", "operating_carrier": "AC", "flight_number": fn, "operating_flight_number": fn,
            "origin": org, "destination": dst,
            "dep_local": dep.strftime("%Y-%m-%dT%H:%M:%S"), "arr_local": arr.strftime("%Y-%m-%dT%H:%M:%S"),
            "dep_utc": (dep + timedelta(hours=4)).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "arr_utc": (arr + timedelta(hours=4)).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "booking_datetime": None, "aircraft": "320", "cabin": "Y", "status": "HK", "arrival_terminal": "1",
        })
    passengers = []
    for i, (fn, ln) in enumerate(tc["pax"], 1):
        pax = {"type": "ADT", "first_name": fn, "last_name": ln, "gender": "U", "date_of_birth": DOB,
               "email": MAIL, "phone": f"+1416555{1000+tc['n']:04d}"}
        if tc.get("aero") and i == 1:
            pax["aeroplan"] = "9876543210"
        passengers.append(pax)
    tickets = [f"014240{tc['n']:02d}0{i}001" for i in range(1, 2)]  # one ticket (claimant PT-1)
    scen = {
        "$schema_version": 2, "scenario_id": pnr_id,
        "title": f"FD_TC_{tc['n']:03d}: APPR {tc['label']} - {tc['pax'][0][0]} {tc['pax'][0][1]} [{loc}]",
        "description": f"FD_TC_{tc['n']:03d} | APPR ELIGIBLE | {tc['label']} | delay {tc['delay']}m code {tc['code']} | CAD {amount}",
        "canvas": "_canvas/pnr_creation_domestic_ac.json", "contains_pii": False,
        "identity": {"pnr": loc, "booking_date": DATE, "type": "PNR"},
        "point_of_sale": {"office_id": OFFICE, "iata_number": "01424012", "system_code": "1A",
                          "agent_type": "AIRLINE", "agent_numeric_sign": "0001", "agent_initials": "FD",
                          "duty_code": "SU", "agent_country": "CA", "agent_city": "YUL"},
        "last_modification_comment": f"SIM-FD-TC-{tc['n']:03d}-INT", "creation_comment": f"SIM-FD-TC-{tc['n']:03d}-INT",
        "passengers": passengers, "segments": segs,
        "ticketing": {"issuance_local_date": ISSUE, "fare": {"amount": "350.00", "currency": "CAD"},
                      "ticket_numbers": tickets},
        "timeline": [{"version": 0, "at": f"{ISSUE}T10:00:00Z", "action": "bootstrap", "description": "Pre-ticketing stub"},
                     {"version": 1, "at": f"{ISSUE}T10:00:01Z", "action": "ticketing_added", "description": "Ticketing reference attached"}],
        "expected_cascade": {"db_end_state": {"trip": {"rows": 1, "status": "ACTIVE", "pnr": loc, "pnr_id": pnr_id},
                                              "passenger": {"rows": len(passengers)}, "flight_segment": {"rows": len(segs)}},
                             "total_cascade_budget_ms": 30000},
        "classification": {"primary_code": f"FD-TC-{tc['n']:03d}", "primary_name": f"Flight Disruption FD_TC_{tc['n']:03d} INT", "confidence": "high"},
        "tags": ["synthetic", f"fd-tc-{tc['n']:03d}", "appr", "eligible", f"code-{tc['code']}", f"cad-{amount}"]
                + (["sister-city"] if tc.get("sister") else []) + (["fallback"] if tc.get("fallback") else [])
                + (["group"] if tc.get("group") else []) + (["multi-pax"] if tc.get("claim_pax", 1) > 1 else []),
    }

    # --- DDS response.json ---
    def dds_segs(seglist):
        out = []
        for i, (fn, org, dst) in enumerate(seglist, 1):
            dep = hhmm(10 + 2 * (i - 1)); arr = hhmm(12 + 2 * (i - 1))
            out.append({"segmentId": f"{pnr_id}-ST-{i}", "segmentStatus": "HK",
                        "departureDatetime": dep.strftime("%Y-%m-%dT%H:%M:00+00:00"),
                        "arrivalDatetime": arr.strftime("%Y-%m-%dT%H:%M:00+00:00"),
                        "departureAirport": org, "arrivalAirport": dst,
                        "marketingFlightNumber": int(fn), "marketingCarrierCode": "AC",
                        "operatingFlightNumber": int(fn), "operatingCarrierCode": "AC",
                        "flightId": f"AC#{fn}#{DATE}#{org}"})
        return out

    mfn, morg, mdst = legs[tc["msl"]]
    claim_pax = tc.get("claim_pax", 1)
    pe = [{"passengerId": f"{pnr_id}-PT-{i}", "passengerType": "ADT", "eligibilityStatus": "ELIGIBLE",
           "systemCode": syscode, "reason": "arrival delay within carrier control",
           "compensationDetails": {"amount": amount, "currency": "CAD", "delayBand": band, "expiryDate": "2027-06-15"}}
          for i in range(1, claim_pax + 1)]

    def regime(name, eligible):
        if eligible:
            return {"regime": name, "boundRph": 1,
                    "mslFlight": {"segmentId": f"{pnr_id}-ST-{tc['msl']+1}", "carrierCode": "AC", "flightNumber": mfn,
                                  "departureAirport": morg, "arrivalAirport": mdst, "isStarSegment": False, "isOalSegment": False},
                    "disruptionType": "INVOLUNTARY", "delayMinutes": tc["delay"], "delayType": "CONTROLLABLE",
                    "delayCode": tc["code"], "customerFriendlyDisruptionReason": reason_text(),
                    "disruptionReason": "MECHANICAL", "passengerEligibility": pe}
        return {"regime": name, "boundRph": 1,
                "passengerEligibility": [{"passengerId": f"{pnr_id}-PT-1", "passengerType": "ADT",
                                          "eligibilityStatus": "NOT_ELIGIBLE", "systemCode": f"FD-{name}-NA-01",
                                          "compensationDetails": {"amount": 0, "currency": "CAD", "delayBand": "NOT_APPLICABLE"}}]}

    dds = {
        "eventMetadata": {"trigger": "DISRUPTION_DETECTION_SERVICE", "timestamp": f"{DATE}T09:05:34.000Z"},
        "pnrIdentifier": {"pnrId": pnr_id, "pnr": loc},
        "itineraryDetails": [{"bound": 1, "boundRph": 1, "isOAL": False,
                              "promisedItinerary": {"origin": prom[0][1], "destination": prom[-1][2], "associatedSegments": dds_segs(prom)},
                              "actualItinerary": {"origin": legs[0][1], "destination": legs[-1][2], "associatedSegments": dds_segs(legs)}}],
        "compensationEligibility": [regime("APPR", True), regime("EU", False), regime("ASL", False)],
        "socFlightEligibility": [{"regime": "APPR", "boundRph": 1, "segmentId": f"{pnr_id}-ST-{tc['msl']+1}",
                                  "carrierCode": "AC", "flightNumber": int(mfn), "departureAirport": morg, "arrivalAirport": mdst,
                                  "segmentStatus": "HK", "disruptionType": "INVOLUNTARY", "delayType": "OTHER", "delayCode": "",
                                  "disruptionReason": "", "customerFriendlyDisruptionReason": "", "delayMinutes": 0,
                                  "delayCategory": "DELAY_LT_2_HOURS",
                                  "passengerEligibility": [{"passengerId": f"{pnr_id}-PT-1", "passengerType": "ADT",
                                                            "bookingClass": None, "cabinClass": "ECONOMY",
                                                            "eligibilityStatus": "NO_DETERMINATION", "systemCode": "SoC-APPR-ND-04",
                                                            "reason": "Data missing - 14 days", "expiryDate": "", "expenseCategories": []}]}],
        "seatFeeRefundEligibility": [],
    }
    return scen, dds, dict(loc=loc, pnr_id=pnr_id, tc=f"FD_TC_{tc['n']:03d}", pax=f"{tc['pax'][0][0]} {tc['pax'][0][1]}",
                           npax=len(passengers), route="-".join([legs[0][1]] + [s[2] for s in legs]),
                           delay=tc["delay"], code=tc["code"], amount=amount, syscode=syscode, band=band,
                           aero=tc.get("aero", False), label=tc["label"], ticket=tickets[0])


def main():
    DDS_DIR.mkdir(parents=True, exist_ok=True)
    rows = []
    for tc, loc in zip(TC30, LOCATORS):
        scen, dds, meta = build(tc, loc)
        (FD_SIT / f"{meta['pnr_id']}.json").write_text(json.dumps(scen, indent=2) + "\n")
        (DDS_DIR / f"{meta['pnr_id']}.dds.json").write_text(json.dumps(dds, indent=2) + "\n")
        rows.append(meta)
        print(f"  {meta['tc']} {meta['loc']} {meta['pax']:24} {meta['route']:14} {meta['delay']}m code {meta['code']:>2} CAD {meta['amount']}")
    (FD_SIT / "_FD_TC30_index.json").write_text(json.dumps(rows, indent=2) + "\n")
    print(f"\nWrote {len(rows)} scenarios + {len(rows)} DDS files; index -> _FD_TC30_index.json")


if __name__ == "__main__":
    main()
