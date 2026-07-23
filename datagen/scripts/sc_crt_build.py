#!/usr/bin/env python3
import os
"""Build SEAT CHANGE test PNRs in the CRT environment (67-case suite).

Source of truth for eligibility = the LIVE seat-change rule flow behind
  POST /eligibility-service/execute-with-mapping   (trigger SEAT_CHANGE,
  changeTrigger.selectedBound REQUIRED — that is the Journey Selection step).

Empirically probed on CRT 2026-07-08 (the repo copy of rules.json is STALE —
live has an 8th rule, ruleCheckinStatus / SC-NE-08, that the repo lacks):

  reason codes   SC-EL-01 eligible
                 SC-NE-01 carrier mix   (marketing OR operating not in AC/QK/RV)
                 SC-NE-02 booking source missing/empty
                 SC-NE-03 booking channel unsupported
                 SC-NE-04 ticket status  (stock != 014, or all coupons flown/void)
                 SC-NE-05 time window    (<24h to departure, or departed) -> OUT_OF_SCOPE
                 SC-NE-06 SSR blocked    (EXST / CBBG / SVAN / ESAN)
                 SC-NE-07 group PNR within 6h of departure
                 SC-NE-08 passenger checked in
  eligible srcs  AC_ONLINE ACO AC_MOBILE CONTACT_CENTRE AIRPORT NDC 1A_GDS GDS_1A
                 GROUP AEROPLAN AC_VACATIONS ACV ADO AGENCY_DIRECT_ONLINE
  NOT eligible   AIR_CANADA_ONLINE(!) ACO_WEB OTA EXPEDIA 1S GDS_NON_1A OTHER AC
                 EMPLOYEE_TRAVEL FLIGHT_PASS AC_CARGO REVENUE
  processing win VOID (booked <=24h ago, feeApplicable=false) | NON_VOID (feeApplicable=true)
  persist ssrs   WCHR MEDA DPNA OXYG MEQT  -> reported in passengerEligibility.specialSsrs
  isUmnr         UMNR ssr present          isYouth  passengerType == YTH

WHERE EACH INPUT LIVES (probed):
  booking_source  eds_pnr_output.booking_context ->  edsPnr[].bookingContext.bookingSource
                  (falls back to trip_details.source; 'AC' is mapped to 'ACO' by the SP router)
  carriers        flight_segment.marketing_carrier_code / operating_carrier_code
  time window     trip.created_at  +  flight_segment.departure_datetime (first seg of bound)
  ticket          ticket.primary_document_number (014 stock) + ticket.coupons[].status,
                  coupons correlated 1:1 to the bound's segments (else that bound -> SC-NE-04)
  ssr             special_service_request.code (+ passenger_id[])
  checked in      journey_updates event_type=CHECK_IN,
                  data.segment.legDeliveries[].acceptance.status == 'ACCEPTED'
  group           booking_source == 'GROUP' (only blocks when <6h to departure)

Phases (idempotent / resumable):
  index         -> _SC_crt_index.json   (fresh locators, unique pax names, ticket series)
  publish       render scenario -> publish booking to CRT PNR Kafka
  checkcascade  how many landed in trip-tracer
  finalize      ticket + DOB + pax types + SSR + CHECK_IN + booking_context + carrier/date patches
  redate        re-patch the time-boundary cases relative to NOW (they decay)
  verify        POST DB-derived payload to the eligibility endpoint, assert reason code

Usage: python3 sc_crt_build.py <phase> [--start N] [--end N]   (no AWS creds needed; WARP on)
"""
import json, os, sys, uuid, subprocess, ssl, urllib.request, urllib.error, argparse, random, datetime
import psycopg2
import _cctdb
from psycopg2.extras import Json
import crt_uniqnames as U

KB   = os.environ.get("CCTQA_DATAGEN_ROOT",
                      os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SENG   = f"{KB}/scripts/scenario_engine.py"
PUB    = f"{KB}/scripts/publish_raw.py"
CANVAS = f"{KB}/scenarios/_canvas/pnr_creation_domestic_ac.json"
WORK   = os.environ.get("SC_WORK", "/tmp/cctqa-datagen"
                        "c5c82706-b02a-4b25-9466-1d1841999e18/scratchpad/sc_work")
SCENW, NDJW = f"{WORK}/scenarios", f"{WORK}/ndjson"
for d in (SCENW, NDJW): os.makedirs(d, exist_ok=True)
OUT = os.environ.get("SC_OUT", f"{WORK}/_SC_crt_index.json")

CRT = dict(
    brokers=("b-1.accctmskcrtcac1.05hf7o.c4.kafka.ca-central-1.amazonaws.com:9092,"
             "b-2.accctmskcrtcac1.05hf7o.c4.kafka.ca-central-1.amazonaws.com:9092,"
             "b-3.accctmskcrtcac1.05hf7o.c4.kafka.ca-central-1.amazonaws.com:9092"),
    topic="emh-dev.ALTEA-PNRDATA-UAT",
    tt_host="ac-cct-trip-tracer-rds-cluster-crt-cac1.cluster-cxqe2wacy866.ca-central-1.rds.amazonaws.com",
    tt_db="trip-tracer", tt_user="dbadmin", tt_pass=os.environ.get("CCT_TRIPTRACER_PASSWORD", ""),
    endpoint="https://rule-engine-platform-service.ac-cct-crt.cloud.aircanada.com/eligibility-service/execute-with-mapping",
    api_key="6a1a7245-c87b-494f-b53a-e1c4277add62",
)
EMAIL   = os.environ.get("CRT_EMAIL", "lahiru@ae-qa1-aircanada.mailinator.com")
PHONE   = os.environ.get("CRT_PHONE", "+94712534323")
DOB_ADT = "1986-04-23"
TPREFIX = os.environ.get("SC_TPREFIX", "014303")   # fresh series (014302 = ANC set-2 / NC)
TBASE0  = int(os.environ.get("SC_TBASE", "1000000"))
SEED    = int(os.environ.get("SC_SEED", "670670"))
# Skip the first N (first,last) combos of the pool so a later set never reuses an earlier
# set's passenger names. set-1 consumed 90; set-2 uses SC_NAME_SKIP=90.
NAME_SKIP = int(os.environ.get("SC_NAME_SKIP", "0"))
CORRIDS = "qa-sc-crt"
# opt-in: assign DB-absent, set-unique passenger names (default OFF -> legacy pool names)
UNIQ = os.environ.get("CRT_UNIQ_NAMES") == "1"

def tt_conn():
    return _cctdb.trip_tracer(CRT["tt_host"], profile=CRT.get("profile"))

# ---- time anchors -----------------------------------------------------------
NOW = datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0)
def iso(dt): return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
CREATED = NOW - datetime.timedelta(days=10)          # NON_VOID window for everything but W_VOID
BOOK_DATE = CREATED.date().isoformat()

