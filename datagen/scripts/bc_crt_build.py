#!/usr/bin/env python3
"""Build BOOKING CHANGE test PNRs in the CRT environment — Voluntary (VOL) + Involuntary (INVOL).

Two very different eligibility mechanisms (both discovered by probing CRT live, 2026-07-10):

VOL  — the LIVE voluntary rule flow behind
         POST /eligibility-service/execute-with-mapping   (trigger BOOKING_CHANGE,
         changeTrigger.selectedBound REQUIRED — that is Journey Selection / GenUC-08).
       Same endpoint + api-key as Seat Change / Name Correction.  The repo copy of
       rule-flows.json is STALE (7 rules); LIVE has 8 — an extra ruleCheckInBag.  Reason
       codes are VBC-* (NOT the repo's ATC_VOL_* concept names).  Probed live:

         VBC-EL-01  eligible
         VBC-NE-01  rule72hrWindow   (>72h15m to departure, or already departed)
         VBC-NE-02  ruleCheckInBag   (checked bag loaded on aircraft) *see divergence*
         VBC-NE-03  ruleBookingSource(only ACO ADO AC_MOBILE AIRPORT CONTACT_CENTRE NDC 1A_GDS)
         VBC-NE-04  ruleFareEligibility (fare family BASIC, or fare-basis suffix BA/BV/BQ)
         VBC-NE-05  ruleSsrRestriction (UPGD UPGO GRPS CBBG MEDA UMNR PETC MEQT ESAN OXYG
                                        DPNA SVAN DPLO EXST AVIH)
         VBC-NE-06  ruleTicketStatus (no 014 ticket, or ALL coupons flown/void)
         VBC-NE-07  ruleCheckinStatus(journey_updates LEG_DELIVERY/CHECK_IN acceptance ACCEPTED)
         VBC-NE-08  ruleEUpgrade     (EUPG ssr)
       processing window: none returned for VOL (feeApplicable/window are seat-change fields).
       Eligible booking sources differ from Seat Change: GROUP / AEROPLAN / AC_VACATIONS are
       NOT eligible for VOL (all -> VBC-NE-03).

INVOL— NOT handled by the rule engine (the endpoint returns HTTP 422 "Unsupported trigger
       'INVOLUNTARY'").  Eligibility is computed by the downstream Involuntary API
       (Order Retrieve + DBaaS/DDS) which is disruption-driven and not statelessly probeable.
       So INVOL PNRs are seeded with the retrievable disruption data model — original segment
       CANCELLED (status UN) + auto-rebooked segment (HK), delay, booking source, SSRs, checked
       baggage, ticket — and VERIFIED only on the BOOKING SIDE (what Order Retrieve reads).

WHERE EACH VOL INPUT LIVES (identical plumbing to Seat Change):
  booking_source  eds_pnr_output.booking_context.bookingSource (authoritative)
                  + trip_details.source fallback ('AC'->'ACO' by the SP router)
  72hr window     flight_segment.departure_datetime (selected bound's first seg) vs now
  ticket          ticket.primary_document_number (014) + coupons[].status (FLOWN => invalid)
  fare            ticket.coupons[].fareBasisCode (suffix BA/BV/BQ) / fareFamily.code (BASIC)
  ssr             special_service_request.code
  checked in      journey_updates event_type CHECK_IN/LEG_DELIVERY acceptance ACCEPTED
  eUpgrade        special_service_request.code == EUPG
  checked bag     BagLoadedOnAircraftDeclaration (downstream self-serve check; see divergence)

Phases (idempotent / resumable):  index publish checkcascade finalize redate verify
Usage: python3 bc_crt_build.py <phase> [--flow vol|invol|all] [--start N] [--end N]
  (no AWS creds needed; WARP on).  Reuses scenario_engine + publish_raw + the CRT config,
  name pool and endpoint caller from sc_crt_build.
"""
import json, os, sys, uuid, subprocess, argparse, random, datetime, copy
import psycopg2
import sc_crt_build as SC          # infra reuse: CRT config, tt_conn, iso, name_pool, call_endpoint
import crt_uniqnames as U

CRT   = SC.CRT
iso   = SC.iso
tt_conn = SC.tt_conn
KB    = SC.KB
SENG  = SC.SENG
PUB   = SC.PUB
CANVAS = SC.CANVAS

WORK  = os.environ.get("BC_WORK", "/tmp/cctqa-datagen"
                       "6b2a122c-1cc3-496f-9016-654db1d90750/scratchpad/bc_work")
SCENW, NDJW = f"{WORK}/scenarios", f"{WORK}/ndjson"
for d in (SCENW, NDJW): os.makedirs(d, exist_ok=True)
OUT   = os.environ.get("BC_OUT", f"{WORK}/_BC_crt_index.json")

EMAIL = os.environ.get("CRT_EMAIL", "lahiru@ae-qa1-aircanada.mailinator.com")
PHONE = os.environ.get("CRT_PHONE", "+94712534323")
DOB_ADT = "1986-04-23"
TPREFIX = os.environ.get("BC_TPREFIX", "014312")     # fresh series (014303/4/7/8 = SC, 014301 ANC, 014292 BAT)
TBASE0  = int(os.environ.get("BC_TBASE", "1000000"))
SEED    = int(os.environ.get("BC_SEED", "515515"))
NAME_SKIP = int(os.environ.get("BC_NAME_SKIP", "0"))
# opt-in: assign DB-absent, set-unique passenger names (default OFF -> legacy pool names)
UNIQ = os.environ.get("CRT_UNIQ_NAMES") == "1"

NOW = datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0)
CREATED = NOW - datetime.timedelta(days=10)
BOOK_DATE = CREATED.date().isoformat()

# departure specs -> timedelta from NOW.  VOL eligible window is 0 < minutes <= 4335 (72h15m).
DEPS = {
    "D2":     datetime.timedelta(hours=48),           # default VOL eligible: within 72h
    "D2b":    datetime.timedelta(hours=52),
    "D1":     datetime.timedelta(hours=24),
    "OUT72":  datetime.timedelta(hours=100),          # >72h15m -> VBC-NE-01
    "M30":    datetime.timedelta(minutes=30),         # departs in 30 min (still within window by rule)
    "PAST3":  datetime.timedelta(hours=-3),           # departed -> VBC-NE-01
    "PAST6":  datetime.timedelta(hours=-6),           # flown seg (mid-journey)
    "INV5":   datetime.timedelta(days=5),             # INVOL original/rebooked, comfortably future
}
BOUNDARY = {"D2", "D2b", "D1", "OUT72", "M30", "PAST3", "PAST6"}   # VOL time-sensitive -> redate

# ages
def age_dob(y): return (NOW - datetime.timedelta(days=int(365.25 * y))).date().isoformat()
CH5, CH7, CH9, CH10 = age_dob(5), age_dob(7), age_dob(9), age_dob(10)
YTH14 = age_dob(14)
INF10M = (NOW - datetime.timedelta(days=300)).date().isoformat()
INF18M = (NOW - datetime.timedelta(days=540)).date().isoformat()

# ---- passenger spec ---------------------------------------------------------
def P(n=1, types=None, ssrs=None, dobs=None):
    types = types or ["ADT"] * n
    ssrs  = ssrs  or [[] for _ in range(n)]
    dobs  = dobs  or [None] * n
    return [dict(ptype=types[i], ssr=ssrs[i], dob=dobs[i]) for i in range(n)]

