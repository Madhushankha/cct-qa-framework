#!/usr/bin/env python3
import os
import _cctdb
"""Build NAME CORRECTION test PNRs in the CRT environment + verify eligibility.

Unlike FD/ANC (which pin a pre-computed DDS the /dds/output endpoint reads), Name
Correction eligibility is computed LIVE and STATELESSLY by the rule engine:
    POST /eligibility-service/execute-with-mapping   (trigger NAME_CORRECTION)
    header x-api-key: <booking-change-eligibility-api-key>
The caller supplies the full EDS-shaped pnrData; the service returns
    data.pnrEligibility.{isPnrEligible, processingWindow, reasonCode, validationStatus,
                         passengerEligibility[]}
So there is NO DDS to pin. This builder:
  * cascades each booking into trip-tracer (scenario_engine -> CRT Kafka) so the
    chatbot can RETRIEVE the PNR + send OTP (email/phone from eds contact),
  * finalizes ticket rows + DOB + passenger_type/has_infant patches,
  * supersedes stale duplicate ACTIVE trips for the same locator,
  * VERIFIES eligibility by POSTing each case's designed pnrData to the live endpoint
    and asserting the expected outcome (isPnrEligible / processingWindow / reasonCode).

Empirically-confirmed rule model (CRT, 2026-07-08):
  ruleCarrierMix (NC-NE-01)     : every non-UN segment's MARKETING carrier must == AC
  ruleBookingChannel (NC-NE-03) : source whitelist is {AC_ONLINE, AC_MOBILE}; anything
                                  else (AC_VACATIONS/OTA/AEROPLAN/EMPLOYEE/FLIGHT_PASS/
                                  GDS/AC_CARGO/GROUP/...) fails
  ruleTimeToDeparture (NC-NE-04): fails when the first segment has DEPARTED **or** departs
                                  within 24h (OUT_OF_SCOPE) -- Window 3 IS enforced by the
                                  service. EXCEPTION: if the booking itself is <=24h old
                                  (Window 1 / VOID), the service returns VOID+ELIGIBLE even
                                  when the flight is <24h away -- i.e. W1 wins over W3.
                                  TC042 expects the opposite; gate that in the chatbot.
  rulePassengerType (NC-NE-05)  : passengerType==YTH or SSR UMNR/YPTU -> fail (isYouth/isUmnr)
  ruleCouponStatus (NC-NE-06)   : needs an OPEN_FOR_USE coupon correlated to a future segment
  ruleCorrectionLimits          : NOT reproducible statelessly -> always passes at the
                                  endpoint; prior-correction is a chatbot/DBaaS gate.
  processingWindow: VOID (booking <=24h old = Window 1) / NON_VOID (Window 2) / OUT_OF_SCOPE.
CHATBOT-LEVEL gates (endpoint returns ELIGIBLE; routing happens in the agentic layer):
  Group Desk, Aeroplan-LINKED (loyalty), checked-in, EXST/CBBG SSR, prior-correction,
  name-transfer detection, and W3-over-W1 priority. Noted per case (chatbot_note).

Phases (idempotent / resumable):
  index        -> _NC_crt_index.json  (locators + tickets from CASES)
  publish      render scenario -> publish booking to CRT PNR Kafka
  checkcascade how many landed in trip-tracer
  finalize     ticket + DOB + passenger_type/has_infant + supersede dup ACTIVE trips
  verify       POST designed pnrData to eligibility endpoint, assert expected outcome
Usage: AWS_PROFILE=ac-cct-crt python3 nc_crt_build.py <phase> [--start N] [--end N]
"""
import json, os, sys, subprocess, argparse, ssl, urllib.request
import boto3, psycopg2, datetime
import crt_uniqnames as U
UNIQ = os.environ.get("CRT_UNIQ_NAMES") == "1"   # opt-in: shared unique-name assignment (default OFF)