# departure specs -> timedelta from NOW.  Boundary cases are re-derived by `redate`.
DEPS = {
    "D5":     datetime.timedelta(days=5),            # default: comfortably >24h
    "D7":     datetime.timedelta(days=7),
    "D12":    datetime.timedelta(days=12),           # return bound of a round trip
    "H12":    datetime.timedelta(hours=12),          # within 24h  -> SC-NE-05
    "M45":    datetime.timedelta(minutes=45),        # <1h         -> SC-NE-05
    "H23M59": datetime.timedelta(hours=23, minutes=59, seconds=59),   # boundary -> SC-NE-05
    "PAST3":  datetime.timedelta(hours=-3),          # departed    -> SC-NE-05
    "H3":     datetime.timedelta(hours=3),           # group <6h   -> SC-NE-07 (+NE-05)
}
BOUNDARY = {"H12", "M45", "H23M59", "PAST3", "H3"}   # decay with wall-clock -> `redate`

# ---- unique passenger-name pool --------------------------------------------
FIRST = ["OLIVIA","LIAM","EMMA","NOAH","AVA","WILLIAM","SOPHIA","BENJAMIN","ISABELLA","LUCAS",
         "MIA","HENRY","CHARLOTTE","THEODORE","AMELIA","JACK","HARPER","OLIVER","EVELYN","JAMES",
         "ABIGAIL","ETHAN","EMILY","ALEXANDER","ELIZABETH","DANIEL","SOFIA","MATTHEW","VICTORIA","JOSEPH",
         "GRACE","SAMUEL","CHLOE","DAVID","PENELOPE","CARTER","LAYLA","OWEN","RILEY","GABRIEL",
         "NORA","JULIAN","HAZEL","LEO","AURORA","ISAAC","SAVANNAH","LINCOLN","BROOKLYN","ANTHONY"]
LAST  = ["ASHFORD","BRENNAC","CALDWYN","DRISCOL","EASTMER","FAIRHOL","GRENVIL","HALLOWE","IRONWOD","JARRECK",
         "KESTREL","LANGMER","MERIDEW","NORWOOD","OAKHURS","PENHALL","QUILLON","RAVENAL","STOWFOR","THORNBY",
         "UPTHORN","VANBROK","WESTMAR","YARDLEY","ZEBROWS","ALDERTN"]
def name_pool(skip=0):
    n = 0
    for ln in LAST:
        for fn in FIRST:
            n += 1
            if n <= skip: continue
            yield (fn, ln)

# ---- case table -------------------------------------------------------------
# seg: (op, mkt, bound, origin, dest, dep_spec)
AC1  = [("AC","AC",1,"YYZ","CDG","D5")]
def ac1(dep): return [("AC","AC",1,"YYZ","CDG",dep)]
MLEG = [("AC","AC",1,"YYZ","YUL","D5"), ("AC","AC",1,"YUL","CDG","D5")]          # connecting, one bound
MLEG_OAL = [("AC","AC",1,"YYZ","YUL","D5"), ("LH","AC",1,"YUL","CDG","D5")]      # leg2 LH-operated
RT   = [("AC","AC",1,"YYZ","CDG","D5"), ("AC","AC",2,"CDG","YYZ","D12")]         # round trip, 2 bounds

def pax(n=1, types=None, ssrs=None, dobs=None):
    """types/ssrs/dobs indexed per passenger."""
    types = types or ["ADT"] * n
    ssrs  = ssrs  or [[] for _ in range(n)]
    dobs  = dobs  or [None] * n
    return [dict(ptype=types[i], ssr=ssrs[i], dob=dobs[i]) for i in range(n)]

CH_DOB  = (NOW - datetime.timedelta(days=int(365.25 * 5))).date().isoformat()    # age 5
CH10    = (NOW - datetime.timedelta(days=int(365.25 * 10))).date().isoformat()   # age 10
CH7     = (NOW - datetime.timedelta(days=int(365.25 * 7))).date().isoformat()
CH4     = (NOW - datetime.timedelta(days=int(365.25 * 4))).date().isoformat()
TEEN14  = (NOW - datetime.timedelta(days=int(365.25 * 14))).date().isoformat()
INF_DOB = (NOW - datetime.timedelta(days=240)).date().isoformat()                # ~8 months
INF6M   = (NOW - datetime.timedelta(days=185)).date().isoformat()

EL = ("SC-EL-01", True, "NON_VOID")
def NE(code, win="NON_VOID"): return (code, False, win)

def C(tc, pri, feat, name, segs=None, paxs=None, src="AC_ONLINE", exp=EL, bound=1,
      checkin=False, seats=None, chatbot="", runtime="", void=False, seed_pnr=True, divergence=""):
    return dict(tc=tc, pri=pri, feat=feat, name=name, segs=segs or AC1, paxs=paxs or pax(1),
                src=src, exp_reason=exp[0], exp_elig=exp[1], exp_win=exp[2], bound=bound,
                checkin=checkin, seats=seats or {}, chatbot=chatbot, runtime=runtime, void=void,
                seed_pnr=seed_pnr, divergence=divergence)