# ---- segment specs ----------------------------------------------------------
# (op, mkt, bound, origin, dest, dep_spec, status, coupon)   status HK|UN ; coupon OPEN|FLOWN
def S(op, mkt, bnd, o, d, dep, status="HK", coupon="OPEN"):
    return dict(op=op, mkt=mkt, bound=bnd, o=o, d=d, dep=dep, status=status, coupon=coupon)

def ac(dep="D2", o="YYZ", d="YVR", status="HK", coupon="OPEN", bnd=1):
    return [S("AC", "AC", bnd, o, d, dep, status, coupon)]

# ---- case constructor -------------------------------------------------------
def C(tc, flow, pri, feat, name, segs=None, paxs=None, src="ACO", exp=None,
      bound=1, checkin=False, bag=None, fare="ECO", cabin="Y", seat=None,
      chatbot="", runtime="", seed_pnr=True, divergence=""):
    """exp = VBC reason code for VOL (None => booking-side only / INVOL).
       bag: None|'notloaded'|'loaded'  fare: 'ECO'|'BASIC'  cabin: Y|J|O"""
    return dict(tc=tc, flow=flow, pri=pri, feat=feat, name=name,
                segs=segs or ac(), paxs=paxs or P(1), src=src, exp=exp, bound=bound,
                checkin=checkin, bag=bag, fare=fare, cabin=cabin, seat=seat,
                chatbot=chatbot, runtime=runtime, seed_pnr=seed_pnr, divergence=divergence)

EL = "VBC-EL-01"