KB   = os.environ.get("CCTQA_DATAGEN_ROOT",
                      os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SENG = f"{KB}/scripts/scenario_engine.py"
PUB  = f"{KB}/scripts/publish_raw.py"
CANVAS = f"{KB}/scenarios/_canvas/pnr_creation_domestic_ac.json"
WORK = "/tmp/cctqa-datagen/nc_work"
SET  = os.environ.get("NC_SET","")            # "" = original named-locator set; e.g. "set2"
_sfx = f"_{SET}" if SET else ""
SCENW=f"{WORK}/scenarios{_sfx}"; NDJW=f"{WORK}/ndjson{_sfx}"
for d in (SCENW,NDJW): os.makedirs(d, exist_ok=True)
OUT = os.environ.get("NC_OUT", f"{WORK}/_NC_crt{_sfx}_index.json")

CRT = dict(
  profile=os.environ.get("AWS_PROFILE","ac-cct-crt"), region="ca-central-1",
  brokers=("b-1.accctmskcrtcac1.05hf7o.c4.kafka.ca-central-1.amazonaws.com:9092,"
           "b-2.accctmskcrtcac1.05hf7o.c4.kafka.ca-central-1.amazonaws.com:9092,"
           "b-3.accctmskcrtcac1.05hf7o.c4.kafka.ca-central-1.amazonaws.com:9092"),
  topic="emh-dev.ALTEA-PNRDATA-UAT",
  tt_host="ac-cct-trip-tracer-rds-cluster-crt-cac1.cluster-cxqe2wacy866.ca-central-1.rds.amazonaws.com",
  tt_db="trip-tracer", tt_user="dbadmin", tt_pass=os.environ.get("CCT_TRIPTRACER_PASSWORD", ""),
  endpoint="https://rule-engine-platform-service.ac-cct-crt.cloud.aircanada.com/eligibility-service/execute-with-mapping",
  api_key="6a1a7245-c87b-494f-b53a-e1c4277add62",
)
EMAIL=os.environ.get("CRT_EMAIL","lahiru@ae-qa1-aircanada.mailinator.com")
PHONE=os.environ.get("CRT_PHONE","+94712534323")
DOB="1986-04-23"
TPREFIX=os.environ.get("NC_TPREFIX","014302")          # ticket series
TBASE0 =int(os.environ.get("NC_TBASE","9000000"))     # doc-number block (must be verified free)
def docnum(r,k): return f"{TPREFIX}{r['tbase']+k:07d}"  # unique 13-digit ticket doc per pax
# NC_SEED set -> generate FRESH random locators (avoids the pre-existing-locator EDS straggler);
# unset -> use the named magic locators from the xlsx (NCHAP1, NCW2C2, ...).
NC_SEED=os.environ.get("NC_SEED")
TODAY=datetime.datetime.now(datetime.timezone.utc).date()  # dynamic — VOID needs booking <24h old
# window date anchors (relative to TODAY)
W1_BOOK=TODAY.isoformat()                                   # booking today -> VOID
W2_BOOK=(TODAY-datetime.timedelta(days=10)).isoformat()     # booking 10d ago -> NON_VOID
FUT_FLIGHT=(TODAY+datetime.timedelta(days=30)).isoformat()  # flight +30d
SOON_FLIGHT=(TODAY+datetime.timedelta(days=1)).isoformat()  # flight tomorrow (future, chatbot W3 <24h)
DEP_FLIGHT=(TODAY-datetime.timedelta(days=1)).isoformat()   # flight yesterday -> OUT_OF_SCOPE
# Window-3 needs a real *datetime* < 24h from now (a bare date at a fixed hour is >24h out).
# NOTE time-sensitive: once these depart they are "departed", which is ALSO OUT_OF_SCOPE,
# so the endpoint verdict (NC-NE-04) stays stable — only the "departs in Nh" narrative drifts.
_NOW=datetime.datetime.now(datetime.timezone.utc)
def _iso(dt): return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
SOON_DT   =_iso(_NOW+datetime.timedelta(hours=8))   # TC040 NCW3S1: "departs in 8 hours"
OVERLAP_DT=_iso(_NOW+datetime.timedelta(hours=6))   # TC042 NCBND3: "departs in 6 hours"
DEP_DT    =_iso(_NOW-datetime.timedelta(hours=30))  # TC041 NCDEP1: already departed

_sess=boto3.Session(profile_name=CRT["profile"], region_name=CRT["region"])
def tt_conn(): return _cctdb.trip_tracer(CRT["tt_host"], profile=CRT.get("profile"))

# ---- CASES ------------------------------------------------------------------
# pax entry: (first,last,ptype[,opts]); opts: ssr=[..], loyalty=True, corrected=True,
#            no_ticket=True, coupon="VOID". ptype in ADT/CHD/INF/YTH.
# window: "W1"(VOID) | "W2"(NON_VOID) | "W3future"(chatbot-W3, endpoint EL NON_VOID) |
#         "W3overlap"(created<24h+flight<24h, endpoint EL VOID) | "DEP"(departed, NC-NE-04)
# carriers: list of (op,mkt) per segment. default [("AC","AC")].
# exp = (isPnrEligible, processingWindow, reasonCode)
def C(tc,pri,feat,name,pnr,paxs,exp,window="W2",src="AC_ONLINE",office="YTOAA08AA",
      system="AC",carriers=None,group=False,chatbot=""):
    return dict(tc=tc,pri=pri,feat=feat,name=name,pnr=pnr,paxs=paxs,window=window,src=src,
                office=office,system=system,carriers=carriers or [("AC","AC")],group=group,
                exp_elig=exp[0],exp_win=exp[1],exp_reason=exp[2],chatbot=chatbot)
EL=lambda w: (True, ("VOID" if w in ("W1","W3overlap") else "NON_VOID"), "NC-EL-01")
CASES=[
 # ---- Happy Path (eligible) ----
 C("NameCorrection_TC001","P3","Happy","W1 single 0-doc nickname (NCHAP1)","NCHAP1",[("SARAH","CHEN","ADT")],EL("W1"),"W1"),
 C("NameCorrection_TC002","P3","Happy","W2 multi-pax 1-doc Persona (NCW2C2)","NCW2C2",[("MICHAEL","TORRES","ADT"),("MARIA","TORRES","ADT"),("CARLOS","TORRES","ADT"),("SOFIA","TORRES","ADT")],EL("W2")),
 C("NameCorrection_TC003","P1","Happy","W2 single 2-doc legal/marital (NCLGL1)","NCLGL1",[("JANE","SMITH","ADT")],EL("W2")),
 C("NameCorrection_TC004","P3","Happy","W1 single 0-doc first-name typo","NCTYP1",[("JOHNN","DOELL","ADT")],EL("W1"),"W1"),
 C("NameCorrection_TC005","P3","Happy","W2 single passport upload","NCPP01",[("EMMA","STOWE","ADT")],EL("W2")),
 C("NameCorrection_TC018","P3","Happy","Middle name correction, no docs","NCMID1",[("HENRY","JAMES","ADT")],EL("W1"),"W1"),
 C("NameCorrection_TC019","P3","Happy","Multi-pax, second passenger selected","NCMP21",[("IVY","STONE","ADT"),("JACK","STONE","ADT")],EL("W2")),
 C("NameCorrection_TC023","P3","Happy","Passport upload validation success","NCPAS1",[("NINA","HALL","ADT")],EL("W2")),
 C("NameCorrection_TC025","P3","Happy","Successful retry after Persona fail","NCRTY1",[("PAM","LEIGH","ADT")],EL("W2")),
 C("NameCorrection_TC027","P3","Happy","W1 last-name typo, no docs","NCLTP1",[("RITA","MOON","ADT")],EL("W1"),"W1"),
 C("NameCorrection_TC057","P3","Happy","0-doc typo/nickname, Persona skipped","NCNK01",[("ROB","ERTSON","ADT")],EL("W1"),"W1"),
 C("NameCorrection_TC058","P3","Happy","1 supporting document required","NCD101",[("MICHAEL","SMYTHE","ADT")],EL("W2")),
 C("NameCorrection_TC059","P3","Happy","2 supporting documents required","NCD201",[("JANE","OSBORNE","ADT")],EL("W2")),
 C("NameCorrection_TC065","P3","Happy","1-doc first attempt fail then success","NCRT11",[("IAN","COOK","ADT")],EL("W2")),
 C("NameCorrection_TC066","P3","Happy","2-doc both pass first attempt","NCRT21",[("JULIA","BAKER","ADT")],EL("W2")),
 C("SeatChange_TC049","P3","Happy","Slight misspelling passes identification (XYZ789)","XYZ789",[("HASSAN","ALI","ADT")],EL("W2")),
 # ---- Ineligible (service-level) ----
 C("NameCorrection_TC007","P2","Ineligible","Young Passenger (YP) blocked","NCYP01",[("TOMMY","YOUNG","YTH")],(False,"NON_VOID","NC-NE-05"),chatbot="rulePassengerType fail (isYouth)"),
 C("NameCorrection_TC008","P2","Ineligible","Unaccompanied Minor (UM) blocked","NCUM01",[("KIDDO","MINOR","CHD",{"ssr":["UMNR"]})],(False,"NON_VOID","NC-NE-05"),chatbot="rulePassengerType fail (isUmnr)"),
 C("NameCorrection_TC015","P2","Ineligible","Booking outside supported correction window","NCOOW1",[("ERIN","GRAYSON","ADT")],(False,"OUT_OF_SCOPE","NC-NE-04"),"DEP"),
 C("NameCorrection_TC020","P2","Ineligible","Unsupported booking channel (OTA)","NCOTA1",[("KARL","ROSS","ADT")],(False,"NON_VOID","NC-NE-03"),src="OTA",office="OTAXX001",system="1B"),
 C("NameCorrection_TC029","P2","Ineligible","Air Canada Vacations -> ACV live agent (NCVAC1)","NCVAC1",[("CARLOS","MARTINEZ","ADT")],(False,"NON_VOID","NC-NE-03"),src="AC_VACATIONS",office="YULAC011V",chatbot="ACV -> Live Agent (ACV queue)"),
 C("NameCorrection_TC030","P2","Ineligible","Full OAL/Star -> End (NCOAL1)","NCOAL1",[("HANS","MUELLER","ADT")],(False,"NON_VOID","NC-NE-01"),carriers=[("LH","LH")],chatbot="Full non-AC -> End Flow"),
 C("NameCorrection_TC031","P2","Ineligible","Mixed AC+OAL -> live agent (NCPRT1)","NCPRT1",[("DAVID","PARK","ADT")],(False,"NON_VOID","NC-NE-01"),carriers=[("AC","AC"),("LH","LH")],chatbot="Partial non-AC -> Live Agent"),
 C("NameCorrection_TC032","P2","Ineligible","Group PNR -> Group Travel Desk (NCGRP1)","NCGRP1",[("GARY","GROUPE","ADT"),("GINA","GROUPE","ADT")],(False,"NON_VOID","NC-NE-03"),src="GROUP",office="GC1AC010",group=True,chatbot="Group -> Group Travel Desk"),
 C("NameCorrection_TC033","P2","Ineligible","AC Cargo booking blocked (NCCGO1)","NCCGO1",[("CARGO","SHIPPER","ADT")],(False,"NON_VOID","NC-NE-03"),src="AC_CARGO",office="YULCG001"),
 C("NameCorrection_TC051","P2","Ineligible","Aeroplan channel -> LAH","NCAPC1",[("XAVIER","POOLE","ADT")],(False,"NON_VOID","NC-NE-03"),src="AEROPLAN",office="YULAP001",chatbot="Aeroplan channel -> Live Agent"),
 C("NameCorrection_TC052","P2","Ineligible","Employee travel program blocked (OID ES/EP/OT/EC)","NCEMP1",[("YOLA","SANO","ADT")],(False,"NON_VOID","NC-NE-03"),src="EMPLOYEE",office="ESYUL001"),
 C("NameCorrection_TC053","P2","Ineligible","Flight Pass program blocked (OID FP)","NCFP01",[("ZANE","FALLON","ADT")],(False,"NON_VOID","NC-NE-03"),src="FLIGHT_PASS",office="YULAC01FP"),
 C("NameCorrection_TC054","P2","Ineligible","Non-1A GDS blocked (OID 1B/1E/.../1S)","NCGDS1",[("AMY","NOLLE","ADT")],(False,"NON_VOID","NC-NE-03"),src="GDS",office="1SGSAB21",system="1S"),
 # ---- Failure Handling (runtime; eligible booking) ----
 C("NameCorrection_TC010","P2","Failure","Persona validation failure","NCPFL1",[("ALICE","BROWNE","ADT")],EL("W2"),chatbot="runtime: Persona returns fail"),
 C("NameCorrection_TC011","P2","Failure","OTP authentication failure","NCOTP1",[("BOB","GREENE","ADT")],EL("W2"),chatbot="runtime: wrong OTP"),
 # TC012 invalid PNR -> intentionally NOT seeded (see report)
 C("NameCorrection_TC013","P2","Failure","Incorrect surname during identification","NCSUR1",[("CAROL","WHITMAN","ADT")],EL("W2"),chatbot="runtime: tester enters wrong surname"),
 C("NameCorrection_TC014","P2","Failure","Persona upload abandoned","NCABN1",[("DAVE","BLACKE","ADT")],EL("W2"),chatbot="runtime: user abandons Persona"),
 C("NameCorrection_TC016","P2","Failure","Bedrock cannot classify correction","NCBRK1",[("FRANK","BLUETT","ADT")],EL("W2"),chatbot="runtime: ambiguous correction"),
 C("NameCorrection_TC017","P2","Failure","Amadeus update failure after validation","NCAMF1",[("GRACE","GOLDING","ADT")],EL("W2"),chatbot="runtime: Amadeus update fails"),
 C("NameCorrection_TC021","P2","Failure","OTP expired before submission","NCEXP1",[("LARA","FOXALL","ADT")],EL("W2"),chatbot="runtime: OTP expiry"),
 C("NameCorrection_TC022","P2","Failure","Persona service unavailable","NCPSU1",[("MARK","REEDER","ADT")],EL("W2"),chatbot="runtime: Persona 5xx"),
 C("NameCorrection_TC024","P2","Failure","Invalid government-issued ID uploaded","NCBID1",[("OSCAR","KINGSLEY","ADT")],EL("W2"),chatbot="runtime: invalid ID"),
 C("NameCorrection_TC026","P2","Failure","State machine processing timeout","NCTMO1",[("QUINN","DAYES","ADT")],EL("W2"),chatbot="runtime: >2h timeout"),
 C("NameCorrection_TC028","P2","Failure","User declines final confirmation","NCDEC1",[("SAM","NASHE","ADT")],EL("W2"),chatbot="runtime: user cancels"),
 C("NameCorrection_TC060","P2","Failure","0-doc, Amadeus fails -> live agent","NC0DA1",[("DENISE","ROYCE","ADT")],EL("W1"),"W1",chatbot="runtime: 0-doc then Amadeus fail"),
 C("NameCorrection_TC061","P2","Failure","1-doc Persona fail 3x -> email","NCP3F1",[("EVAN","HUNTER","ADT")],EL("W2"),chatbot="runtime: 3x Persona fail -> namecorrectiondenom@aircanada.ca"),
 C("NameCorrection_TC062","P2","Failure","2-doc, doc2 fails 3x -> live agent","NCP3D1",[("FIONA","WARDLE","ADT")],EL("W2"),chatbot="runtime: doc2 3x fail"),
 C("NameCorrection_TC063","P2","Failure","1-doc dispute -> live agent","NCDSP1",[("GEORGE","BELLE","ADT")],EL("W2"),chatbot="runtime: user disputes doc requirement"),
 C("NameCorrection_TC064","P2","Failure","2-doc dispute -> live agent","NCDSP2",[("HELEN","WOODES","ADT")],EL("W2"),chatbot="runtime: user disputes docs"),
 # ---- Ineligible (special) already above; Edge cases below ----
 C("NameCorrection_TC006","P2","Ineligible","Previous correction already exists","NCPRV1",[("WANG","LIANG","ADT",{"corrected":True})],EL("W2"),chatbot="prior-correction: DBaaS/chatbot blocks (endpoint EL)"),
 C("NameCorrection_TC009","P2","Ineligible","Aeroplan-linked booking blocked","NCAER1",[("JENNIFER","LIUANG","ADT",{"loyalty":True})],EL("W2"),chatbot="Aeroplan-linked -> Live Agent (endpoint EL)"),
 # ---- Edge Cases ----
 C("NameCorrection_TC034","P2","Edge","Checked-in pax -> live agent (W2)","NCCHK1",[("TINA","WELLS","ADT")],EL("W2"),chatbot="checked-in -> Live Agent (endpoint EL)"),
 C("NameCorrection_TC035","P2","Edge","Infant eligible under same rules","NCINF1",[("ROSA","LOPEZ","ADT"),("BABY","LOPEZ","INF")],EL("W2"),chatbot="infant eligible"),
 C("NameCorrection_TC036","P2","Edge","Romanized Chinese name, 1 doc via email","NCCHN1",[("LIHUA","WANG","ADT")],EL("W2"),chatbot="romanized -> 1 doc via email"),
 C("NameCorrection_TC037","P2","Edge","Handwritten doc -> manual review","NCHWD1",[("URSULA","VOGT","ADT")],EL("W2"),chatbot="handwritten -> manual review"),
 C("NameCorrection_TC038","P2","Edge","Special chars in name (Jose Garcia)","NCSPC1",[("JOSE","GARCIA","ADT")],EL("W2"),chatbot="special chars scrubbed in Persona"),
 C("NameCorrection_TC039","P2","Edge","EXST/CBBG SSR -> live agent","NCSSR1",[("VERA","COXWELL","ADT",{"ssr":["EXST"]})],EL("W2"),chatbot="EXST/CBBG -> Live Agent (endpoint EL)"),
 C("NameCorrection_TC040","P2","Edge","First segment <24h -> live agent (NCW3S1)","NCW3S1",[("PRIYA","SHARMA","ADT")],(False,"OUT_OF_SCOPE","NC-NE-04"),"W3future",chatbot="flight departs in ~8h -> Window 3 -> Live Agent. Service enforces (NC-NE-04)."),
 C("NameCorrection_TC041","P2","Edge","First segment departed -> live agent (NCDEP1)","NCDEP1",[("ROBERT","KIM","ADT")],(False,"OUT_OF_SCOPE","NC-NE-04"),"DEP",chatbot="departed -> Live Agent (Window 3)"),
 C("NameCorrection_TC042","P2","Edge","Window 3 priority over Window 1 (NCBND3)","NCBND3",[("RITA","PATEL","ADT")],(True,"VOID","NC-EL-01"),"W3overlap",chatbot="DIVERGENCE: TC042 expects Window 3 to win, but booked 2h ago + flight in 6h -> service returns VOID/ELIGIBLE (Window 1 wins). W3-over-W1 priority is NOT enforced by the eligibility service; must be gated in the chatbot. Raise with product."),
 C("NameCorrection_TC043","P2","Edge","Entirely different name (transfer) -> live agent","NCXFR1",[("NICK","SMITH","ADT")],EL("W2"),chatbot="name-transfer detected at name capture -> Live Agent"),
 C("NameCorrection_TC044","P2","Edge","Already-corrected pax blocked in new session (NCDUP3)","NCDUP3",[("MARIA","GARCIA","ADT",{"corrected":True})],EL("W2"),chatbot="prior-correction: DBaaS/chatbot blocks (endpoint EL)"),
 C("NameCorrection_TC045","P2","Edge","All 4 pax corrected sequentially, 1 session (NCALL4)","NCALL4",[("ALICE","BROWN","ADT"),("BOB","BROWN","ADT"),("CAROL","BROWN","ADT"),("DAVE","BROWN","ADT")],EL("W2")),
 C("NameCorrection_TC046","P2","Edge","Each pax in separate session (NCSEQ4)","NCSEQ4",[("TOM","LEE","ADT"),("AMY","LEE","ADT"),("SAM","LEE","ADT"),("ZOE","LEE","ADT")],EL("W2")),
 C("NameCorrection_TC047","P2","Edge","2 pax session 1, 2 pax session 2 (NCMIX4)","NCMIX4",[("EVA","WHITE","ADT"),("MAX","WHITE","ADT"),("LILY","WHITE","ADT"),("JACK","WHITE","ADT")],EL("W2")),
 C("NameCorrection_TC048","P2","Edge","3 pax session 1, 4th in separate (NC3P1S)","NC3P1S",[("ANA","CRUZ","ADT"),("BEN","CRUZ","ADT"),("MIA","CRUZ","ADT"),("LEO","CRUZ","ADT")],EL("W2")),
 C("NameCorrection_TC049","P2","Edge","Different doc requirements per pax (NCDC31, xlsx: NCDOC31)","NCDC31",[("SARAH","MILLER","ADT"),("JAMES","MILLER","ADT")],EL("W2")),
 C("NameCorrection_TC050","P2","Edge","Codeshare AC-operated, partner-marketed","NCCDS1",[("WENDY","PALMER","ADT")],(False,"NON_VOID","NC-NE-01"),carriers=[("AC","LH")],chatbot="DIVERGENCE: BRD expects eligible (AC-operated codeshare) but service fails carrier-mix on marketing carrier != AC"),
 C("NameCorrection_TC055","P2","Edge","First name corrected, last name still correctable","NCFNL1",[("BRAD","COLE","ADT",{"corrected":True})],EL("W2"),chatbot="per-field limit: last-name still allowed (chatbot/DBaaS)"),
 C("NameCorrection_TC056","P2","Edge","Session expiry during Persona","NCSES1",[("CARA","DUNNE","ADT")],EL("W2"),chatbot="runtime: chatbot session timeout during Persona"),
]
# TC012 intentionally unseeded
UNSEEDED=[("NameCorrection_TC012","Invalid PNR during identification — tests a NON-existent booking; no PNR to seed.")]

# ---- window date helpers ----------------------------------------------------
def window_dates(window):
    """returns (booking_date, created_iso, dep_date, is_departed, dep_iso)
    dep_iso (when set) pins the FIRST segment's exact departure datetime — required for the
    Window-3 cases, where a bare date at a fixed hour would land >24h out."""
    if window=="W1":         return W1_BOOK, _iso(_NOW-datetime.timedelta(hours=2)).replace("Z",".000Z"), FUT_FLIGHT, False, None
    if window=="W3overlap":  # booked <24h ago AND flight <24h away -> W3 must beat W1
        created=_iso(_NOW-datetime.timedelta(hours=2))
        return created[:10], created, OVERLAP_DT[:10], False, OVERLAP_DT
    if window=="W3future":   return W2_BOOK, W2_BOOK+"T10:00:00.000Z", SOON_DT[:10], False, SOON_DT
    if window=="DEP":        return W2_BOOK, W2_BOOK+"T10:00:00.000Z", DEP_DT[:10], True, DEP_DT
    return W2_BOOK, W2_BOOK+"T10:00:00.000Z", FUT_FLIGHT, False, None   # W2

def seg_times(dep_date, segidx, dep_iso=None):
    if dep_iso and segidx==0:
        d=datetime.datetime.strptime(dep_iso,"%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=datetime.timezone.utc)
        a=d+datetime.timedelta(hours=3)
        return d.strftime("%Y-%m-%dT%H:%M:%S"), a.strftime("%Y-%m-%dT%H:%M:%S"), _iso(d), _iso(a)
    h=8+segidx*4
    dl=f"{dep_date}T{h:02d}:30:00"; al=f"{dep_date}T{h+3:02d}:45:00"
    du=f"{dep_date}T{h+4:02d}:30:00Z"; au=f"{dep_date}T{h+7:02d}:45:00Z"
    return dl,al,du,au

# ---- index ------------------------------------------------------------------
# ---- fresh-name planning (NC_SEED sets) -------------------------------------
# Names must not collide with any other set. Cases whose NAME carries test meaning get a
# semantically-equivalent replacement rather than a random one.
_FIRSTS=["ELENA","MARCUS","NADIA","OLIVER","PRIYA","QUENTIN","ROSALIE","TOBIAS","URSULA","VICTOR",
         "WENDY","XAVIER","YASMIN","ZANE","ADRIAN","BIANCA","CEDRIC","DELIA","EMILIO","FIONA",
         "GAVIN","HELENA","IVAN","JOSEPHINE","KAMAL","LOUISA","MATEO","NORA","OSCAR","PAOLA",
         "RAFAEL","SIENNA","THEO","VALERIE","WESLEY","YOLANDA","ARTHUR","BEATRICE","CONRAD","DIANA",
         # headroom (added when the 40x40 grid ran dry at set10)
         "AUGUSTIN","BRIGITTE","CASIMIR","DOROTHEA","EDMUND","FELICITY","GERALDINE","HORACE",
         "ISOLDE","JULIUS","KATRINA","LEOPOLD","MARIANNE","NIKOLAI","OTTILIE","PERCIVAL",
         "ROSAMUND","SEBASTIAN","THEODORA","ULRICH","VERONIKA","WILHELM","XIMENA","YVETTE",
         "ZACHARY","ANNIKA","BARNABY","CORDELIA","DESMOND","EULALIA","FERDINAND","GWENDOLYN",
         "HUMPHREY","IMOGEN","JASPER","KRISTIANE","LAZARUS","MIRABEL","NATHANIEL","OPHELIA"]
_LASTS =["OKONKWO","VANCE","LINDQVIST","BARRERA","FONTAINE","HALVORSEN","IBARRA","KOWALCZYK",
         "MARCHETTI","NAKAMURA","OYELARAN","PRZYBYLSKI","QUIROGA","ROSSETTI","SVENSSON","TANAKA",
         "URBANOWICZ","VILLANUEVA","WEATHERBY","ZIELINSKI","ASHFORD","BRENNAN","CALDERON","DUBOIS",
         "ELLSWORTH","FAIRBANKS","GALLAGHER","HOLLANDER","IRIARTE","JANSEN","KILBRIDE","LARSSON",
         "MONTGOMERY","NORDSTROM","ODUYA","PENHALIGON","RADCLIFFE","STRANDBERG","THORNBURY","VESTERGAARD",
         # headroom
         "ABERNATHY","BLACKWOOD","CARRINGTON","DELACROIX","EASTERBROOK","FITZGERALD","GRIMALDI",
         "HAWTHORNE","INGERSOLL","JOHANSSON","KENSINGTON","LOCKWOOD","MERRIWEATHER","NIGHTINGALE",
         "OSTROWSKI","PEMBERTON","QUARTERMAIN","RUTHERFORD","SHACKLETON","TREMBLAY","UNDERWOOD",
         "VANDERBILT","WHITFIELD","YARBOROUGH","ZAVALA","ARMITAGE","BRAITHWAITE","CHURCHILL",
         "DRUMMOND","ETHERIDGE","FAULKNER","GOODWIN","HARGREAVES","ISHERWOOD","JEFFERSON",
         "KILPATRICK","LANGFORD","MACALLISTER","NEWCOMBE","OAKHURST"]
# TC -> semantic name CATEGORY = (first_pool, last_pool). plan_paxs picks a FREE first x last
# combination (>=100 combos each) -> scales across many sets without the fixed-12 pool exhausting.
_SPECIAL_CAT={
 "NameCorrection_TC036":(  # romanized Chinese
   ["XIUYING","WEI","MINJUN","HAORAN","FANG","JING","LEI","NA","TAO","YAN","HUI","PENG","QIANG","MEI","JUN","LING"],
   ["ZHANG","CHEN","LI","LIU","HUANG","WU","ZHAO","SUN","ZHOU","XU","GUO","MA","LIN","YANG","HE","GAO"]),
 "NameCorrection_TC038":(  # accent-bearing
   ["RENEE","ZOE","ANDRE","CHLOE","NOE","RENE","INES","CELINE","HELOISE","MAEVA","LUCA","SOREN","AGNES","MATHIS"],
   ["LEVESQUE","MULLER","COTE","GAUTHIER","BRUNET","BELANGER","MORICE","ROY","PETIT","GIRARD","ROSSI","DAHL","BOISSY","NADEAU"]),
 "NameCorrection_TC043":(  # transfer / entirely-different name
   ["GREG","DEAN","KYLE","TROY","SETH","WADE","BRENT","CHAD","LANCE","DREW","GLEN","NEIL","CRAIG","SCOTT","TODD","KENT"],
   ["TAYLOR","WALKER","MORGAN","BENNETT","PARKER","COOPER","REED","HAYES","WARD","MURPHY","FOSTER","BRIGGS","HOLT","LANE"]),
 "NameCorrection_TC018":(  # middle-name correction
   ["EDWARD","HENRY","PHILIP","CHARLES","ALBERT","FREDERICK","WALTER","RALPH","HAROLD","EUGENE","LEONARD","HERBERT","CLARENCE","RAYMOND"],
   ["LOUIS","GEORGE","JAMES","LEE","PAUL","JOHN","DEAN","ALLEN","JAY","ROSS","KYLE","NEIL","MARK","REID"]),
 "NameCorrection_TC035":(  # adult (infant shares the surname)
   ["NADIA","SOFIA","AMARA","LEILA","MAYA","ANIKA","ZARA","NINA","TANIA","RITA","DIVYA","ELSA","PRIYA","IMANI"],
   ["OKONKWO","REYES","DIALLO","HADDAD","SINGH","PATEL","KHAN","COSTA","MENDEZ","OKAFOR","RAO","BERG","NANDA","SESAY"]),
 "SeatChange_TC049":(  # near-miss surname
   ["HUSSEIN","KARIM","OMAR","TAREQ","BILAL","SAMIR","YOUSEF","RAMI","NADER","HANI","WALID","ZAID","FADI","MAHER"],
   ["ALAWI","NASSER","FARIS","SAAD","RASHID","AZIZ","HAMDI","SALEH","FOUAD","JABER","KHALIL","MANSOUR","HADDAD","QASSEM"]),
}
def prior_full_names():
    """every passenger full-name ALREADY in trip-tracer — read from the LIVE passenger table
    (the WHOLE table, not just NC series) so fresh-set names are GLOBALLY unique, not merely
    unique among NC sets. Survives scratchpad/index-file loss; plus any local NC index files."""
    names=set()
    try:
        conn=tt_conn(); cur=conn.cursor()
        cur.execute("select distinct first_name,last_name from passenger")
        for f,l in cur.fetchall():
            if f and l: names.add(f"{f} {l}")
        conn.close()
    except Exception as e: print(f"[warn] prior_full_names DB read failed: {e}")
    import glob
    for fp in glob.glob(f"{WORK}/_NC_crt*_index.json"):
        try:
            for r in json.load(open(fp)):
                for p in r["paxs"]: names.add(f"{p[0]} {p[1]}")
        except Exception: pass
    return names

def plan_paxs(seed, exclude):
    import random
    rng=random.Random(int(seed)+7); used=set(exclude); out=[]
    lasts=_LASTS[:]; rng.shuffle(lasts); li=0
    for c in CASES:
        orig=c["paxs"]; cat=_SPECIAL_CAT.get(c["tc"]); newp=[]
        if cat:
            firsts,lasts=cat
            combos=[(f,l) for f in firsts for l in lasts]; rng.shuffle(combos)
            # a valid combo: adult name free AND (if infant present) "INFANT <last>" also free
            has_inf=any(p[2]=="INF" for p in orig)
            chosen=next((o for o in combos
                         if f"{o[0]} {o[1]}" not in used and (not has_inf or f"INFANT {o[1]}" not in used)), None)
            if chosen is None:
                raise RuntimeError(f"special name category exhausted for {c['tc']} "
                                   f"({len(combos)} combos all taken). Widen its pools in _SPECIAL_CAT.")
            for k,p in enumerate(orig):
                if p[2]=="INF": f,l="INFANT",chosen[1]           # infant shares the adult surname
                else: f,l=chosen
                newp.append((f,l)+tuple(p[2:]))
        else:
            # pick a surname that still has enough FREE first names for this booking's adults.
            # (bounded: never spin — the old `while ... in used: fi+=1` looped forever once a
            #  surname's first-names were all taken, which happens as sets accumulate.)
            nad=sum(1 for p in orig if p[2]!="INF")
            pick=None
            for ln in lasts:
                free=[f for f in _FIRSTS if f"{f} {ln}" not in used]
                if len(free)>=nad:
                    rng.shuffle(free); pick=(ln,free[:nad]); break
            if pick is None:
                raise RuntimeError(f"name pool exhausted for {c['tc']} (needs {nad} free firsts on some "
                                   f"surname). Expand _FIRSTS/_LASTS in nc_crt_build.py.")
            ln,fs=pick; fi=0
            for p in orig:
                if p[2]=="INF": fn="INFANT"
                else: fn=fs[fi]; fi+=1
                newp.append((fn,ln)+tuple(p[2:]))
        for q in newp: used.add(f"{q[0]} {q[1]}")
        out.append(newp)
    return out

def taken_locators():
    """locators already present in trip-tracer (any date) -> never reuse for a fresh set"""
    conn=tt_conn(); cur=conn.cursor(); cur.execute("select distinct pnr from trip"); t={r[0] for r in cur.fetchall()}
    conn.close(); return t

def gen_locators(n, seed, taken):
    import random
    rng=random.Random(int(seed)); A="ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"; out=[]; used=set()
    while len(out)<n:
        loc="".join(rng.choice(A) for _ in range(6))
        if loc in used or loc in taken or not loc[0].isalpha(): continue
        used.add(loc); out.append(loc)
    return out

def build_index():
    recs=[]
    locs=None
    paxplan=None
    if NC_SEED:
        locs=gen_locators(len(CASES), NC_SEED, taken_locators())
        excl=prior_full_names()
        paxplan=plan_paxs(NC_SEED, excl)
        clash=excl & {f"{p[0]} {p[1]}" for ps in paxplan for p in ps}
        assert not clash, f"name collision with prior set(s): {clash}"
        print(f"[index] fresh locators (seed {NC_SEED}): {locs[:5]} ... | {len(excl)} prior names excluded, 0 collisions")
    for i,c in enumerate(CASES):
        bdate,created,dep,departed,dep_iso=window_dates(c["window"])
        if locs: c=dict(c, pnr=locs[i], paxs=paxplan[i])
        pid=f"{c['pnr']}-{bdate}"
        recs.append(dict(tc=c["tc"],pri=c["pri"],feat=c["feat"],name=c["name"],pnr=c["pnr"],pnr_id=pid,
            booking_date=bdate,created=created,dep_date=dep,departed=departed,dep_iso=dep_iso,window=c["window"],
            paxs=c["paxs"],npax=len(c["paxs"]),src=c["src"],office=c["office"],system=c["system"],
            carriers=c["carriers"],group=c["group"],
            exp_elig=c["exp_elig"],exp_win=c["exp_win"],exp_reason=c["exp_reason"],chatbot=c["chatbot"],
            tbase=TBASE0+i*10,ticket=f"{TPREFIX}{TBASE0+i*10:07d}",email=EMAIL,phone=PHONE,
            pnr_named=c["pnr"]))
    if UNIQ:                                            # opt-in shared unique names (sets pax_names/uniq_names)
        _c=tt_conn(); U.assign_names(recs, lambda r: r["npax"], _c, seed=8501); _c.close()
        print(f"[index] CRT_UNIQ_NAMES: assigned DB-absent unique names to {sum(r['npax'] for r in recs)} pax")
    json.dump(recs,open(OUT,"w"),indent=1)
    print(f"[index] {len(recs)} PNRs -> {OUT}  (+{len(UNSEEDED)} unseeded: {[u[0] for u in UNSEEDED]})")
    return recs
def load_index(): return json.load(open(OUT))

# ---- scenario generation ----------------------------------------------------
def px_type(ptype):   # scenario_engine accepts ADT/CHD/INF; YTH cascaded as CHD then patched
    return {"ADT":"ADT","CHD":"CHD","INF":"INF","YTH":"CHD"}.get(ptype,"ADT")
def make_scenario(r):
    bdate=r["booking_date"]; dep=r["dep_date"]
    pax=[]
    for k,p in enumerate(r["paxs"]):
        first,last,ptype=p[0],p[1],p[2]
        entry=dict(type=px_type(ptype),first_name=first,last_name=last,gender="U",
                   date_of_birth=DOB,email=r["email"],phone=r["phone"])
        pax.append(entry)
    segs=[]
    for j,(op,mkt) in enumerate(r["carriers"]):
        o,d=("YYZ","CDG") if j==0 else ("CDG","FRA")
        dl,al,du,au=seg_times(dep,j)
        segs.append(dict(carrier=mkt,operating_carrier=op,flight_number=str(870+j),operating_flight_number=str(870+j),
                         origin=o,destination=d,dep_local=dl,arr_local=al,dep_utc=du,arr_utc=au,
                         booking_datetime=r["created"],aircraft="789",cabin="Y",status="HK",arrival_terminal="2A"))
    scn=dict(**{"$schema_version":2},scenario_id=r["pnr_id"],title=f"{r['tc']}: {r['name']} [{r['pnr']}]",
        description=r["name"],canvas="_canvas/pnr_creation_domestic_ac.json",contains_pii=False,
        identity=dict(pnr=r["pnr"],booking_date=bdate,type="PNR"),
        point_of_sale=dict(office_id=r["office"],iata_number="01424012",system_code=r["system"],agent_type="AIRLINE",
                           agent_numeric_sign="0001",agent_initials="NC",duty_code="SU",agent_country="CA",agent_city="YUL"),
        last_modification_comment=f"SIM-{r['tc']}-NC-CRT",creation_comment=f"SIM-{r['tc']}-NC-CRT",
        passengers=pax,segments=segs,
        ticketing=dict(issuance_local_date=bdate,fare=dict(amount="1450.00",currency="CAD"),
                       ticket_numbers=[docnum(r,k) for k in range(r["npax"])]),
        timeline=[dict(version=0,at=f"{bdate}T10:00:00Z",action="bootstrap",description="Pre-ticketing stub"),
                  dict(version=1,at=f"{bdate}T10:00:01Z",action="ticketing_added",description="Ticketing reference attached")])
    if r.get("pax_names"): scn=U.apply_to_scenario(scn,r)   # override passenger names when opt-in unique names set
    json.dump(scn,open(f"{SCENW}/{r['pnr_id']}.json","w"),indent=1)
    return scn

def render_publish_one(r):
    make_scenario(r)
    nd=f"{NDJW}/{r['pnr']}.ndjson"
    subprocess.run(["python3",SENG,"render","--scenario",f"{SCENW}/{r['pnr_id']}.json","--out",nd,"--canvas",CANVAS],
                   check=True,capture_output=True)
    out=subprocess.run(["python3",PUB,"--ndjson",nd,"--brokers",CRT["brokers"],"--topic",CRT["topic"],"--live"],
                       capture_output=True,text=True)
    return ("produced" in (out.stdout+out.stderr)),(out.stdout+out.stderr)

def cascaded(conn,pids):
    cur=conn.cursor(); cur.execute("select pnr_id from trip where pnr_id = any(%s)",(pids,)); return {x[0] for x in cur.fetchall()}

def finalize_one(r,ttc):
    cur=ttc.cursor(); pid=r["pnr_id"]; bdate=r["booking_date"]
    for k,p in enumerate(r["paxs"]):
        tk=docnum(r,k)
        cur.execute("""insert into ticket
            (primary_document_number,pnr_id,passenger_id,ticket_id,document_numbers,issuance_local_date,document_type)
            values (%s,%s,%s,%s,ARRAY[%s],%s,'T') on conflict do nothing""",
            (tk,pid,f"{pid}-PT-{k+1}",f"{tk}-{bdate}",tk,bdate))
        # patch passenger_type for YTH; has_infant handled below
        ptype=p[2]
        if ptype=="YTH":
            cur.execute("update passenger set passenger_type='YTH' where pnr_id=%s and passenger_id=%s",(pid,f"{pid}-PT-{k+1}"))
        # seed SSR rows (UMNR/YPTU/EXST/CBBG...) into special_service_request so the CHATBOT (which
        # retrieves the PNR from trip-tracer) sees them — scenario_engine/cascade does NOT emit these,
        # they'd otherwise exist only in the eligibility payload. Mirrors the YTH patch. (TC008/TC039)
        opts=p[3] if len(p)>3 else {}
        for code in opts.get("ssr",[]):
            ssr_id=f"{pid}-OT-{k+1}-{code}"
            cur.execute("""insert into special_service_request
                (ssr_id,pnr_id,code,passenger_id,segment_id,status,text,quantity,is_removed,
                 last_pnr_version,received_at,last_modified)
                values (%s,%s,%s,ARRAY[%s],ARRAY[%s],'HK',%s,1,false,1,now(),now())
                on conflict do nothing""",
                (ssr_id,pid,code,f"{pid}-PT-{k+1}",f"{pid}-ST-1",code))
    cur.execute("update passenger set date_of_birth=%s where pnr_id=%s",(DOB,pid))
    if any(p[2]=="INF" for p in r["paxs"]):
        cur.execute("update passenger set has_infant=true where pnr_id=%s and passenger_type<>'INF'",(pid,))
    # supersede stale duplicate ACTIVE trips for the same locator (keep only ours ACTIVE)
    cur.execute("update trip set status='INACTIVE' where pnr=%s and pnr_id<>%s and status='ACTIVE'",(r["pnr"],pid))
    cur.execute("update trip set status='ACTIVE' where pnr_id=%s",(pid,))
    ttc.commit()

# ---- eligibility payload + endpoint (shared with nc_checkpoints) ------------
_CTX=ssl.create_default_context(); _CTX.check_hostname=False; _CTX.verify_mode=ssl.CERT_NONE
def build_payload(r):
    pid=r["pnr_id"]; loc=r["pnr"]; created=r["created"]
    seg_ids=[f"{pid}-ST-{j+1}" for j in range(len(r["carriers"]))]
    P=[]; T=[]
    for i,p in enumerate(r["paxs"]):
        ppid=f"{pid}-PT-{i+1}"; ptype=p[2]; opts=p[3] if len(p)>3 else {}
        updates=[]
        if opts.get("loyalty"): updates.append({"attributeType":"LOYALTY","membership":{"number":"892345678","programName":"Aeroplan"}})
        if opts.get("corrected"): updates.append({"attributeType":"NAME","eventType":"PASSENGER_NAME_CHANGE"})
        P.append({"passengerId":ppid,"pnrId":pid,"firstName":p[0],"lastName":p[1],
                  "passengerType":ptype,"dateOfBirth":DOB,"isRemoved":False,"updates":updates})
        if ptype=="INF" and opts.get("no_ticket"): continue
        doc=docnum(r,i)
        cs=opts.get("coupon","OPEN_FOR_USE")
        # one coupon per segment, each correlated to its segment (so carrier-mix sees every leg)
        coupons=[{"id":f"{doc}-{j+1}","sequenceNumber":j+1,"status":cs,"fareBasisCode":"YAY00EFF","fareFamily":{"code":"ECO","owner":"AC"}} for j in range(len(seg_ids))]
        corr=[{"correlatedData":[{"ticketCouponId":f"{doc}-{j+1}","pnrTravelerId":ppid,"pnrAirSegmentId":seg_ids[j]} for j in range(len(seg_ids))]}]
        T.append({"primaryDocumentNumber":doc,"pnrId":pid,"passengerId":ppid,"documentNumbers":[doc],
            "coupons":coupons,"correlation":corr,"updates":[]})
    FS=[]; SSR=[]
    for j,(op,mkt) in enumerate(r["carriers"]):
        o,d=("YYZ","CDG") if j==0 else ("CDG","FRA")
        dl,al,du,au=seg_times(r["dep_date"],j,r.get("dep_iso"))
        FS.append({"segmentId":seg_ids[j],"pnrId":pid,"segmentStatus":"HK","boundRph":1,"bookingDatetime":created,
            "departureAirport":o,"arrivalAirport":d,"departureDatetime":du,"arrivalDatetime":au,
            "departureDatetimeLocal":du,"arrivalDatetimeLocal":au,"marketingCarrierCode":mkt,"marketingFlightNumber":870+j,
            "operatingCarrierCode":op,"operatingFlightNumber":870+j,"flightId":f"{mkt}-{870+j}-{r['dep_date']}-{o}",
            "cabinCode":"Y","cabinClass":"Y","aircraftCode":"789","isRemoved":False,"isMultileg":False,
            "passengerId":[f"{pid}-PT-{i+1}" for i in range(len(r["paxs"]))]})
    for i,p in enumerate(r["paxs"]):
        opts=p[3] if len(p)>3 else {}
        for code in opts.get("ssr",[]): SSR.append({"code":code,"passengerId":f"{pid}-PT-{i+1}","status":"HK"})
    bounds=[{"boundRph":1,"origin":"YYZ","destination":FS[-1]["arrivalAirport"],"regimes":["APPR"],
             "promisedSegments":seg_ids,"actualSegments":seg_ids,
             "bookingContext":{"bookingSource":r["src"],"bookingType":"REGULAR","gdsLocator":"GDSLOC"}}]
    gd={"groupName":"TESTGROUP","isGroupPnr":True} if r["group"] else None
    return {"changeTrigger":{"changeType":"ELIGIBILITY_SERVICE_REQUEST","trigger":"NAME_CORRECTION","selectedBound":None,"timestamp":None,"entity":None},
      "pnrData":{"changeTrigger":None,"pnrId":pid,"pnr":loc,"lastName":[],"createdAt":created,"status":"ACTIVE",
        "source":r["src"],"travelType":"REGULAR","groupDetails":gd,"login":None,"officeId":r["office"],"iataNumber":None,
        "linkedPnr":None,"receivedAt":None,"lastModified":created,"lastPnrVersion":None,"lastModifiedEventLogId":None,
        "passengers":P,"flightSegments":FS,"flightLegs":[],"journeyUpdates":[],"non1a":None,"specialServiceRequests":SSR,
        "tickets":T,"emds":[],"baggageUpdates":None,"stormxVouchers":None,"icouponVouchers":None,
        "icouponTransportRedemptions":None,"cancelledVouchers":None,"edsFlight":[],"edsPnr":[{"pnrId":pid,"bounds":bounds}],"dds":[],"oalFlights":[]}}

def call_endpoint(r):
    req=urllib.request.Request(CRT["endpoint"],data=json.dumps(build_payload(r)).encode(),
        headers={"Content-Type":"application/json","x-api-key":CRT["api_key"]},method="POST")
    try:
        with urllib.request.urlopen(req,context=_CTX,timeout=30) as resp: j=json.loads(resp.read().decode())
    except Exception as e: return {"err":str(e)[:120]}
    pe=j.get("data",{}).get("pnrEligibility",{})
    return {"elig":pe.get("isPnrEligible"),"win":pe.get("processingWindow"),
            "reason":(pe.get("reasonCode") or {}).get("code"),"val":pe.get("validationStatus"),
            "npe":len(pe.get("passengerEligibility",[]))}

def verify_one(r):
    g=call_endpoint(r)
    ok=(g.get("elig")==r["exp_elig"] and g.get("win")==r["exp_win"] and g.get("reason")==r["exp_reason"])
    return ok,g

# ---- main -------------------------------------------------------------------
def main():
    ap=argparse.ArgumentParser(); ap.add_argument("phase")
    ap.add_argument("--start",type=int,default=0); ap.add_argument("--end",type=int,default=10**9)
    a=ap.parse_args()
    if a.phase=="index": build_index(); return
    recs=load_index(); sl=recs[a.start:a.end]
    if a.phase=="publish":
        ok=0
        for i,r in enumerate(sl):
            good,log=render_publish_one(r); ok+=good
            print(f"  [{a.start+i}] {r['pnr_id']} {r['tc']} {'OK' if good else 'FAIL '+log[-160:]}",flush=True)
        print(f"[publish] {ok}/{len(sl)} produced")
    elif a.phase=="checkcascade":
        ttc=tt_conn(); have=cascaded(ttc,[r["pnr_id"] for r in sl]); ttc.close()
        miss=[r["pnr_id"] for r in sl if r["pnr_id"] not in have]
        print(f"[cascade] {len(have)}/{len(sl)} present; missing={miss}")
    elif a.phase=="finalize":
        ttc=tt_conn()
        for i,r in enumerate(sl):
            try: finalize_one(r,ttc); print(f"  [{a.start+i}] {r['pnr_id']} {r['tc']} finalized",flush=True)
            except Exception as e: ttc.rollback(); print(f"  [{a.start+i}] {r['pnr_id']} ERR {e}",flush=True)
        ttc.close(); print("[finalize] tickets/DOB/type/supersede done")
    elif a.phase=="verify":
        res=[]; ok=0
        for r in sl:
            good,g=verify_one(r); ok+=good
            res.append(dict(tc=r["tc"],pnr=r["pnr"],exp=(r["exp_elig"],r["exp_win"],r["exp_reason"]),got=g,ok=good))
            if not good: print(f"  FAIL {r['pnr']} {r['tc']} exp={r['exp_elig']}/{r['exp_win']}/{r['exp_reason']} got={g.get('elig')}/{g.get('win')}/{g.get('reason')}")
        print(f"[verify] {ok}/{len(sl)} eligibility outcomes match expected")
        json.dump(res,open(f"{WORK}/nc_verify{_sfx}.json","w"),indent=1)
    else: print("unknown phase"); sys.exit(2)

if __name__=="__main__": main()