CASES = [
 # ---------------- Happy Path (19) ----------------
 C("SeatChange_TC001","P2","Happy Path","Single-pax single-leg seat change via web + credit card",
   seats={0:"22C"}, chatbot="SC-01b -> seat map -> SC-03 -> SC-03a"),
 C("SeatChange_TC002","P2","Happy Path","Single-pax single-leg via text channel (conversational search)",
   seats={0:"22C"}, runtime="text channel: 'I'd like a window seat' -> best-fit result"),
 C("SeatChange_TC003","P1","Happy Path","Single-pax multi-leg seat change on both legs", segs=MLEG,
   seats={0:"22C"}, chatbot="seat map shows Leg1/Leg2 tabs + 'Next Flights'"),
 C("SeatChange_TC004","P1","Happy Path","Two-passenger PNR, seats changed for both", paxs=pax(2),
   seats={0:"22C",1:"22D"}, chatbot="multi-pax Note 1: seat map opens directly"),
 C("SeatChange_TC005","P1","Happy Path","Multi-journey PNR — user selects RETURN journey", segs=RT,
   bound=2, seats={0:"22C"}, chatbot="GenUC-08 journey selection -> selectedBound=2"),
 C("SeatChange_TC006","P2","Happy Path","Free seat change (Standard->Standard, $0.00, no payment step)",
   seats={0:"22B"}, runtime="widget prices standard seat at CA $0.00 -> payment skipped"),
 C("SeatChange_TC007","P2","Happy Path","Seat change paid with acWallet", seats={0:"22C"},
   runtime="acWallet balance CA $100 / fee CA $34"),
 C("SeatChange_TC008","P2","Happy Path","Seat change paid with FlexPay (amount > $99)", seats={0:"22C"},
   runtime="premium seat CA $150 -> FlexPay offered"),
 C("SeatChange_TC009","P1","Happy Path","Already-authenticated user skips OTP", seats={0:"22C"},
   runtime="active session -> GenUC-05 bypassed"),
 C("SeatChange_TC010","P2","Happy Path","Identification by ticket number instead of PNR", seats={0:"22C"},
   chatbot="GenUC-01 accepts the 014 ticket number (see Ticket column)"),
 C("SeatChange_TC011","P2","Happy Path","Declines payment, re-selects a different seat, pays", seats={0:"22C"},
   runtime="SC-03 No -> SC-03b Yes -> seat map"),
 C("SeatChange_TC012","P2","Happy Path","Declines payment and abandons", seats={0:"22C"},
   runtime="SC-03 No -> SC-03b No -> End"),
 # ---------------- Eligibility Block (12) ----------------
 C("SeatChange_TC013","P1","Eligibility Block","Blocked at ACV booking source", src="AC_VACATIONS",
   exp=EL, chatbot="Miro: ACV -> live agent",
   divergence="Live rule flow accepts AC_VACATIONS as an ELIGIBLE channel (SC-EL-01). The ACV block is a "
              "chatbot/identification-layer decision, not an eligibility-service one."),
 C("SeatChange_TC014","P1","Eligibility Block","Blocked at OTA booking source", src="OTA",
   exp=NE("SC-NE-03"), chatbot="ruleBookingChannel=fail -> 'contact your booking source'"),
 C("SeatChange_TC015","P2","Eligibility Block","Blocked because passenger is checked in", checkin=True,
   exp=NE("SC-NE-08"), chatbot="SC-01a checked-in -> My Bookings / SSCI"),
 C("SeatChange_TC016","P2","Eligibility Block","Blocked because PNR is a group booking", src="GROUP",
   exp=EL, chatbot="Miro: group -> 'contact your booking source'",
   divergence="Live rule flow treats GROUP as an ELIGIBLE channel; ruleGroupPnr only fails when the flight "
              "is <6h away (SC-NE-07). A >6h group PNR returns SC-EL-01."),
 C("SeatChange_TC017","P1","Eligibility Block","Blocked — flight operated by non-AC carrier (LH)",
   segs=[("LH","AC",1,"YYZ","FRA","D5")], exp=NE("SC-NE-01"), chatbot="ruleCarrierMix=fail"),
 C("SeatChange_TC018","P2","Eligibility Block","Blocked by EXST SSR", paxs=pax(1, ssrs=[["EXST"]]),
   exp=NE("SC-NE-06"), chatbot="ruleSsrRestriction=fail -> 'contact Accessibility Services'"),
 C("SeatChange_TC019","P2","Eligibility Block","Blocked by PETC SSR", paxs=pax(1, ssrs=[["PETC"]]),
   exp=EL, chatbot="Miro: PETC blocks",
   divergence="PETC is NOT in the live sc_blocking_ssr lookup (EXST/CBBG/SVAN/ESAN only) -> SC-EL-01."),
 C("SeatChange_TC020","P1","Eligibility Block","Blocked — flight departs in <1 hour", segs=ac1("M45"),
   exp=NE("SC-NE-05","OUT_OF_SCOPE"), chatbot="ruleTimeWindow=fail; 'last-minute changes not permitted'"),
 C("SeatChange_TC021","P2","Eligibility Block","Redirected — flight within 24 hours", segs=ac1("H12"),
   exp=NE("SC-NE-05","OUT_OF_SCOPE"), chatbot="within-24h -> check-in redirect"),
 C("SeatChange_TC022","P2","Eligibility Block","Blocked by confirmed eUpgrade", paxs=pax(1, ssrs=[["EUPG"]]),
   exp=EL, chatbot="Miro: confirmed eUpgrade blocks",
   divergence="EUPG is not an input to any live seat-change rule -> SC-EL-01. eUpgrade must be enforced "
              "in the Seat Change Widget."),
 C("SeatChange_TC023","P1","Eligibility Block","Blocked — flight already departed", segs=ac1("PAST3"),
   exp=NE("SC-NE-05","OUT_OF_SCOPE"), chatbot="departed -> OUT_OF_SCOPE"),
 C("SeatChange_TC024","P2","Eligibility Block","Multi-leg: leg1 AC eligible, leg2 LH ineligible",
   segs=MLEG_OAL, exp=NE("SC-NE-01"), chatbot="bound NE; segmentsEligibility[0]=EL, [1]=SC-NE-01"),
 # ---------------- ID Failure (4) ----------------
 C("SeatChange_TC025","P2","ID Failure","Invalid PNR — 4 failed identification attempts", seed_pnr=False,
   runtime="tester types the RESERVED locator (see report); it must NOT exist in trip-tracer"),
 C("SeatChange_TC026","P2","ID Failure","Correct PNR, completely wrong name (Levenshtein fail)",
   runtime="tester enters a wrong surname against the seeded PNR"),
 C("SeatChange_TC027","P2","ID Failure","Third-party (OTA) booking -> MANUAL_HANDLING", src="OTA",
   exp=NE("SC-NE-03"), chatbot="identification detects OTA -> manual handling"),
 C("SeatChange_TC030","P2","ID Failure","Empty last name rejected at GenUC-01",
   runtime="tester submits an empty last name"),
 # ---------------- Auth Failure (2) ----------------
 C("SeatChange_TC028","P1","Auth Failure","All OTP + IDV attempts exhausted",
   runtime="15 wrong OTP + 3 wrong IDV against the seeded contact"),
 C("SeatChange_TC029","P1","Auth Failure","OTP expires after 5 minutes",
   runtime="wait >5 min before submitting the OTP"),
 # ---------------- Seat Map (5) ----------------
 C("SeatChange_TC031","P1","Seat Map","Seat map reached but flight is 100% full", seats={0:"22C"},
   runtime="ENVIRONMENTAL: seat inventory comes from the live Seat Change Widget, not the PNR"),
 C("SeatChange_TC032","P1","Seat Map","Selected seat taken by another user before confirm", seats={0:"22C"},
   runtime="ENVIRONMENTAL: concurrent seat grab"),
 C("SeatChange_TC033","P2","Seat Map","Text channel: 3 failed searches -> My Bookings link", seats={0:"22C"},
   runtime="text channel, 3 no-match preference searches"),
 C("SeatChange_TC034","P2","Seat Map","User selects their already-assigned seat", seats={0:"14A"},
   chatbot="current seat 14A is seeded as an RQST SSR"),
 C("SeatChange_TC035","P2","Seat Map","Economy pax tries to select a Business seat", seats={0:"22C"},
   runtime="cabin Y booked; widget blocks J seats"),
 # ---------------- Payment (4) ----------------
 C("SeatChange_TC036","P2","Payment","Payment rejected — expired credit card", seats={0:"22C"},
   runtime="ENVIRONMENTAL: expired card 01/2025"),
 C("SeatChange_TC037","P2","Payment","FlexPay not offered below $99", seats={0:"22C"},
   runtime="total CA $50"),
 C("SeatChange_TC038","P1","Payment","Network drop mid-payment — idempotency prevents double charge",
   seats={0:"22C"}, runtime="ENVIRONMENTAL"),
 C("SeatChange_TC039","P1","Payment","Split payment attempt blocked", seats={0:"22C"}, runtime="ENVIRONMENTAL"),
 # ---------------- Passenger Rules (8) ----------------
 C("SeatChange_TC040","P2","Passenger Rules","Child under 12 blocked from exit row",
   paxs=pax(2, ["ADT","CHD"], [[], ["CHLD"]], [None, CH_DOB]), seats={0:"14A"},
   chatbot="adult on 14A + child age 5 (DOB seeded)"),
 C("SeatChange_TC041","P2","Passenger Rules","Child under 12 cannot sit in a far row from the adult",
   paxs=pax(2, ["ADT","CHD"], [[], ["CHLD"]], [None, CH_DOB]), seats={0:"14A"},
   runtime="widget proximity logic; seat 30F far from row 14"),
 C("SeatChange_TC042","P2","Passenger Rules","Lap infant blocks the adult from an exit row",
   paxs=pax(2, ["ADT","INF"], [["INFT"], []], [None, INF_DOB]), seats={0:"14A"},
   chatbot="has_infant=true on the adult"),
 C("SeatChange_TC043","P2","Passenger Rules","Unaccompanied Minor blocked from restricted seats",
   paxs=pax(1, ["CHD"], [["UMNR"]], [CH10]), seats={0:"25B"},
   chatbot="passengerEligibility.isUmnr=true (still SC-EL-01)"),
 C("SeatChange_TC044","P2","Passenger Rules","Multi-child PNR proximity across 2 adults + 2 children",
   paxs=pax(4, ["ADT","ADT","CHD","CHD"], [[],[],["CHLD"],["CHLD"]], [None,None,CH7,CH4]), seats={0:"14A"}),
 C("SeatChange_TC045","P2","Passenger Rules","Passenger aged 14 fails the exit-row age requirement",
   paxs=pax(2, ["ADT","YTH"], [[],[]], [None, TEEN14]), seats={0:"10A"},
   chatbot="passengerEligibility.isYouth=true for the YTH pax"),
 C("SeatChange_TC046","P2","Passenger Rules","Preferred -> Standard downgrade, no refund", seats={0:"5A"},
   runtime="current paid Preferred seat 5A seeded; widget shows no-refund alert"),
 C("SeatChange_TC047","P1","Passenger Rules","Bassinet seat allowed because an infant is present",
   paxs=pax(2, ["ADT","INF"], [["INFT","BSCT"], []], [None, INF6M]), seats={0:"11A"}),
 # ---------------- Disruption (1) ----------------
 C("SeatChange_TC048","P2","Disruption","Disrupted ACV booking -> ACV live agent", src="AC_VACATIONS",
   exp=EL, runtime="ENVIRONMENTAL: disruption raised by FDM, not seedable on the PNR",
   divergence="AC_VACATIONS is an eligible channel for the rule flow; the ACV/LAH transfer is chatbot-side."),
 # ---------------- Happy Path (continued) ----------------
 C("SeatChange_TC049","P2","Happy Path","Seat ADD — booking has no pre-assigned seat", seats={},
   chatbot="no RQST SSR seeded -> 'change/add your seat(s)'"),
 C("SeatChange_TC050","P2","Happy Path","Seat change paid with a gift card", seats={0:"22C"},
   runtime="AC gift card with sufficient balance"),
 C("SeatChange_TC051","P2","Happy Path","Wrong OTP then correct OTP on retry", seats={0:"22C"},
   runtime="1 wrong OTP then the correct one"),
 C("SeatChange_TC052","P2","Happy Path","OTP resend then successful authentication", seats={0:"22C"},
   runtime="request resend, use the new code"),
 C("SeatChange_TC053","P2","Happy Path","4-passenger PNR, all seats changed at once", paxs=pax(4),
   seats={0:"22A",1:"22B",2:"22C",3:"22D"}),
 C("SeatChange_TC054","P2","Happy Path","3-pax PNR, only one passenger's seat changed", paxs=pax(3),
   seats={0:"22A",1:"22B",2:"22C"}),
 # ---------------- Edge Cases (12) ----------------
 C("SeatChange_TC055","P3","Edge – Concurrency","Two browser tabs, only one seat change succeeds",
   seats={0:"22C"}, runtime="ENVIRONMENTAL"),
 C("SeatChange_TC056","P3","Edge – Concurrency","Chatbot + call-centre edit the same PNR", seats={0:"22C"},
   runtime="ENVIRONMENTAL"),
 C("SeatChange_TC057","P3","Edge – Time Boundary","Flight at exactly 23h59m59s -> within-24h redirect",
   segs=ac1("H23M59"), exp=NE("SC-NE-05","OUT_OF_SCOPE"), chatbot="boundary confirmed live: 23:59:59 -> "
   "OUT_OF_SCOPE, 24:05 -> NON_VOID"),
 C("SeatChange_TC058","P3","Edge – Session","Session timeout while on the seat map", seats={0:"22C"},
   runtime="ENVIRONMENTAL"),
 C("SeatChange_TC059","P3","Edge – Aircraft","Aircraft swap invalidates the assigned seat", seats={0:"14A"},
   runtime="ENVIRONMENTAL: A320 -> CRJ-200 swap is a flight-level event"),
 C("SeatChange_TC060","P3","Edge – Mid-flow","Flight cancelled by the airline during the flow",
   seats={0:"22C"}, runtime="ENVIRONMENTAL"),
 C("SeatChange_TC061","P3","Edge – Mid-flow","Passenger checks in on another channel mid-flow",
   seats={0:"22C"}, runtime="starts NOT checked in (no CHECK_IN row); tester checks in via app mid-flow. "
   "Pair with TC015's PNR to see the SC-NE-08 end state."),
 C("SeatChange_TC062","P3","Edge – Max Passengers","9-passenger PNR", paxs=pax(9),
   seats={i: f"2{i}A" for i in range(0)}, chatbot="SC-03 shows 9 line items + combined total"),
 C("SeatChange_TC063","P3","Edge – Infant","Lap infant needs no separate seat",
   paxs=pax(2, ["ADT","INF"], [["INFT"], []], [None, INF_DOB]), seats={0:"22C"},
   chatbot="infant has no ticket coupon of its own; has_infant=true on the adult"),
 C("SeatChange_TC064","P3","Edge – Codeshare","Codeshare: marketing LH, operating AC",
   segs=[("AC","LH",1,"YYZ","FRA","D7")], exp=NE("SC-NE-01"),
   divergence="Test case expects eligibility to look only at the OPERATING carrier. The live rule checks "
              "BOTH marketing and operating (elig-sc-carrier-validation) -> SC-NE-01."),
 C("SeatChange_TC065","P3","Edge – Browser Nav","Browser back button on the payment screen", seats={0:"22C"},
   runtime="ENVIRONMENTAL"),
 C("SeatChange_TC066","P3","Edge – Network","Session restored after a network drop on the seat map",
   seats={0:"14A"}, runtime="ENVIRONMENTAL"),
 C("SeatChange_TC067","P2","Happy Path","Insufficient acWallet balance", seats={0:"22C"},
   runtime="acWallet balance below the seat fee -> fallback payment"),
]
assert len(CASES) == 67, len(CASES)