# =============================================================================
# VOLUNTARY case table  (trigger BOOKING_CHANGE)
# =============================================================================
VOL = [
 C("VOL_TC001","vol","P1","Voluntary (Eligible)","Change to higher fare, pays fare difference",
   exp=EL, chatbot="BCVol-02 Change my flight -> higher fare -> payment"),
 C("VOL_TC002","vol","P1","Voluntary (Eligible)","Change to lower fare, refund initiated", exp=EL),
 C("VOL_TC003","vol","P1","Voluntary (Eligible)","Change to equal fare, no payment/refund", exp=EL),
 C("VOL_TC004","vol","P1","Voluntary (Eligible)","Rejects all options -> escalate after retry limit",
   exp=EL, runtime="ENVIRONMENTAL: retry threshold is chatbot-side"),
 C("VOL_TC005","vol","P2","Voluntary (Eligible)","Route change, outbound higher fare (no change fee)",
   exp=EL, chatbot="BCVol alt-criteria = Arrival/Departure Airport"),
 C("VOL_TC006","vol","P2","Voluntary (Eligible)","Route change, outbound lower fare (change fee applies)",
   exp=EL),
 C("VOL_TC007","vol","P2","Voluntary (Eligible)","Date outside allowed 7-day window -> retry prompt",
   exp=EL, divergence="7-day search window is a WIDGET limit; the rule 72h window still accepts the "
   "seeded 48h departure -> VBC-EL-01. Retry prompt is chatbot-side."),
 C("VOL_TC008","vol","P2","Voluntary (Eligible)","Selected flight becomes unavailable (seats blocked)",
   exp=EL, runtime="ENVIRONMENTAL: live inventory refresh"),
 C("VOL_TC009","vol","P1","Voluntary (Eligible)","Payment fails then succeeds on retry",
   exp=EL, runtime="ENVIRONMENTAL: payment gateway"),
 C("VOL_TC010","vol","P3","Voluntary (Eligible)","Add ancillaries during change", exp=EL),
 C("VOL_TC011","vol","P3","Voluntary (Eligible)","Skip ancillaries, existing removed", exp=EL,
   runtime="existing ancillaries attached (seat 14A seeded)", seat="14A"),
 C("VOL_TC012","vol","P1","Voluntary (Eligible)","Backend failure during booking update (GLOB-09)",
   exp=EL, runtime="ENVIRONMENTAL"),
 C("VOL_TC013","vol","P3","Voluntary (Eligible)","Proceeds without selecting a flight -> validation",
   exp=EL, runtime="ENVIRONMENTAL"),
 C("VOL_TC014","vol","P2","Voluntary (Eligible)","Dynamic waiver removes change fee, no payment",
   exp=EL, divergence="ruleDynamicWaiver is a live placeholder (NOT_APPLICABLE); waiver pricing is "
   "downstream. PNR is seeded eligible."),
 C("VOL_TC015","vol","P2","Voluntary (Eligible)","Cabin upgrade Economy -> Business", exp=EL, cabin="Y",
   chatbot="Upgrade my flight -> J cabin available on replacement"),
 C("VOL_TC016","vol","P2","Voluntary (Eligible)","Cabin downgrade -> accepts live agent transfer",
   exp=EL, cabin="J", chatbot="original cabin Business; downgrade intent -> GLOB-16"),
 C("VOL_TC017","vol","P3","Voluntary (Eligible)","Cabin downgrade -> declines transfer, flow ends",
   exp=EL, cabin="O", chatbot="original cabin Premium Economy"),
 C("VOL_TC018","vol","P3","Voluntary (Eligible)","Cash bid upgrade Economy -> Business (Plusgrade)",
   exp=EL, chatbot="ADD-71 bid upgrade; Aeroplan member, 014 stock, not basic, no blocking SSR"),
 C("VOL_TC019","vol","P1","Voluntary (Eligible)","Multi-pax booking, all rebooked together",
   paxs=P(2), exp=EL),
 C("VOL_TC020","vol","P1","Voluntary (Eligible)","2 ADT + 1 CHD + 1 INF (lap infant), full flow",
   paxs=P(4, ["ADT","ADT","CHD","INF"], [[],[],["CHLD"],["INFT"]], [None,None,CH7,INF10M]), exp=EL),
 C("VOL_TC021","vol","P2","Voluntary (Eligible)","2 ADT + 1 CHD + 1 INS (infant with seat)",
   paxs=P(4, ["ADT","ADT","CHD","INF"], [[],[],["CHLD"],["BSCT"]], [None,None,CH5,INF18M]), exp=EL,
   runtime="INS = infant occupying seat; gets child fare + own seat"),
 C("VOL_TC022","vol","P3","Voluntary (Eligible)","1 ADT + 1 CHD + 1 YTH (YPTU) accompanied youth",
   paxs=P(3, ["ADT","CHD","YTH"], [[],["CHLD"],["YPTU"]], [None,CH9,YTH14]), exp=EL,
   divergence="YPTU is not a blocking SSR -> VBC-EL-01. Accompanied-youth allowance is design-correct."),
 C("VOL_TC024","vol","P2","Voluntary (Eligible)","Multi-pax split PNR (not all together) -> live agent",
   paxs=P(3, ["ADT","ADT","CHD"], [[],[],["CHLD"]], [None,None,CH10]), exp=EL,
   chatbot="BCVol-04 'is everyone rebooked together?' No -> GLOB-16 (chatbot-side split)"),
 C("VOL_TC025","vol","NA","Voluntary (Eligible)","Same-day connect: seg1 flown, seg2 unflown -> change seg2",
   segs=[S("AC","AC",1,"YYZ","YUL","PAST6","HK","FLOWN"), S("AC","AC",2,"YUL","YHZ","D2","HK","OPEN")],
   bound=2, exp=EL, chatbot="mid-journey; seg1 (bound1) flown/USED excluded, GenUC-08 selects the "
   "onward journey (bound2) -> only seg2 evaluated -> eligible",
   divergence="Modelled as two selectable journeys: bound1 = flown YYZ-YUL, bound2 = onward YUL-YHZ. "
   "The chatbot's journey selection (GenUC-08) targets bound2. Selecting bound1 would return VBC-NE-01 "
   "(its leg has departed)."),
 C("VOL_TC026","vol","NA","Voluntary (Eligible)","Intl overnight connect: seg1 flown, seg2 unflown",
   segs=[S("AC","AC",1,"YYZ","LHR","PAST6","HK","FLOWN"), S("AC","AC",2,"LHR","CDG","D2","HK","OPEN")],
   bound=2, exp=EL, chatbot="onward journey bound2 = LHR-CDG selected"),
 C("VOL_TC027","vol","NA","Voluntary (Eligible)","Intl overnight, seat 12A + bags NOT loaded -> proceeds",
   segs=[S("AC","AC",1,"YYZ","LHR","PAST6","HK","FLOWN"), S("AC","AC",2,"LHR","CDG","D2","HK","OPEN")],
   bound=2, exp=EL, seat="12A", bag="notloaded",
   divergence="BagLoadedOnAircraftDeclaration=FALSE -> ruleCheckInBag pass -> VBC-EL-01. Onward journey bound2."),
 C("VOL_TC028","vol","NA","Voluntary (Eligible)","Same-day connect: seg2 checked in -> cancel check-in first",
   segs=[S("AC","AC",1,"YYZ","YUL","PAST6","HK","FLOWN"), S("AC","AC",2,"YUL","YHZ","D2","HK","OPEN")],
   bound=2, exp="VBC-NE-07", checkin=True,
   chatbot="BCVol-03 detects check-in on onward bound2 -> SSCI cancel -> ADD-70 re-verify"),
 C("VOL_TC029","vol","P3","Voluntary (Eligible)","Change departure airport to sister city (YYZ->YTZ)",
   exp=EL),
 C("VOL_TC029b","vol","P3","Voluntary (Eligible)","Change arrival airport to sister city (EWR->JFK)",
   segs=ac("D2","YUL","EWR"), exp=EL, chatbot="second VOL_TC019 row in sheet (arrival sister city)"),
 C("VOL_TC030","vol","P1","Voluntary (inEligible)","Non-self-service SSR (OXYG) -> live agent",
   paxs=P(1, ["ADT"], [["OXYG"]]), exp="VBC-NE-05"),
 C("VOL_TC031","vol","P1","Voluntary (inEligible)","Checked baggage attached -> blocked",
   exp=EL, bag="loaded", divergence="ruleCheckInBag did not fire for any seeded baggage shape probed "
   "on CRT (baggage_updates BAG_LOADED_ON_AIRCRAFT, seg/pax booleans all -> pass). The checked-bag "
   "block (VBC-NE-02) is enforced by the downstream BCVol-03 self-serve check, not the stateless rule "
   "endpoint. PNR carries a real BAG_LOADED_ON_AIRCRAFT row for the downstream check."),
 C("VOL_TC032","vol","P1","Voluntary (inEligible)","Third-party (Expedia) booking -> blocked",
   src="OTA", exp="VBC-NE-03"),
 C("VOL_TC033","vol","P2","Voluntary (inEligible)","Air Canada Vacations booking -> blocked",
   src="AC_VACATIONS", exp="VBC-NE-03",
   divergence="AC_VACATIONS is eligible for Seat Change but NOT for Voluntary -> VBC-NE-03."),
 C("VOL_TC034","vol","P2","Voluntary (inEligible)","OAL (Lufthansa) segment present -> blocked",
   segs=[S("LH","AC",1,"YYZ","FRA","D2","HK","OPEN")], exp=EL,
   divergence="The VOL rule flow has NO carrier-mix rule (unlike Seat Change). An OAL-operated segment "
   "returns VBC-EL-01; the OAL block is enforced in the widget / downstream."),
 C("VOL_TC035","vol","P2","Voluntary (inEligible)","Group booking -> blocked", src="GROUP",
   exp="VBC-NE-03", divergence="GROUP is eligible for Seat Change but NOT for Voluntary -> VBC-NE-03."),
 C("VOL_TC036","vol","P2","Voluntary (inEligible)","Change within restricted time window (dep 30 min)",
   segs=ac("M30"), exp=EL, divergence="A 30-minute-out departure is still inside the rule's 0<t<=72h15m "
   "window -> VBC-EL-01. The last-minute restriction is a widget rule."),
 C("VOL_TC037","vol","P1","Voluntary (inEligible)","Repeated invalid booking details -> retry blocked",
   seed_pnr=False, runtime="reserved locator, never seeded"),
 C("VOL_TC038","vol","P2","Voluntary (inEligible)","Partially correct ID (correct PNR, wrong surname)",
   exp=EL, runtime="tester enters a wrong surname against this seeded PNR"),
 C("VOL_TC039","vol","P1","Voluntary (inEligible)","Eligibility service failure -> agent routing",
   exp=EL, runtime="ENVIRONMENTAL: API outage"),
 C("VOL_TC040","vol","P3","Voluntary (inEligible)","Override attempt on ineligible booking",
   fare="BASIC", exp="VBC-NE-04", runtime="booking is ineligible (basic fare); override must be blocked"),
 C("VOL_TC041","vol","P1","Voluntary (inEligible)","Rejects legal disclaimer -> flow ends",
   exp=EL, runtime="ENVIRONMENTAL: disclaimer rejection"),
 C("VOL_TC042","vol","P2","Voluntary (inEligible)","Aeroplan redemption booking -> blocked",
   src="AEROPLAN", exp="VBC-NE-03",
   divergence="AEROPLAN is eligible for Seat Change but NOT for Voluntary -> VBC-NE-03."),
 C("VOL_TC043","vol","P3","Voluntary (inEligible)","Confirmed eUpgrade (EUPG) -> blocked",
   paxs=P(1, ["ADT"], [["EUPG"]]), exp="VBC-NE-08"),
 C("VOL_TC044","vol","P2","Voluntary (inEligible)","Basic fare booking -> blocked", fare="BASIC",
   exp="VBC-NE-04"),
 C("VOL_TC045","vol","P3","Voluntary (InEligible)","Bid upgrade unavailable — blocking SSR (PETC)",
   paxs=P(1, ["ADT"], [["PETC"]]), exp="VBC-NE-05"),
 C("VOL_TC046","vol","P1","Voluntary (InEligible)","Intl overnight, bag LOADED at connect -> blocked",
   segs=[S("AC","AC",1,"YYZ","LHR","PAST6","HK","FLOWN"), S("AC","AC",2,"LHR","CDG","D2","HK","OPEN")],
   bound=2, exp=EL, seat="12A", bag="loaded",
   divergence="Same as VOL_TC031 — checked-bag block (VBC-NE-02) is downstream, not stateless. Onward bound2."),
 C("VOL_TC047","vol","P3","Voluntary - Ineligible","Two-segment itinerary, BOTH segments flown -> none eligible",
   segs=[S("AC","AC",1,"YYZ","YUL","PAST6","HK","FLOWN"), S("AC","AC",1,"YUL","YHZ","PAST3","HK","FLOWN")],
   exp="VBC-NE-06", chatbot="all coupons flown -> zero eligible segments"),
 C("VOL_TC048","vol","P1","Live Agent Handoff (GLOB-16)","Checked baggage inducted -> blocked (airport agent)",
   exp=EL, bag="loaded", divergence="Same as VOL_TC031 — checked-bag/induction block is downstream."),
 C("VOL_TC049","vol","P2","Voluntary (InEligible)","Single Youth Passenger (YP, age 14) -> blocked",
   paxs=P(1, ["YTH"], [[]], [YTH14]), exp=EL,
   divergence="A lone YTH has no blocking SSR and passenger_type is not a VOL rule input -> VBC-EL-01. "
   "The single-youth block is enforced at the chatbot passenger-type check."),
 C("VOL_TC050","vol","P3","Voluntary (InEligible)","Employee Travel Site (ETS) booking -> blocked",
   src="ETS", exp="VBC-NE-03", divergence="ETS maps to an unsupported booking source -> VBC-NE-03."),
 C("SeatChange_TC052","vol","P2","Happy Path","Voluntary flow seat change with AC flight continues vol flow",
   exp=EL, seat="22C", chatbot="BCVol-07a seat change returns to vol flow"),
]

# =============================================================================
# INVOLUNTARY case table  (disruption data model; booking-side verification only)
# =============================================================================
# INVOL segment convention: original disrupted flight status UN (cancelled), rebooked HK.
def disr(o="YYZ", d="YVR", rebook=True, delay_min=240, src_dep="INV5"):
    """Original cancelled seg + (optionally) an auto-rebooked seg on the same bound."""
    segs = [S("AC","AC",1,o,d,src_dep,"UN","OPEN")]
    if rebook:
        segs.append(S("AC","AC",1,o,d,src_dep,"HK","OPEN"))   # rebooked (dep patched by delay in finalize)
    return segs

def CI(tc, pri, feat, name, o="YYZ", d="YVR", rebook=True, delay=240, src="ACO",
       paxs=None, ssr=None, bag=None, checkin=False, fare="ECO", seed_pnr=True,
       chatbot="", runtime="", divergence=""):
    pax = paxs or P(1)
    if ssr:                                     # attach ssr list to first pax
        pax[0]["ssr"] = list(set(pax[0]["ssr"]) | set(ssr))
    return dict(tc=tc, flow="invol", pri=pri, feat=feat, name=name,
                segs=disr(o, d, rebook, delay), paxs=pax, src=src, exp=None, bound=1,
                checkin=checkin, bag=bag, fare=fare, cabin="Y", seat=None,
                delay=delay, rebooked=rebook, chatbot=chatbot, runtime=runtime,
                seed_pnr=seed_pnr, divergence=divergence)