# ---- index ------------------------------------------------------------------
def all_taken(conn):
    cur = conn.cursor(); cur.execute("select distinct pnr from trip"); return {r[0] for r in cur.fetchall()}

def build_index():
    rnd = random.Random(SEED)
    conn = tt_conn(); taken = all_taken(conn); conn.close()
    A = "ABCDEFGHIJKLMNPQRSTUVWXYZ23456789"
    locs = []
    while len(locs) < len(CASES) + 1:                 # +1 reserved, never-seeded locator (TC025)
        L = "".join(rnd.choice(A) for _ in range(6))
        if L not in taken and L not in locs: locs.append(L)
    pool = name_pool(NAME_SKIP)
    recs, tb = [], TBASE0
    for i, c in enumerate(CASES):
        loc = locs[i]
        pid = f"{loc}-{BOOK_DATE}"
        paxs = []
        for k, p in enumerate(c["paxs"]):
            fn, ln = next(pool)
            paxs.append(dict(first=fn, last=ln, ptype=p["ptype"], ssr=p["ssr"],
                             dob=p["dob"] or DOB_ADT))
        # EVERY passenger (lap infants included) carries their own 014 document — verified against
        # live CRT data, and required: ruleTicketStatus is per-passenger, and a bound is only
        # eligible when EVERY passenger on it passes (an infant with no ticket -> bound SC-NE-04).
        tickets = {}
        for k in range(len(paxs)):
            tickets[k] = f"{TPREFIX}{tb:07d}"; tb += 10
        segs = [dict(op=s[0], mkt=s[1], bound=s[2], o=s[3], d=s[4], dep=s[5],
                     dep_iso=iso(NOW + DEPS[s[5]])) for s in c["segs"]]
        recs.append(dict(tc=c["tc"], pri=c["pri"], feat=c["feat"], name=c["name"], pnr=loc, pnr_id=pid,
                         booking_date=BOOK_DATE, created=iso(CREATED), segs=segs, paxs=paxs, npax=len(paxs),
                         tickets=tickets, src=c["src"], bound=c["bound"], checkin=c["checkin"],
                         seats={str(k): v for k, v in c["seats"].items()},
                         exp_reason=c["exp_reason"], exp_elig=c["exp_elig"], exp_win=c["exp_win"],
                         chatbot=c["chatbot"], runtime=c["runtime"], divergence=c["divergence"],
                         seed_pnr=c["seed_pnr"], email=EMAIL, phone=PHONE,
                         boundary=any(s["dep"] in BOUNDARY for s in segs)))
    recs[[r["tc"] for r in recs].index("SeatChange_TC025")]["pnr"] = locs[-1]   # reserved, unseeded
    recs[[r["tc"] for r in recs].index("SeatChange_TC025")]["pnr_id"] = f"{locs[-1]}-{BOOK_DATE}"
    if UNIQ:                                          # opt-in unique, DB-absent passenger names
        uconn = tt_conn()
        U.assign_names(recs, lambda r: r["npax"], uconn, seed=SEED)
        uconn.close()
        for r in recs:                               # write assigned names back into paxs
            for k, nm in enumerate(r.get("pax_names", [])):
                r["paxs"][k]["first"], r["paxs"][k]["last"] = nm
    json.dump(recs, open(OUT, "w"), indent=1)
    seeded = sum(1 for r in recs if r["seed_pnr"])
    print(f"[index] {len(recs)} cases -> {OUT}   ({seeded} seeded, 1 reserved-unseeded)")
    return recs