INVOL = [
 CI("InVOL_TC001","P1","Involuntary (Eligible)","Accepts airline-proposed itinerary after disruption",
    o="YYZ", d="YVR", rebook=True, delay=180, chatbot="already rebooked -> Confirm proposed itinerary"),
 CI("InVOL_TC002","P1","Involuntary (Eligible)","Rejects proposal, searches alternate flight",
    o="YUL", d="YYC", rebook=True, delay=180),
 CI("InVOL_TC003","P2","Involuntary (Eligible)","Changes travel date within waiver window (+/-3 days)",
    o="YOW", d="YHZ", rebook=True, delay=120),
 CI("InVOL_TC004","P2","Involuntary (Eligible)","No alternate flights available -> agent escalation",
    o="YYZ", d="LAS", rebook=True, delay=200, runtime="ENVIRONMENTAL: no inventory in search"),
 CI("InVOL_TC005","P2","Involuntary (Eligible)","Rejects all alternate options -> support offered",
    o="YVR", d="YEG", rebook=True, delay=150, runtime="ENVIRONMENTAL: retry threshold"),
 CI("InVOL_TC006","P1","Involuntary (Eligible)","Already-rebooked passenger accepts itinerary",
    o="YYZ", d="YVR", rebook=True, delay=90),
 CI("InVOL_TC007","P2","Involuntary (Eligible)","Rebooked, minor delay (18 min) -> acknowledgment only",
    o="YYZ", d="YVR", rebook=True, delay=18, chatbot="<30 min -> acknowledgment only"),
 CI("InVOL_TC008","P1","Involuntary (Eligible)","240-min arrival delay -> refund option displayed",
    o="YVR", d="LHR", rebook=True, delay=240, src="ACO",
    chatbot="delay>179 + ACB source -> Confirm/Change/Cancel&Refund"),
 CI("InVOL_TC009","P1","Involuntary (Eligible)","No-Pro passenger manually searches & confirms alternate",
    o="YYZ", d="YVR", rebook=False, delay=200, chatbot="no automatic rebooking exists"),
 CI("InVOL_TC010","P2","Involuntary (Eligible)","Delay under 30 min -> acknowledgment only",
    o="YYZ", d="YEG", rebook=True, delay=18),
 CI("InVOL_TC011","P2","Involuntary (Eligible)","Delay 31-179 min -> flight change enabled (no refund)",
    o="YUL", d="ORD", rebook=True, delay=95),
 CI("InVOL_TC012","P1","Involuntary (Eligible)","Delay >=180 min -> refund option enabled",
    o="YVR", d="LHR", rebook=True, delay=240),
 CI("InVOL_TC013","P1","Involuntary (Eligible)","Checked-baggage informational alert after rebooking",
    o="YYC", d="YYZ", rebook=True, delay=120, bag="notloaded",
    chatbot="domestic, baggage exists but does not block -> transfer message"),
 CI("InVOL_TC014","P1","Involuntary (Eligible)","Only impacted bound shown (round-trip, outbound cancelled)",
    o="YYZ", d="FRA", rebook=True, delay=200,
    chatbot="return bound remains locked; add 2nd bound in finalize"),
 CI("InVOL_TC015","P3","Involuntary (Eligible)","Session restored after device/channel switch",
    o="YYZ", d="YVR", rebook=True, delay=120, runtime="ENVIRONMENTAL: session persistence"),
 CI("InVOL_TC016","P1","Involuntary (Eligible)","Cancel booking -> refund deep-link",
    o="YVR", d="SFO", rebook=True, delay=240),
 CI("InVOL_TC017","P2","Involuntary (Eligible)","Duplicate acknowledgment blocked (idempotency)",
    o="YYZ", d="YVR", rebook=True, delay=120, runtime="ENVIRONMENTAL: idempotency"),
 CI("InVOL_TC018","P3","Involuntary (Eligible)","Already-rebooked flight excluded from alt search results",
    o="YYZ", d="YVR", rebook=True, delay=150, runtime="ENVIRONMENTAL: search excludes rebooked flight"),
 CI("InVOL_TC019","P2","Involuntary (Eligible)","Only disrupted segment updated (3-seg multi-city)",
    o="YYZ", d="YUL", rebook=True, delay=200,
    chatbot="seg2 YUL->CDG cancelled; seg1/seg3 active (multi-seg added in finalize)"),
 CI("InVOL_TC020","P1","Involuntary (InEligible)","Rejects legal disclaimer -> flow terminated",
    o="YYZ", d="YVR", rebook=True, delay=120, runtime="ENVIRONMENTAL: disclaimer rejection"),
 CI("InVOL_TC021","P1","Involuntary (InEligible)","Repeated invalid booking credentials -> blocked",
    seed_pnr=False, runtime="reserved locator, never seeded"),
 CI("InVOL_TC022","P1","Involuntary (InEligible)","Correct PNR, incorrect surname",
    o="YYZ", d="YVR", rebook=True, delay=120, runtime="tester enters wrong surname"),
 CI("InVOL_TC023","P2","Involuntary (InEligible)","Booking not self-reac eligible (selfReac=false)",
    o="YYZ", d="YVR", rebook=True, delay=120,
    divergence="selfReac is a DBaaS/DDS verdict, not seedable on the PNR; seeded as retrievable disruption."),
 CI("InVOL_TC024","P3","Involuntary (InEligible)","OAL rebooking (Lufthansa) blocked from self-service",
    o="YYZ", d="FRA", rebook=True, delay=200,
    divergence="rebooked seg patched to LH-operated in finalize -> OAL"),
 CI("InVOL_TC025","P2","Involuntary (InEligible)","Departure too close (<30 min) -> wait advisory",
    o="YYZ", d="YVR", rebook=True, delay=15),
 CI("InVOL_TC026","P2","Involuntary (InEligible)","Eligibility API timeout -> agent escalation",
    o="YYZ", d="YVR", rebook=True, delay=120, runtime="ENVIRONMENTAL: API timeout"),
 CI("InVOL_TC027","P3","Involuntary (InEligible)","Third-party OTA disrupted booking -> blocked",
    o="YYZ", d="YVR", rebook=True, delay=120, src="OTA"),
 CI("InVOL_TC028","P1","Involuntary (InEligible)","Checked baggage blocks self-service before change",
    o="YYZ", d="YVR", rebook=True, delay=200, bag="loaded",
    chatbot="Self-Serve Check 1 detects checked bag -> block"),
 CI("InVOL_TC029","P1","Involuntary Eligible","Mid-journey: seg1 flown, connecting seg cancelled, bag -> airport agent",
    o="YYZ", d="YUL", rebook=False, delay=200, bag="loaded",
    chatbot="seg1 YYZ->YUL flown; seg2 YUL->LHR cancelled; checked bag -> airport baggage agent"),
 CI("InVOL_TC030","P3","Involuntary (InEligible)","PETC SSR booking -> agent",
    o="YYZ", d="YVR", rebook=True, delay=150, ssr=["PETC"]),
 CI("InVOL_TC031","P3","Involuntary (InEligible)","Upgrade booking (UPGD/UPGO) -> manual handling",
    o="YYZ", d="YVR", rebook=True, delay=150, ssr=["UPGD"]),
 CI("InVOL_TC032","P3","Involuntary (InEligible)","Aeroplan redemption -> Manage My Booking",
    o="YYZ", d="YVR", rebook=True, delay=150, src="AEROPLAN"),
 CI("InVOL_TC033","P3","Involuntary (InEligible)","ACV request -> ACV Contact Us redirect at entry",
    o="YYZ", d="YVR", rebook=True, delay=150, src="AC_VACATIONS"),
 CI("InVOL_TC034","P3","Involuntary (InEligible)","AC Cargo request -> Contact Us redirect at entry",
    o="YYZ", d="YVR", rebook=True, delay=150, src="AC_CARGO", runtime="AC Cargo context redirect"),
 CI("InVOL_TC035","P3","Involuntary (InEligible)","Group booking (GRPS SSR) -> blocked",
    o="YYZ", d="YVR", rebook=True, delay=150, ssr=["GRPS"], src="GROUP"),
 CI("InVOL_TC036","P3","Involuntary (SPML)","SPML/VGML special meal -> blocked, routes to agent",
    o="YYZ", d="YVR", rebook=True, delay=150, ssr=["VGML"]),
 CI("InVOL_TC037","P3","Involuntary (KSML)","KSML kosher meal -> blocked",
    o="YYZ", d="JFK", rebook=True, delay=150, ssr=["KSML"]),
 CI("InVOL_TC038","P3","Involuntary (DBML)","DBML diabetic meal -> blocked",
    o="YYZ", d="LAX", rebook=True, delay=150, ssr=["DBML"]),
 CI("InVOL_TC039","P2","Involuntary (InEligible ETS)","ETS (Employee Travel) booking -> blocked",
    o="YYZ", d="YOW", rebook=True, delay=150, src="ETS"),
 CI("InVOL_TC040","P2","Involuntary (Error)","Confirm Alternate Offer API fails twice -> agent",
    o="YYZ", d="YVR", rebook=True, delay=200, runtime="ENVIRONMENTAL: confirm API failure"),
 CI("InVOL_TC041","P3","Involuntary (InEligible UMNR)","UMNR (unaccompanied minor) SSR -> agent",
    o="YVR", d="YYC", rebook=True, delay=150, paxs=P(1, ["CHD"], [["UMNR"]], [CH10])),
 CI("InVOL_TC042","P3","Involuntary (InEligible IT/BT)","IT/BT (industry/bulk) fare -> blocked",
    o="YYZ", d="YUL", rebook=True, delay=150, fare="ITBT"),
 CI("InVOL_TC043","P1","Involuntary (InEligible Non-1A GDS)","Non-Amadeus GDS (Sabre 1S), GDSSelfReacc=N -> blocked",
    o="YYZ", d="YUL", rebook=True, delay=150, src="OTA", fare="ITBT",
    runtime="booking source 1S / GDSSelfReacc=N"),
 CI("InVOL_TC044","P2","Involuntary (InEligible Basic)","Basic fare disrupted booking",
    o="YYZ", d="YVR", rebook=True, delay=150, fare="BASIC"),
 CI("InVOL_TC045","P2","Involuntary (System)","Service downtime before disclaimer -> downtime message",
    o="YYZ", d="YVR", rebook=True, delay=120, runtime="ENVIRONMENTAL: service error API"),
 CI("InVOL_TC046","P3","Involuntary (InEligible AVIH)","AVIH (animal in hold) SSR -> agent",
    o="YYZ", d="YVR", rebook=True, delay=150, ssr=["AVIH"]),
 CI("Booking Change_SeatChange_TC047","P3","Disruption","Eligible disrupted flight seat change (TK status)",
    o="YYZ", d="YUL", rebook=True, delay=150, chatbot="original AC870 cancelled, rebooked AC872, seat change"),
]

CASES = VOL + INVOL

# ---- index ------------------------------------------------------------------
def all_taken(conn):
    cur = conn.cursor(); cur.execute("select distinct pnr from trip"); return {r[0] for r in cur.fetchall()}

def free_docs(conn, n, prefix=None, base=None):
    """n ticket documents on `prefix` that are ABSENT from the ticket table.

    A band that looks free by a narrow range count can still collide: unrelated PNRs (some months
    old) hold same-prefix documents, and finalize's
        INSERT ... ON CONFLICT (primary_document_number) DO UPDATE SET coupons
    would then patch THAT pnr's row and leave ours ticket-less (every VOL case -> VBC-NE-06).
    So probe every candidate against the DB and skip the taken ones."""
    prefix = prefix or TPREFIX
    base = TBASE0 if base is None else base
    cur = conn.cursor(); out = []
    cand = [f"{prefix}{base + i * 10:07d}" for i in range(n * 4 + 200)]
    for i in range(0, len(cand), 500):
        b = cand[i:i + 500]
        cur.execute("select primary_document_number from ticket where primary_document_number = any(%s)", (b,))
        used = {x[0] for x in cur.fetchall()}
        out.extend([d for d in b if d not in used])
        if len(out) >= n: break
    cur.close()
    if len(out) < n:
        raise RuntimeError(f"ticket-doc generator short on {prefix}: need {n}, found {len(out)} free")
    return out[:n]