def load_index(): return json.load(open(OUT))
def seeded(recs): return [r for r in recs if r["seed_pnr"]]

# ---- scenario + publish -----------------------------------------------------
def px_type(t): return {"ADT":"ADT","CHD":"CHD","INF":"INF","YTH":"CHD"}.get(t, "ADT")

def _scn_tickets(r):
    tk = tickets_of(r); out = []; last = None
    for k in range(r["npax"]):
        last = tk.get(k, last)
        out.append(last)
    return out

def make_scenario(r):
    pax_entries = [dict(type=px_type(p["ptype"]), first_name=p["first"], last_name=p["last"], gender="U",
                        date_of_birth=p["dob"], email=r["email"], phone=r["phone"]) for p in r["paxs"]]
    segs = []
    for j, s in enumerate(r["segs"]):
        dep = s["dep_iso"]
        arr = iso(datetime.datetime.strptime(dep, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=datetime.timezone.utc)
                  + datetime.timedelta(hours=7))
        segs.append(dict(carrier="AC", operating_carrier="AC",          # OAL patched post-cascade
                         flight_number=str(870 + j), operating_flight_number=str(870 + j),
                         origin=s["o"], destination=s["d"], bound=s["bound"],
                         dep_local=dep, arr_local=arr, dep_utc=dep, arr_utc=arr,
                         booking_datetime=r["created"], aircraft="320", cabin="Y", status="HK"))
    scn = dict(**{"$schema_version": 2}, scenario_id=r["pnr_id"], title=f"{r['tc']}: {r['name']} [{r['pnr']}]",
               description=r["name"], canvas="_canvas/pnr_creation_domestic_ac.json", contains_pii=False,
               identity=dict(pnr=r["pnr"], booking_date=r["booking_date"], type="PNR"),
               point_of_sale=dict(office_id="YTOAA08AA", iata_number="01424012", system_code="AC",
                                  agent_type="AIRLINE", agent_numeric_sign="0001", agent_initials="SC",
                                  duty_code="SU", agent_country="CA", agent_city="YUL"),
               last_modification_comment=f"SIM-{r['tc']}-SC-CRT", creation_comment=f"SIM-{r['tc']}-SC-CRT",
               passengers=pax_entries, segments=segs,
               ticketing=dict(issuance_local_date=r["booking_date"],
                              fare=dict(amount="1450.00", currency="CAD"),
                              # one entry per pax so scenario_engine aligns refs to travelers; an
                              # infant reuses the preceding adult's document (lap infant, no own coupon)
                              ticket_numbers=_scn_tickets(r)),
               timeline=[dict(version=0, at=f"{r['booking_date']}T10:00:00Z", action="bootstrap",
                              description="Pre-ticketing stub"),
                         dict(version=1, at=f"{r['booking_date']}T10:00:01Z", action="ticketing_added",
                              description="Ticketing reference attached")])
    json.dump(scn, open(f"{SCENW}/{r['pnr_id']}.json", "w"), indent=1)
    return scn

def render_publish_one(r):
    make_scenario(r)
    nd = f"{NDJW}/{r['pnr']}.ndjson"
    subprocess.run(["python3", SENG, "render", "--scenario", f"{SCENW}/{r['pnr_id']}.json", "--out", nd,
                    "--canvas", CANVAS], check=True, capture_output=True)
    out = subprocess.run(["python3", PUB, "--ndjson", nd, "--brokers", CRT["brokers"], "--topic", CRT["topic"],
                          "--live"], capture_output=True, text=True)
    log = out.stdout + out.stderr
    return ("produced" in log), log

# ---- finalize ---------------------------------------------------------------
def tickets_of(r): return {int(k): v for k, v in r["tickets"].items()}

def coupons_json(r, k):
    """One coupon per segment, correlated to that segment (a bound with an uncorrelated
    coupon fails ruleTicketStatus -> SC-NE-04)."""
    return [dict(sequenceNumber=j + 1, status="OPEN_FOR_USE", fareBasisCode="YAY00EFF",
                 fareFamily=dict(code="ECO", owner="AC"),
                 soldSegment=dict(bookingClass="Y", carrierCode=s["mkt"], flightnumber=str(870 + j),
                                  departure=dict(iataCode=s["o"], at=s["dep_iso"]),
                                  arrival=dict(iataCode=s["d"], at=s["dep_iso"])))
            for j, s in enumerate(r["segs"])]

def checkin_data(r, ppid):
    s = r["segs"][0]
    return {"segment": {"id": f"DCS-{r['pnr']}", "pnrSegmentId": f"{r['pnr_id']}-ST-1",
                        "departureAirport": s["o"], "arrivalAirport": s["d"],
                        "departureDateTime": s["dep_iso"], "carrierCode": "AC", "flightNumber": "870",
                        "statusCode": "HK", "class": "Y", "cabin": "Y",
                        "dcsProductType": "ACTIVE_SYNCHRONISED",
                        "passengerDisruption": {"status": "NOT_DISRUPTED"},
                        "legDeliveries": [{"id": f"DCS-{r['pnr']}-{s['o']}", "departureAirport": s["o"],
                                           "arrivalAirport": s["d"], "departureDate": s["dep_iso"][:10],
                                           "operatingFlight": {"carrierCode": "AC", "number": "870"},
                                           "travelCabinCode": "Y",
                                           "acceptance": {"securityNumber": f"{s['o']}-001",
                                                          "status": "ACCEPTED", "acceptanceType": "PRIMARY",
                                                          "isAdvanceAccepted": True, "channel": "WEB",
                                                          "physicalAcceptanceLocation": "CKI"}}]},
            "passengerFirstName": r["paxs"][0]["first"], "passengerLastName": r["paxs"][0]["last"],
            "dateOfBirth": r["paxs"][0]["dob"], "pnrTravelerId": ppid,
            "dcsPassengerId": f"DCSPAX-{r['pnr']}"}

def rqst_text(pid, ppid, seat, at):
    return json.dumps({"code": "RQST", "subType": "SPECIAL_SERVICE_REQUEST", "serviceProvider": {"code": "AC"},
                       "status": "HK", "creation": {"dateTime": at, "pointOfSale": {"office": {"id": "YTOAA08AA"}}},
                       "seats": [{"number": seat, "characteristicCodes": ["N"],
                                  "traveler": {"type": "stakeholder", "id": ppid, "ref": "processedPnr.travelers"}}],
                       "priceCategory": {"code": "A", "subCode": "0B5"}})

# trip_details.source is varchar(5): the GDS/owner code, NOT the marketing channel.
TD_SOURCE = {"AC_ONLINE": "AC", "AC_VACATIONS": "AC", "GROUP": "AC", "OTA": "1S"}

SSR_TEXT = {"EXST": "EXTRA SEAT", "PETC": "SOFT SIDED", "UMNR": "UM10", "INFT": "INFANT OCCUPYING NO SEAT",
            "BSCT": "BASSINET REQ FOR INFT", "CHLD": "CHILD", "EUPG": "FROM-Y/TO-R/AC000000001"}

def finalize_one(r, conn):
    cur = conn.cursor(); pid, loc = r["pnr_id"], r["pnr"]
    segids = [f"{pid}-ST-{j+1}" for j in range(len(r["segs"]))]
    at = r["created"]

    # 1. tickets (one document per pax, coupons correlated to every segment). The document number
    # is PK-unique across the whole ticket table, so if a concurrent writer/prior set already owns
    # this number we must NOT clobber their row — FAIL LOUDLY so the caller re-bands, rather than
    # silently patching a foreign PNR's coupons and leaving ours ticketless.
    for k, tk in tickets_of(r).items():
        ppid = f"{pid}-PT-{k+1}"
        cur.execute("select pnr_id from ticket where primary_document_number=%s", (tk,))
        owner = cur.fetchone()
        if owner and owner[0] != pid:
            raise RuntimeError(f"ticket {tk} already owned by {owner[0]} (not {pid}); re-band this set")
        cur.execute("""insert into ticket (primary_document_number,pnr_id,passenger_id,ticket_id,
                       document_numbers,issuance_local_date,document_type,coupons)
                       values (%s,%s,%s,%s,ARRAY[%s],%s,'T',%s)
                       on conflict (primary_document_number) do update
                         set coupons=excluded.coupons, passenger_id=excluded.passenger_id
                         where ticket.pnr_id=excluded.pnr_id""",
                    (tk, pid, ppid, f"{tk}-{r['booking_date']}", tk, r["booking_date"],
                     json.dumps(coupons_json(r, k))))
    # 2. DOB + passenger types + has_infant
    for k, p in enumerate(r["paxs"]):
        cur.execute("update passenger set date_of_birth=%s, passenger_type=%s where pnr_id=%s and passenger_id=%s",
                    (p["dob"], p["ptype"], pid, f"{pid}-PT-{k+1}"))
    if any(p["ptype"] == "INF" for p in r["paxs"]):
        cur.execute("update passenger set has_infant=true where pnr_id=%s and passenger_type<>'INF'", (pid,))
    # 3. carrier patches (published all-AC so the cascade accepts it; OAL applied here)
    for j, s in enumerate(r["segs"]):
        cur.execute("""update flight_segment set marketing_carrier_code=%s, operating_carrier_code=%s,
                       bound_rph=%s, departure_datetime=%s, arrival_datetime=%s,
                       departure_datetime_local=%s, arrival_datetime_local=%s
                       where pnr_id=%s and segment_id=%s""",
                    (s["mkt"], s["op"], s["bound"], s["dep_iso"],
                     iso(datetime.datetime.strptime(s["dep_iso"], "%Y-%m-%dT%H:%M:%SZ")
                         .replace(tzinfo=datetime.timezone.utc) + datetime.timedelta(hours=7)),
                     s["dep_iso"][:19].replace("T", " "),
                     (datetime.datetime.strptime(s["dep_iso"], "%Y-%m-%dT%H:%M:%SZ")
                      + datetime.timedelta(hours=7)).strftime("%Y-%m-%d %H:%M:%S"),
                     pid, segids[j]))
    # 4. SSRs (declared + RQST seat assignments)
    cur.execute("delete from special_service_request where pnr_id=%s and ssr_id like %s", (pid, f"{pid}-QA-%"))
    n = 0
    for k, p in enumerate(r["paxs"]):
        ppid = f"{pid}-PT-{k+1}"
        for code in p["ssr"]:
            n += 1
            cur.execute("""insert into special_service_request
                (ssr_id,pnr_id,code,passenger_id,segment_id,status,text,quantity,is_removed,received_at,last_modified)
                values (%s,%s,%s,%s,%s,'HK',%s,1,false,%s,%s) on conflict (ssr_id) do nothing""",
                (f"{pid}-QA-{n}", pid, code, [ppid], segids, SSR_TEXT.get(code, code), at, at))
    for k_s, seat in r["seats"].items():
        k = int(k_s); ppid = f"{pid}-PT-{k+1}"; n += 1
        cur.execute("""insert into special_service_request
            (ssr_id,pnr_id,code,passenger_id,segment_id,status,text,quantity,is_removed,received_at,last_modified)
            values (%s,%s,'RQST',%s,%s,'HK',%s,1,false,%s,%s) on conflict (ssr_id) do nothing""",
            (f"{pid}-QA-{n}", pid, [ppid], [segids[0]], rqst_text(pid, ppid, seat, at), at, at))
    # 5. checked-in (journey_updates CHECK_IN / acceptance ACCEPTED)
    cur.execute("delete from journey_updates where pnr_id=%s and entity_id like %s", (pid, f"qa-sc-%"))
    if r["checkin"]:
        cur.execute("""insert into journey_updates
            (id,pnr_id,pnr,entity,entity_id,entity_version,event_action,event_type,data,last_modified,received_at)
            values (%s,%s,%s,'CM',%s,'1','UPDATED','CHECK_IN',%s,%s,%s)""",
            (str(uuid.uuid4()), pid, loc, f"qa-sc-{loc}", json.dumps(checkin_data(r, f"{pid}-PT-1")), at, at))
    # 6. booking source: eds booking_context (authoritative) + trip_details.source (fallback)
    grp = r["src"] == "GROUP"
    bc = {"bookingSource": r["src"], "bookingType": "REVENUE",
          "bookingSubtype": "GROUP" if grp else "REVENUE", "gdsLocator": "AMADEUS"}
    cur.execute("update eds_pnr_output set booking_context=%s where pnr_id=%s", (json.dumps(bc), pid))
    # trip_details.source is varchar(5) -> it holds the GDS code, not the channel. It is only the
    # FALLBACK for booking_source (SP maps 'AC'->'ACO'); eds booking_context above is authoritative.
    cur.execute("update trip_details set source=%s, travel_type=%s, group_details=%s where pnr_id=%s",
                (TD_SOURCE.get(r["src"], "AC"), "GROUP" if grp else "REGULAR",
                 json.dumps({"size": 10, "name": "SC QA GROUP", "sizeTaken": r["npax"],
                             "sizeRemaining": 10 - r["npax"]}) if grp else None, pid))
    # 7. one ACTIVE trip per locator
    cur.execute("update trip set status='INACTIVE' where pnr=%s and pnr_id<>%s and status='ACTIVE'", (loc, pid))
    cur.execute("update trip set status='ACTIVE', created_at=%s where pnr_id=%s", (r["created"], pid))
    conn.commit(); cur.close()