def build_index():
    rnd = random.Random(SEED)
    conn = tt_conn(); taken = all_taken(conn); conn.close()
    A = "ABCDEFGHIJKLMNPQRSTUVWXYZ23456789"
    n_reserved = sum(1 for c in CASES if not c["seed_pnr"])
    locs = []
    while len(locs) < len(CASES) + n_reserved:
        L = "".join(rnd.choice(A) for _ in range(6))
        if L not in taken and L not in locs: locs.append(L)
    pool = SC.name_pool(NAME_SKIP)
    # ticket documents are probed against the DB, never just taken from a "free-looking" band
    dconn = tt_conn()
    docs = free_docs(dconn, sum(len(c["paxs"]) for c in CASES))
    dconn.close()
    recs, dk, ri = [], 0, len(CASES)
    for i, c in enumerate(CASES):
        loc = locs[i]
        if not c["seed_pnr"]:
            loc = locs[ri]; ri += 1                      # reserved, never-seeded
        pid = f"{loc}-{BOOK_DATE}"
        paxs = []
        for p in c["paxs"]:
            fn, ln = next(pool)
            paxs.append(dict(first=fn, last=ln, ptype=p["ptype"], ssr=p["ssr"], dob=p["dob"] or DOB_ADT))
        tickets = {}
        for k in range(len(paxs)):
            tickets[k] = docs[dk]; dk += 1
        segs = [dict(op=s["op"], mkt=s["mkt"], bound=s["bound"], o=s["o"], d=s["d"], dep=s["dep"],
                     status=s["status"], coupon=s["coupon"], dep_iso=iso(NOW + DEPS[s["dep"]]))
                for s in c["segs"]]
        recs.append(dict(tc=c["tc"], flow=c["flow"], pri=c["pri"], feat=c["feat"], name=c["name"],
                         pnr=loc, pnr_id=pid, booking_date=BOOK_DATE, created=iso(CREATED),
                         segs=segs, paxs=paxs, npax=len(paxs), tickets=tickets, src=c["src"],
                         bound=c["bound"], checkin=c["checkin"], bag=c.get("bag"), fare=c["fare"],
                         cabin=c["cabin"], seat=c.get("seat"), exp=c["exp"],
                         delay=c.get("delay"), rebooked=c.get("rebooked"),
                         chatbot=c["chatbot"], runtime=c["runtime"], divergence=c["divergence"],
                         seed_pnr=c["seed_pnr"], email=EMAIL, phone=PHONE,
                         boundary=any(s["dep"] in BOUNDARY for s in segs),
                         # pnr_common_checks.date_windows compares against MIN(departure) per PNR.
                         # Booking Change acts BEFORE travel, so the flight is normally upcoming; the
                         # mid-journey / both-flown cases legitimately have an already-departed first leg.
                         flight_expect=("past" if min(DEPS[s["dep"]] for s in c["segs"])
                                        < datetime.timedelta(0) else "future")))
    if UNIQ:                                          # opt-in unique, DB-absent passenger names
        uconn = tt_conn()
        U.assign_names(recs, lambda r: r["npax"], uconn, seed=SEED)
        uconn.close()
        for r in recs:                               # write assigned names back into paxs
            for k, nm in enumerate(r.get("pax_names", [])):
                r["paxs"][k]["first"], r["paxs"][k]["last"] = nm
    json.dump(recs, open(OUT, "w"), indent=1)
    seeded = sum(1 for r in recs if r["seed_pnr"])
    print(f"[index] {len(recs)} cases ({len(VOL)} VOL + {len(INVOL)} INVOL) -> {OUT}"
          f"   ({seeded} seeded, {len(recs)-seeded} reserved-unseeded)")
    return recs

def load_index(): return json.load(open(OUT))
def seeded(recs): return [r for r in recs if r["seed_pnr"]]

# ---- scenario + publish -----------------------------------------------------
def px_type(t): return {"ADT":"ADT","CHD":"CHD","INF":"INF","YTH":"CHD"}.get(t, "ADT")

def tickets_of(r): return {int(k): v for k, v in r["tickets"].items()}

def _scn_tickets(r):
    tk = tickets_of(r); out = []; last = None
    for k in range(r["npax"]):
        last = tk.get(k, last); out.append(last)
    return out