def redate(recs, conn):
    """Re-anchor the time-boundary cases to NOW (they decay with wall clock)."""
    now = datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0)
    cur = conn.cursor(); n = 0
    for r in recs:
        if not (r["seed_pnr"] and r["boundary"]): continue
        for j, s in enumerate(r["segs"]):
            s["dep_iso"] = iso(now + DEPS[s["dep"]])
            cur.execute("""update flight_segment set departure_datetime=%s, arrival_datetime=%s,
                           departure_datetime_local=%s, arrival_datetime_local=%s
                           where pnr_id=%s and segment_id=%s""",
                        (s["dep_iso"], iso(now + DEPS[s["dep"]] + datetime.timedelta(hours=7)),
                         s["dep_iso"][:19].replace("T", " "),
                         iso(now + DEPS[s["dep"]] + datetime.timedelta(hours=7))[:19].replace("T", " "),
                         r["pnr_id"], f"{r['pnr_id']}-ST-{j+1}"))
        n += 1
    conn.commit(); cur.close()
    json.dump(recs, open(OUT, "w"), indent=1)
    print(f"[redate] re-anchored {n} boundary PNRs to {iso(now)}")

# ---- verification (DB -> eligibility payload -> live endpoint) ---------------
_CTX = ssl.create_default_context(); _CTX.check_hostname = False; _CTX.verify_mode = ssl.CERT_NONE
BOOKING_SOURCE_MAP = {"AC": "ACO"}      # from cct-sp-bookingChange-crt-router/trip-to-eligibility-mapper.ts

def db_payload(pid, bound, conn):
    """Rebuild the pnrData the chatbot would send, straight from trip-tracer."""
    cur = conn.cursor()
    cur.execute("select pnr,status,created_at from trip where pnr_id=%s", (pid,))
    row = cur.fetchone()
    if not row: return None
    loc, status, created = row
    cur.execute("select source,travel_type,group_details,office_id from trip_details where pnr_id=%s", (pid,))
    td = cur.fetchone() or (None, None, None, None)
    cur.execute("""select passenger_id,first_name,last_name,passenger_type,date_of_birth from passenger
                   where pnr_id=%s and not is_removed order by passenger_id""", (pid,))
    paxrows = cur.fetchall()
    cur.execute("""select segment_id,segment_status,bound_rph,departure_airport,arrival_airport,
                   departure_datetime,arrival_datetime,marketing_carrier_code,marketing_flight_number,
                   operating_carrier_code,operating_flight_number,cabin_code,cabin_class
                   from flight_segment where pnr_id=%s and not is_removed order by segment_id""", (pid,))
    segrows = cur.fetchall()
    cur.execute("""select primary_document_number,passenger_id,document_numbers,coupons from ticket
                   where pnr_id=%s""", (pid,))
    tktrows = cur.fetchall()
    cur.execute("""select code,passenger_id,status,text from special_service_request
                   where pnr_id=%s and not is_removed""", (pid,))
    ssrrows = cur.fetchall()
    cur.execute("""select entity,entity_id,entity_version,event_action,event_type,data
                   from journey_updates where pnr_id=%s""", (pid,))
    jurows = cur.fetchall()
    cur.execute("select booking_context,bounds from eds_pnr_output where pnr_id=%s order by received_at desc limit 1", (pid,))
    edsrow = cur.fetchone()
    cur.close()

    def j(x): return json.loads(x) if isinstance(x, str) else x
    P = [{"passengerId": p[0], "pnrId": pid, "firstName": p[1], "lastName": p[2], "passengerType": p[3],
          "dateOfBirth": p[4].isoformat() if p[4] else None, "isRemoved": False, "updates": []} for p in paxrows]
    segids = [s[0] for s in segrows]
    FS = [{"segmentId": s[0], "pnrId": pid, "segmentStatus": (s[1] or "HK").strip(), "boundRph": s[2],
           "bookingDatetime": iso(created), "departureAirport": (s[3] or "").strip(),
           "arrivalAirport": (s[4] or "").strip(), "departureDatetime": iso(s[5]), "arrivalDatetime": iso(s[6]),
           "departureDatetimeLocal": iso(s[5]), "arrivalDatetimeLocal": iso(s[6]),
           "marketingCarrierCode": (s[7] or "").strip(), "marketingFlightNumber": s[8],
           "operatingCarrierCode": (s[9] or "").strip(), "operatingFlightNumber": s[10],
           "flightId": f"{(s[7] or '').strip()}-{s[8]}", "cabinCode": (s[11] or "Y").strip(),
           "cabinClass": (s[12] or "Y").strip(), "aircraftCode": "320", "isRemoved": False, "isMultileg": False,
           "passengerId": [p[0] for p in paxrows]} for s in segrows]
    T = []
    for doc, ppid, docnums, coupons in tktrows:
        cps = j(coupons) or []
        T.append({"primaryDocumentNumber": doc, "pnrId": pid, "passengerId": ppid,
                  "documentNumbers": docnums or [doc],
                  "coupons": [{"id": f"{doc}-{c.get('sequenceNumber')}", **c} for c in cps],
                  "correlation": [{"correlatedData": [
                      {"ticketCouponId": f"{doc}-{c.get('sequenceNumber')}", "pnrTravelerId": ppid,
                       "pnrAirSegmentId": segids[min(c.get("sequenceNumber", 1) - 1, len(segids) - 1)]}
                      for c in cps]}],
                  "updates": []})
    SSR = [{"code": (c or "").strip(), "passengerId": (pids or [None])[0], "status": st, "text": tx}
           for c, pids, st, tx in ssrrows]
    JU = [{"pnrId": pid, "pnr": loc, "entity": e, "entityId": eid, "entityVersion": ev, "eventAction": ea,
           "eventType": et, "data": j(d),
           "passengerIds": [j(d).get("pnrTravelerId")] if j(d).get("pnrTravelerId") else []}
          for e, eid, ev, ea, et, d in jurows]
    bc = j(edsrow[0]) if edsrow and edsrow[0] else None
    bounds = j(edsrow[1]) if edsrow and edsrow[1] else []
    for b in bounds:
        if bc: b["bookingContext"] = bc
    src = td[0]
    pd = {"changeTrigger": None, "pnrId": pid, "pnr": loc, "lastName": [], "createdAt": iso(created),
          "status": status, "source": BOOKING_SOURCE_MAP.get(src, src), "travelType": td[1],
          "groupDetails": j(td[2]), "login": None, "officeId": td[3], "iataNumber": None, "linkedPnr": None,
          "receivedAt": None, "lastModified": iso(created), "lastPnrVersion": None,
          "lastModifiedEventLogId": None, "passengers": P, "flightSegments": FS, "flightLegs": [],
          "journeyUpdates": JU, "non1a": None, "specialServiceRequests": SSR, "tickets": T, "emds": [],
          "baggageUpdates": None, "stormxVouchers": None, "icouponVouchers": None,
          "icouponTransportRedemptions": None, "cancelledVouchers": None, "edsFlight": [],
          "edsPnr": [{"pnrId": pid, "bookingContext": bc, "bounds": bounds}], "dds": [], "oalFlights": []}
    return {"changeTrigger": {"changeType": "ELIGIBILITY_SERVICE_REQUEST", "trigger": "SEAT_CHANGE",
                              "selectedBound": bound, "timestamp": None, "entity": None}, "pnrData": pd}

def call_endpoint(payload):
    req = urllib.request.Request(CRT["endpoint"], data=json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json", "x-api-key": CRT["api_key"]},
                                 method="POST")
    try:
        with urllib.request.urlopen(req, context=_CTX, timeout=40) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        return {"err": f"HTTP {e.code} {e.read().decode()[:120]}"}
    except Exception as e:
        return {"err": str(e)[:120]}

def eligibility_of(r, conn):
    p = db_payload(r["pnr_id"], r["bound"], conn)
    if p is None: return {"err": "no trip row"}
    res = call_endpoint(p)
    if "err" in res: return res
    be = (res.get("data") or {}).get("boundEligibility") or {}
    segs = be.get("segmentsEligibility") or []
    pe = (segs[0].get("passengerEligibility") if segs else []) or []
    return {"elig": be.get("isBoundEligible"), "win": be.get("processingWindow"),
            "reason": (be.get("reasonCode") or {}).get("code"), "fee": be.get("feeApplicable"),
            "val": be.get("validationStatus") or {}, "bookingSource": (res.get("data") or {}).get("bookingSource"),
            "segs": [{"seg": s["segmentId"], "op": s["operatingCarrierCode"], "elig": s["isSegmentEligible"],
                      "rc": (s.get("reasonCode") or {}).get("code")} for s in segs],
            "pax": [{"id": x["passengerId"], "elig": x["isPassengerEligible"], "umnr": x["isUmnr"],
                     "yth": x["isYouth"], "ssrs": x.get("specialSsrs") or [],
                     "rc": (x.get("reasonCode") or {}).get("code")} for x in pe]}

# ---- main -------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(); ap.add_argument("phase")
    ap.add_argument("--start", type=int, default=0); ap.add_argument("--end", type=int, default=10**9)
    a = ap.parse_args()
    if a.phase == "index": build_index(); return
    recs = load_index()
    sl = seeded(recs)[a.start:a.end]
    if a.phase == "publish":
        ok = 0
        for i, r in enumerate(sl):
            good, log = render_publish_one(r); ok += good
            print(f"  [{a.start+i:2}] {r['pnr_id']} {r['tc']:20} {'OK' if good else 'FAIL ' + log[-160:]}", flush=True)
        print(f"[publish] {ok}/{len(sl)} produced")
    elif a.phase == "checkcascade":
        conn = tt_conn(); cur = conn.cursor()
        cur.execute("select pnr_id from trip where pnr_id = any(%s)", ([r["pnr_id"] for r in sl],))
        have = {x[0] for x in cur.fetchall()}; conn.close()
        miss = [r["pnr_id"] for r in sl if r["pnr_id"] not in have]
        print(f"[cascade] {len(have)}/{len(sl)} present; missing={miss}")
    elif a.phase == "finalize":
        conn = tt_conn()
        for i, r in enumerate(sl):
            finalize_one(r, conn); print(f"  [{a.start+i:2}] {r['pnr_id']} {r['tc']} finalized", flush=True)
        conn.close(); print(f"[finalize] {len(sl)} done")
    elif a.phase == "redate":
        conn = tt_conn(); redate(recs, conn); conn.close()
    elif a.phase == "verify":
        conn = tt_conn(); ok = 0; bad = []
        for r in sl:
            g = eligibility_of(r, conn)
            good = (g.get("elig") == r["exp_elig"] and g.get("reason") == r["exp_reason"]
                    and g.get("win") == r["exp_win"])
            ok += good
            if not good: bad.append((r["tc"], r["pnr"], f"exp {r['exp_elig']}/{r['exp_win']}/{r['exp_reason']}",
                                     f"got {g.get('elig')}/{g.get('win')}/{g.get('reason')} {g.get('err','')}"))
            print(f"  {r['tc']:20} {r['pnr']} bound{r['bound']} -> {g.get('reason')} "
                  f"{g.get('win')} elig={g.get('elig')} {'OK' if good else '<<< MISMATCH'}", flush=True)
        conn.close()
        print(f"[verify] {ok}/{len(sl)} match expected")
        for b in bad: print("   ", b)
    else:
        print("phases: index publish checkcascade finalize redate verify")

if __name__ == "__main__":
    main()