def make_scenario(r):
    pax_entries = [dict(type=px_type(p["ptype"]), first_name=p["first"], last_name=p["last"], gender="U",
                        date_of_birth=p["dob"], email=r["email"], phone=r["phone"]) for p in r["paxs"]]
    segs = []
    for j, s in enumerate(r["segs"]):
        dep = s["dep_iso"]
        arr = iso(datetime.datetime.strptime(dep, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=datetime.timezone.utc)
                  + datetime.timedelta(hours=7))
        # publish all-AC / all-HK so the cascade accepts it; UN/OAL/cabin patched post-cascade
        segs.append(dict(carrier="AC", operating_carrier="AC",
                         flight_number=str(870 + j), operating_flight_number=str(870 + j),
                         origin=s["o"], destination=s["d"], bound=s["bound"],
                         dep_local=dep, arr_local=arr, dep_utc=dep, arr_utc=arr,
                         booking_datetime=r["created"], aircraft="320", cabin="Y", status="HK"))
    scn = dict(**{"$schema_version": 2}, scenario_id=r["pnr_id"],
               title=f"{r['tc']}: {r['name']} [{r['pnr']}]", description=r["name"],
               canvas="_canvas/pnr_creation_domestic_ac.json", contains_pii=False,
               identity=dict(pnr=r["pnr"], booking_date=r["booking_date"], type="PNR"),
               point_of_sale=dict(office_id="YTOAA08AA", iata_number="01424012", system_code="AC",
                                  agent_type="AIRLINE", agent_numeric_sign="0001", agent_initials="BC",
                                  duty_code="SU", agent_country="CA", agent_city="YUL"),
               last_modification_comment=f"SIM-{r['tc']}-BC-CRT", creation_comment=f"SIM-{r['tc']}-BC-CRT",
               passengers=pax_entries, segments=segs,
               ticketing=dict(issuance_local_date=r["booking_date"],
                              fare=dict(amount="1450.00", currency="CAD"), ticket_numbers=_scn_tickets(r)),
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
# fare-basis: eligible ends EFF (SC used YAY00EFF); BASIC ends BA -> VBC-NE-04
FARE_BASIS = {"ECO": ("YAY00EFF", "ECO"), "BASIC": ("YAY00BA", "BASIC"), "ITBT": ("ITYAY00", "ITBT")}
COUPON_STATUS = {"OPEN": "OPEN_FOR_USE", "FLOWN": "FLOWN"}

def coupons_json(r, k):
    fb, ff = FARE_BASIS.get(r["fare"], FARE_BASIS["ECO"])
    return [dict(sequenceNumber=j + 1, status=COUPON_STATUS.get(s["coupon"], "OPEN_FOR_USE"),
                 fareBasisCode=fb, fareFamily=dict(code=ff, owner="AC"),
                 soldSegment=dict(bookingClass=r["cabin"], carrierCode=s["mkt"], flightnumber=str(870 + j),
                                  departure=dict(iataCode=s["o"], at=s["dep_iso"]),
                                  arrival=dict(iataCode=s["d"], at=s["dep_iso"])))
            for j, s in enumerate(r["segs"])]

def checkin_data(r, ppid):
    s = r["segs"][-1]        # last (unflown) segment is the checked-in one
    return {"segment": {"id": f"DCS-{r['pnr']}", "pnrSegmentId": f"{r['pnr_id']}-ST-{len(r['segs'])}",
                        "departureAirport": s["o"], "arrivalAirport": s["d"],
                        "departureDateTime": s["dep_iso"], "carrierCode": "AC", "flightNumber": "870",
                        "statusCode": "HK", "class": r["cabin"], "cabin": r["cabin"],
                        "dcsProductType": "ACTIVE_SYNCHRONISED",
                        "passengerDisruption": {"status": "NOT_DISRUPTED"},
                        "legDeliveries": [{"id": f"DCS-{r['pnr']}-{s['o']}", "departureAirport": s["o"],
                                           "arrivalAirport": s["d"], "departureDate": s["dep_iso"][:10],
                                           "operatingFlight": {"carrierCode": "AC", "number": "870"},
                                           "travelCabinCode": r["cabin"],
                                           "acceptance": {"securityNumber": f"{s['o']}-001",
                                                          "status": "ACCEPTED", "acceptanceType": "PRIMARY",
                                                          "isAdvanceAccepted": True, "channel": "WEB",
                                                          "physicalAcceptanceLocation": "CKI"}}]},
            "passengerFirstName": r["paxs"][0]["first"], "passengerLastName": r["paxs"][0]["last"],
            "dateOfBirth": r["paxs"][0]["dob"], "pnrTravelerId": ppid, "dcsPassengerId": f"DCSPAX-{r['pnr']}"}

def rqst_text(ppid, seat, at):
    return json.dumps({"code": "RQST", "subType": "SPECIAL_SERVICE_REQUEST", "serviceProvider": {"code": "AC"},
                       "status": "HK", "creation": {"dateTime": at, "pointOfSale": {"office": {"id": "YTOAA08AA"}}},
                       "seats": [{"number": seat, "characteristicCodes": ["N"],
                                  "traveler": {"type": "stakeholder", "id": ppid, "ref": "processedPnr.travelers"}}],
                       "priceCategory": {"code": "A", "subCode": "0B5"}})

# trip_details.source is varchar(5): GDS/owner code, not the marketing channel.
TD_SOURCE = {"ACO": "AC", "AC_VACATIONS": "AC", "GROUP": "AC", "AEROPLAN": "AC", "ETS": "AC",
             "AC_CARGO": "AC", "OTA": "1S"}
SSR_TEXT = {"EXST": "EXTRA SEAT", "PETC": "SOFT SIDED", "UMNR": "UM10", "INFT": "INFANT OCCUPYING NO SEAT",
            "BSCT": "BASSINET REQ FOR INFT", "CHLD": "CHILD", "EUPG": "FROM-Y/TO-R/AC000000001",
            "YPTU": "YOUNG PASSENGER", "OXYG": "OXYGEN REQUIRED", "AVIH": "ANIMAL IN HOLD",
            "GRPS": "GROUP BOOKING", "VGML": "VEGETARIAN MEAL", "KSML": "KOSHER MEAL",
            "DBML": "DIABETIC MEAL", "UPGD": "UPGRADE", "UPGO": "UPGRADE OP"}

BAG_COLS = ["bag_tag_number","event_type","pnr_id","station_code","flight_departure_station_code",
            "flight_arrival_station_code","flight_departure_date_local","flight_carrier_code","flight_number",
            "bag_tag_status","passenger_name","event_time","event_store_id","source_system_id","carrier_code",
            "inbound_carrier_code","user_name","workstation_name","load_position_name","timestamp","received_at"]

def _epoch_ms(dt): return int((dt - datetime.datetime(1970,1,1,tzinfo=datetime.timezone.utc)).total_seconds()*1000)

def seed_baggage(r, conn):
    """Seed a checked-bag record. bag='loaded' => BAG_LOADED_ON_AIRCRAFT (Loaded); 'notloaded' =>
    only BAG_CREATED/BAG_ACCEPTED (offloaded)."""
    if not r["bag"]: return
    cur = conn.cursor(); pid = r["pnr_id"]
    cur.execute("delete from baggage_updates where pnr_id=%s and user_name='CCT-BC'", (pid,))
    s = r["segs"][-1]
    base = datetime.datetime.strptime(r["created"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=datetime.timezone.utc)
    tag = "0014" + f"{(abs(hash(pid)) % 900000) + 100000}"
    pname = f"{r['paxs'][0]['last']}/{r['paxs'][0]['first']}"
    def row(etype, ts, status, load=None):
        d = dict(bag_tag_number=tag, event_type=etype, pnr_id=pid, station_code=s["o"],
                 flight_departure_station_code=s["o"], flight_arrival_station_code=s["d"],
                 flight_departure_date_local=s["dep_iso"][:10], flight_carrier_code="AC", flight_number="870",
                 bag_tag_status=status, passenger_name=pname, event_time=_epoch_ms(ts),
                 event_store_id=(abs(hash((pid, etype))) % 9_000_000_000) + 1_000_000_000, source_system_id=1,
                 carrier_code="AC", inbound_carrier_code="AC", user_name="CCT-BC", workstation_name="CCT-AUTO",
                 load_position_name=load, timestamp=ts, received_at=ts + datetime.timedelta(seconds=15))
        vals = [d.get(c) for c in BAG_COLS]; ph = ",".join(["%s"] * len(BAG_COLS))
        cur.execute(f"insert into baggage_updates (id,{','.join(BAG_COLS)}) values (gen_random_uuid(),{ph})", vals)
    row("BAG_CREATED", base, "Active")
    row("BAG_ACCEPTED", base + datetime.timedelta(minutes=5), "Accepted")
    if r["bag"] == "loaded":
        row("BAG_ONLOADED", base + datetime.timedelta(minutes=30), "Loaded")
        row("BAG_LOADED_ON_AIRCRAFT", base + datetime.timedelta(minutes=45), "Loaded", load="FWD-1")
        row("BAG_POSITIONED_ON_FLIGHT_LEG", base + datetime.timedelta(minutes=50), "Loaded")
    conn.commit(); cur.close()

def _arr_iso(dep_iso, hours=7):
    return iso(datetime.datetime.strptime(dep_iso, "%Y-%m-%dT%H:%M:%SZ")
               .replace(tzinfo=datetime.timezone.utc) + datetime.timedelta(hours=hours))

def finalize_one(r, conn):
    cur = conn.cursor(); pid, loc = r["pnr_id"], r["pnr"]
    segids = [f"{pid}-ST-{j+1}" for j in range(len(r["segs"]))]
    at = r["created"]
    # 1. tickets (one document per pax, coupons correlated to every segment)
    for k, tk in tickets_of(r).items():
        ppid = f"{pid}-PT-{k+1}"
        cur.execute("""insert into ticket (primary_document_number,pnr_id,passenger_id,ticket_id,
                       document_numbers,issuance_local_date,document_type,coupons)
                       values (%s,%s,%s,%s,ARRAY[%s],%s,'T',%s)
                       on conflict (primary_document_number) do update set coupons=excluded.coupons""",
                    (tk, pid, ppid, f"{tk}-{r['booking_date']}", tk, r["booking_date"],
                     json.dumps(coupons_json(r, k))))
    # 2. DOB + passenger types + has_infant
    for k, p in enumerate(r["paxs"]):
        cur.execute("update passenger set date_of_birth=%s, passenger_type=%s where pnr_id=%s and passenger_id=%s",
                    (p["dob"], p["ptype"], pid, f"{pid}-PT-{k+1}"))
    if any(p["ptype"] == "INF" for p in r["paxs"]):
        cur.execute("update passenger set has_infant=true where pnr_id=%s and passenger_type<>'INF'", (pid,))
    # 3. segment patches: carrier (OAL), bound, status (UN cancelled), cabin, times
    for j, s in enumerate(r["segs"]):
        cur.execute("""update flight_segment set marketing_carrier_code=%s, operating_carrier_code=%s,
                       bound_rph=%s, segment_status=%s, cabin_code=%s, cabin_class=%s,
                       departure_datetime=%s, arrival_datetime=%s,
                       departure_datetime_local=%s, arrival_datetime_local=%s
                       where pnr_id=%s and segment_id=%s""",
                    (s["mkt"], s["op"], s["bound"], s["status"], r["cabin"], r["cabin"],
                     s["dep_iso"], _arr_iso(s["dep_iso"]),
                     s["dep_iso"][:19].replace("T", " "), _arr_iso(s["dep_iso"])[:19].replace("T", " "),
                     pid, segids[j]))
    # 4. SSRs (declared + RQST seat)
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
    if r["seat"]:
        n += 1; ppid = f"{pid}-PT-1"
        cur.execute("""insert into special_service_request
            (ssr_id,pnr_id,code,passenger_id,segment_id,status,text,quantity,is_removed,received_at,last_modified)
            values (%s,%s,'RQST',%s,%s,'HK',%s,1,false,%s,%s) on conflict (ssr_id) do nothing""",
            (f"{pid}-QA-{n}", pid, [ppid], [segids[-1]], rqst_text(ppid, r["seat"], at), at, at))
    # 5. checked-in
    cur.execute("delete from journey_updates where pnr_id=%s and entity_id like %s", (pid, "qa-bc-%"))
    if r["checkin"]:
        cur.execute("""insert into journey_updates
            (id,pnr_id,pnr,entity,entity_id,entity_version,event_action,event_type,data,last_modified,received_at)
            values (%s,%s,%s,'CM',%s,'1','UPDATED','CHECK_IN',%s,%s,%s)""",
            (str(uuid.uuid4()), pid, loc, f"qa-bc-{loc}", json.dumps(checkin_data(r, f"{pid}-PT-1")), at, at))
    # 6. booking source: eds booking_context (authoritative) + trip_details.source (fallback)
    grp = r["src"] == "GROUP"
    bc = {"bookingSource": r["src"], "bookingType": "REVENUE",
          "bookingSubtype": "GROUP" if grp else "REVENUE", "gdsLocator": "AMADEUS"}
    cur.execute("update eds_pnr_output set booking_context=%s where pnr_id=%s", (json.dumps(bc), pid))
    cur.execute("update trip_details set source=%s, travel_type=%s, group_details=%s where pnr_id=%s",
                (TD_SOURCE.get(r["src"], "AC"), "GROUP" if grp else "REGULAR",
                 json.dumps({"size": 10, "name": "BC QA GROUP", "sizeTaken": r["npax"],
                             "sizeRemaining": 10 - r["npax"]}) if grp else None, pid))
    # 7. baggage
    # 8. one ACTIVE trip per locator
    cur.execute("update trip set status='INACTIVE' where pnr=%s and pnr_id<>%s and status='ACTIVE'", (loc, pid))
    cur.execute("update trip set status='ACTIVE', created_at=%s where pnr_id=%s", (r["created"], pid))
    conn.commit(); cur.close()
    seed_baggage(r, conn)

def redate(recs, conn):
    now = datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0)
    cur = conn.cursor(); n = 0
    for r in recs:
        if not (r["seed_pnr"] and r["boundary"]): continue
        for j, s in enumerate(r["segs"]):
            s["dep_iso"] = iso(now + DEPS[s["dep"]])
            cur.execute("""update flight_segment set departure_datetime=%s, arrival_datetime=%s,
                           departure_datetime_local=%s, arrival_datetime_local=%s
                           where pnr_id=%s and segment_id=%s""",
                        (s["dep_iso"], _arr_iso(s["dep_iso"]),
                         s["dep_iso"][:19].replace("T", " "), _arr_iso(s["dep_iso"])[:19].replace("T", " "),
                         r["pnr_id"], f"{r['pnr_id']}-ST-{j+1}"))
        n += 1
    conn.commit(); cur.close()
    json.dump(recs, open(OUT, "w"), indent=1)
    print(f"[redate] re-anchored {n} boundary PNRs to {iso(now)}")

# ---- VOL verification (DB -> BOOKING_CHANGE payload -> live endpoint) --------
def vol_eligibility(r, conn):
    p = SC.db_payload(r["pnr_id"], r["bound"], conn)
    if p is None: return {"err": "no trip row"}
    p["changeTrigger"]["trigger"] = "BOOKING_CHANGE"
    res = SC.call_endpoint(p)
    if "err" in res: return res
    be = (res.get("data") or {}).get("boundEligibility") or {}
    segs = be.get("segmentsEligibility") or []
    return {"elig": be.get("isBoundEligible"), "reason": (be.get("reasonCode") or {}).get("code"),
            "val": be.get("validationStatus") or {}, "bookingSource": (res.get("data") or {}).get("bookingSource"),
            "segs": [{"seg": s["segmentId"], "elig": s["isSegmentEligible"],
                      "rc": (s.get("reasonCode") or {}).get("code")} for s in segs]}

# ---- main -------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(); ap.add_argument("phase")
    ap.add_argument("--flow", default="all", choices=["all", "vol", "invol"])
    ap.add_argument("--start", type=int, default=0); ap.add_argument("--end", type=int, default=10**9)
    a = ap.parse_args()
    if a.phase == "index": build_index(); return
    recs = load_index()
    sl = seeded(recs)
    if a.flow != "all": sl = [r for r in sl if r["flow"] == a.flow]
    sl = sl[a.start:a.end]
    if a.phase == "publish":
        ok = 0
        for i, r in enumerate(sl):
            good, log = render_publish_one(r); ok += good
            print(f"  [{a.start+i:3}] {r['pnr_id']} {r['tc']:28} {'OK' if good else 'FAIL ' + log[-160:]}", flush=True)
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
            finalize_one(r, conn); print(f"  [{a.start+i:3}] {r['pnr_id']} {r['tc']:28} finalized", flush=True)
        conn.close(); print(f"[finalize] {len(sl)} done")
    elif a.phase == "redate":
        conn = tt_conn(); redate(recs, conn); conn.close()
    elif a.phase == "verify":
        conn = tt_conn(); ok = 0; bad = []; nvol = 0
        for r in sl:
            if r["flow"] != "vol" or r["exp"] is None:
                continue
            nvol += 1
            g = vol_eligibility(r, conn)
            good = (g.get("reason") == r["exp"])
            ok += good
            if not good: bad.append((r["tc"], r["pnr"], f"exp {r['exp']}", f"got {g.get('reason')} {g.get('err','')}"))
            print(f"  {r['tc']:20} {r['pnr']} bound{r['bound']} -> {g.get('reason')} "
                  f"elig={g.get('elig')} {'OK' if good else '<<< MISMATCH'}", flush=True)
        conn.close()
        print(f"[verify] {ok}/{nvol} VOL cases match expected (INVOL is booking-side only)")
        for b in bad: print("   ", b)
    else:
        print("phases: index publish checkcascade finalize redate verify   [--flow vol|invol|all]")

if __name__ == "__main__":
    main()
