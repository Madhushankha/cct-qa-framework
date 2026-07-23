#!/usr/bin/env python3
import os
import _cctdb
"""Build Ancillaries SEAT & BAG fee-refund test PNRs in the CRT environment.

The seat/bag refund bot reads the SAME rule-engine DDS path as FD (S3 +
execution_traces + /rule-engine/dds/output endpoint), but the eligibility lives
in two TOP-LEVEL arrays of the DDS response (siblings of compensationEligibility):

  seatFeeRefundEligibility[]  (per passenger x segment):
     emdNumber, emdCouponStatus(USED/OPEN/REFUNDED/VOID/EXCHANGED), eligibilityStatus,
     systemCode(SF-EL-01 / SF-NE-01 / SF-NE-REFUNDED / SF-NE-VOID / SF-OAL-01),
     reason, currency, amount, hasSeatCharacteristicsChanged, fopCode(CC / AWLTR=AC-Wallet)
  baggageRefundEligibility[]  (per segment, then passengerEligibility[] per pax):
     isAHLPresent, ahlCreationDate, reportType(AHL/DPR/CBO/NONE), waitPeriodSatisfied,
     + per pax: emdNumber, eligibilityStatus, systemCode(BF-EL-01 / BF-NE-01 /
       BF-NE-REFUNDED / BF-NE-VOID / BF-NE-NOREPORT / BF-OAL-01), reason, amount, fopCode

Everything the bot needs (EMD status, prefix 014=AC vs 016/838=OAL, seat-char change,
AHL/DPR presence, FOP) is IN the DDS response — no separate emd / AHL table seeding.
Booking (pax names, contact for OTP, ticket) still comes from trip-tracer via Kafka.

Taxonomy + field values validated against the prior qa-uatcrt/qa-recreate CRT set
(2026-06-24) which the seat/bag bot was tested against. This builder generates a FRESH
set: new random locators, contact Reese/Jordan/Avery Smith + lahiru mailinator OTP.

Phases (idempotent / resumable):
  index    -> _ANC_SEATBAG_crt_index.json  (fresh locators + tickets from CASES table)
  publish  render scenario -> publish booking to CRT PNR Kafka
  checkcascade  how many landed in trip-tracer
  finalize ticket + DOB + S3 put(DDS) + execution_traces pin
  verify   GET dds/output endpoint, assert seat/bag systemCode matches expected
Usage: AWS_PROFILE=ac-cct-crt python3 anc_crt_build.py <phase> [--start N] [--end N]
"""
import json, os, sys, uuid, subprocess, ssl, urllib.request, argparse, random, datetime
import boto3, psycopg2
import crt_uniqnames as U

UNIQ = os.environ.get("CRT_UNIQ_NAMES") == "1"   # opt-in DB-absent unique passenger names (default OFF)

KB   = os.environ.get("CCTQA_DATAGEN_ROOT",
                      os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SENG = f"{KB}/scripts/scenario_engine.py"
PUB  = f"{KB}/scripts/publish_raw.py"
CANVAS = f"{KB}/scenarios/_canvas/pnr_creation_domestic_ac.json"
WORK = "/tmp/cctqa-datagen/anc_work"
SCENW=f"{WORK}/scenarios"; DDSW=f"{WORK}/dds"; NDJW=f"{WORK}/ndjson"
for d in (SCENW,DDSW,NDJW): os.makedirs(d, exist_ok=True)
# per-set knobs (override via env to mint a new independent set — see SETS ledger in memory)
OUT = os.environ.get("ANC_OUT", f"{WORK}/_ANC_SEATBAG_crt_index.json")

CRT = dict(
  profile=os.environ.get("AWS_PROFILE","ac-cct-crt"), region="ca-central-1",
  brokers=("b-1.accctmskcrtcac1.05hf7o.c4.kafka.ca-central-1.amazonaws.com:9092,"
           "b-2.accctmskcrtcac1.05hf7o.c4.kafka.ca-central-1.amazonaws.com:9092,"
           "b-3.accctmskcrtcac1.05hf7o.c4.kafka.ca-central-1.amazonaws.com:9092"),
  topic="emh-dev.ALTEA-PNRDATA-UAT",
  tt_host="ac-cct-trip-tracer-rds-cluster-crt-cac1.cluster-cxqe2wacy866.ca-central-1.rds.amazonaws.com",
  tt_db="trip-tracer", tt_user="dbadmin", tt_pass=os.environ.get("CCT_TRIPTRACER_PASSWORD", ""),
  re_host="ac-cct-rule-engine-crt-cac1-rds-cluster-instance1.cxqe2wacy866.ca-central-1.rds.amazonaws.com",
  re_db="postgres", re_user="dbadmin", re_pass=os.environ.get("CCT_RULEENGINE_PASSWORD", ""),
  s3_bucket="cct-ask-ac-crt-logs",
  endpoint="https://rule-engine-platform-service.ac-cct-crt.cloud.aircanada.com/rule-engine/dds/output/",
  api_key=os.environ.get("DDS_API_KEY", ""),
)
EMAIL=os.environ.get("CRT_EMAIL","lahiru@ae-qa1-aircanada.mailinator.com")
PHONE=os.environ.get("CRT_PHONE","+94712534323")
DOB="1986-04-23"
PIN_TS="2028-12-31 00:00:00+00"   # beats existing 2027-12-31 / 2028-06-30 pins on ORDER BY DESC
TPREFIX=os.environ.get("ANC_TPREFIX","014302")     # set-1=014301 set-2=014302 set-3=014303
SEED=int(os.environ.get("ANC_SEED","767676"))      # set-1=545454 set-2=767676 set-3=989898
NAME_OFFSET=int(os.environ.get("ANC_NAME_OFFSET","0"))  # skip N names so sets don't share names
CORR="qa-anc-crt"
# Dates are RELATIVE TO TODAY so a set is never born stale (a fixed FDATE expires the pre-travel
# cases the moment it passes; a fixed PDATE drifts). Override with ANC_PDATE / ANC_FDATE if needed.
_TODAY=datetime.date.today()
def _d(n): return (_TODAY+datetime.timedelta(days=n)).isoformat()
PDATE=os.environ.get("ANC_PDATE", _d(-21))   # post-travel: flown 3 weeks ago
FDATE=os.environ.get("ANC_FDATE", _d(+15))   # pre-travel: 15 days out (SEAT-TC-031/033 spec)
# BAG_TC011 = "72-hour wait NOT satisfied": needs a RECENT flight + an AHL younger than 72h,
# else waitPeriodSatisfied=false contradicts a weeks-old ahlCreationDate (see AHL-age checkpoint).
BAG011_DATE=_d(-2)                            # flown 2 days ago (still post-travel)
BAG011_AHL=f"{_d(-1)}T10:00:00Z"              # AHL raised 24h ago -> genuinely inside the 72h window
# Distinct passenger-name pool: every PNR gets a unique primary name, and every
# passenger across the whole set is globally unique (first x last sequential walk).
FIRST=["OLIVIA","LIAM","EMMA","NOAH","AVA","WILLIAM","SOPHIA","BENJAMIN","ISABELLA","LUCAS",
       "MIA","HENRY","CHARLOTTE","THEODORE","AMELIA","JACK","HARPER","OLIVER","EVELYN","JAMES",
       "ABIGAIL","ETHAN","EMILY","ALEXANDER","ELIZABETH","DANIEL","SOFIA","MATTHEW","VICTORIA","JOSEPH",
       "GRACE","SAMUEL","CHLOE","DAVID","PENELOPE","CARTER","LAYLA","OWEN","RILEY","GABRIEL",
       "NORA","JULIAN","HAZEL","LEO","AURORA","ISAAC","SAVANNAH","LINCOLN","BROOKLYN","ANTHONY"]
LAST =["TREMBLAY","GAGNON","ROY","CoTE","BOUCHARD","GAUTHIER","MORIN","LAVOIE","FORTIN","GAGNE",
       "OUELLET","PELLETIER","BELANGER","LEVESQUE","BERGERON","LEBLANC","PAQUETTE","GIRARD","SIMARD","BOISVERT",
       "CARON","BEAULIEU","CLOUTIER","DUBOIS","POIRIER","FONTAINE"]
def name_pool(offset=0):
    i=0
    for ln in LAST:
        for fn in FIRST:
            if i>=offset: yield (fn, ln.upper())
            i+=1

_sess=boto3.Session(profile_name=CRT["profile"], region_name=CRT["region"])
def tt_conn(): return _cctdb.trip_tracer(CRT["tt_host"], profile=CRT.get("profile"))
def re_conn(): return _cctdb.rule_engine(CRT["re_host"], dbname=CRT.get("re_db","postgres"), profile=CRT.get("profile"))

# ---- routes ----------------------------------------------------------------
DOM =("YUL","YYZ","AC","4922")     # domestic AC single seg
DOM2=("YYZ","YVR","AC","0123")     # alt domestic
OALI=("CDG","YYZ","AC","0871")     # intl route, AC-ticketed but OAL-operated (op carrier overridden via emd/DDS)
MS  =[("YYZ","YUL","AC","4922"),("YUL","CDG","AC","0870")]  # multi-seg (seg1 elig / seg2 not, TC018)
MSO =[("YYZ","CDG","AC","0870"),("CDG","FRA","AC","0871")]  # multi-seg OAL (TC005)

# seat row defaults ----------------------------------------------------------
def srow(status="ELIGIBLE",syscode="SF-EL-01",coupon="USED",char=True,amount=68.85,fop="CC",emd="014",reason=""):
    return dict(status=status,syscode=syscode,coupon=coupon,char=char,amount=amount,fop=fop,emd=emd,reason=reason)
def S_EL(reason,**kw):  return srow("ELIGIBLE","SF-EL-01","USED",True,68.85,"CC","014",reason,**kw)
def S_NE(reason,**kw):  return srow("NOT_ELIGIBLE","SF-NE-01","USED",False,0,"CC","014",reason,**kw)
def S_REF(reason):      return srow("NOT_ELIGIBLE","SF-NE-REFUNDED","REFUNDED",False,0,"CC","014",reason)
def S_VOID(reason):     return srow("NOT_ELIGIBLE","SF-NE-VOID","VOID",False,0,"CC","014",reason)
def S_OAL(reason,emd="016"): return srow("NOT_ELIGIBLE","SF-OAL-01","USED",False,0,"CC",emd,reason)
# bag row defaults -----------------------------------------------------------
def brow(status="ELIGIBLE",syscode="BF-EL-01",amount=30.0,fop="CC",emd="014",reason=""):
    return dict(status=status,syscode=syscode,amount=amount,fop=fop,emd=emd,reason=reason)
def B_EL(reason,**kw):  return brow("ELIGIBLE","BF-EL-01",30.0,"CC","014",reason,**kw)
def B_NE(reason,**kw):  return brow("NOT_ELIGIBLE","BF-NE-01",0,"CC","014",reason,**kw)
def B_REF(reason):      return brow("NOT_ELIGIBLE","BF-NE-REFUNDED",0,"CC","014",reason)
def B_VOID(reason):     return brow("NOT_ELIGIBLE","BF-NE-VOID",0,"CC","014",reason)
def B_OAL(reason,emd="016"): return brow("NOT_ELIGIBLE","BF-OAL-01",0,"CC",emd,reason)
def B_NOREP(reason):    return brow("NOT_ELIGIBLE","BF-NE-NOREPORT",0,"CC","014",reason)

# ---- CASES table (54) ------------------------------------------------------
# Each: tc, suite, npax, nseg(route), seat_rows/bag config, flags.
# seat: 'rows' = list over (pax x seg) built by helper. bag: per-seg AHL cfg + per-pax rows.
S=[]  # seat cases
def seat(tc,name,pax=1,route=DOM,rows=None,future=False,note=""):
    S.append(dict(tc=tc,suite="seat",name=name,npax=pax,route=[route] if isinstance(route,tuple) else route,
                  seat=rows,future=future,note=note))
# --- 33 seat cases ---
seat("ANC-SEAT-TC-001","Seat Refund — EMD Already Refunded (Status R)",1,DOM,[[S_REF("Seat Refund — EMD Already Refunded (Status R)")]])
seat("ANC-SEAT-TC-002","Seat Refund — EMD Voided (Status V)",1,DOM,[[S_VOID("Seat Refund — EMD Voided (Status V)")]])
seat("ANC-SEAT-TC-003","Seat Refund — Single Segment — EMD NOT 014 — OAL Referral",1,OALI,[[S_OAL("Seat Refund — Single Segment — EMD NOT 014 — OAL Referral")]])
seat("ANC-SEAT-TC-004","Seat Refund — Single Segment — EMD NOT 014 — Customer Disputes",1,OALI,[[S_OAL("Seat Refund — Single Segment — EMD NOT 014 — Customer Disputes → Dispute")]])
seat("ANC-SEAT-TC-005","Seat Refund — Multi-Segment — EMD NOT 014 — OAL Referral",1,MSO,[[S_OAL("segment 1 OAL")],[S_OAL("segment 2 OAL")]])
seat("ANC-SEAT-TC-006","Seat Refund — Multi-Segment — EMD 014 — ELIGIBLE",1,MS,[[S_EL("segment 1 ELIGIBLE")],[S_EL("segment 2 ELIGIBLE")]])
seat("ANC-SEAT-TC-007","Seat Refund — Single Segment — EMD 014 — ELIGIBLE",1,DOM,[[S_EL("Seat Refund — Single Segment — EMD 014 — ELIGIBLE")]])
seat("ANC-SEAT-TC-008","Seat Refund — NOT Eligible — Seat Number Changed Without Char Change",1,DOM,[[S_NE("Seat Refund — NOT Eligible — Seat Number Changed Without Characteristic Change")]])
seat("ANC-SEAT-TC-009","Seat Refund — NOT Eligible — Seat Char Change — Customer Disputes",1,DOM,[[S_NE("Seat Refund — NOT Eligible — Seat Char Change — Customer Disputes")]])
seat("ANC-SEAT-TC-010","Seat Refund — NOT Eligible — No Seat Fee Paid",1,DOM,[[]],note="no_emd")   # empty seat array
seat("ANC-SEAT-TC-011","Seat Refund — NOT Eligible — Already Refunded",1,DOM,[[S_REF("Seat Refund — NOT Eligible — Already Refunded")]])
seat("ANC-SEAT-TC-012","Seat Refund — NOT Eligible — Pax Rebooked and Holding Ticket",1,DOM,[[S_NE("Seat Refund — NOT Eligible — Pax Rebooked and Holding Ticket")]])
seat("ANC-SEAT-TC-013","Seat Refund — Service Downtime",1,DOM,[[S_NE("Seat Refund — Service Downtime")]],note="downtime")
seat("ANC-SEAT-TC-014","Seat Refund — ACV Booking → Redirected to ACV",1,DOM,[[S_NE("Seat Refund — ACV Booking → Redirected to ACV")]],note="acv")
seat("ANC-SEAT-TC-015","Seat Refund — Exchanged EMD → New EMD Located",1,DOM,[[dict(**{**S_NE("Seat Refund — Exchanged EMD → New EMD Located and Rules Applied"),"coupon":"EXCHANGED"})]])
seat("ANC-SEAT-TC-016","Seat Refund — Automatable FOP (AC Wallet)",1,DOM,[[dict(**{**S_EL("Seat Refund — Automatable FOP (AC Wallet)"),"fop":"AWLTR"})]])
seat("ANC-SEAT-TC-017","Seat Refund — Multi-Passenger PNR — Mixed Eligibility",3,DOM,
     [[S_EL("Seat Refund — Multi-Passenger — Mixed (Pax1 eligible seat char change)"),
       S_NE("Seat Refund — Multi-Passenger — Mixed (Pax2 not eligible no change)"),
       S_EL("Seat Refund — Multi-Passenger — Mixed (Pax3 eligible denied boarding)")]])
seat("ANC-SEAT-TC-018","Seat Refund — Multi-Segment Parallel Eligibility — Mixed",1,MS,
     [[S_EL("segment 1 ELIGIBLE")],[S_NE("segment 2 NOT ELIGIBLE same characteristics")]])
seat("ANC-SEAT-TC-019","Seat Refund — OAL/STAR Partner Operated Segment",1,OALI,[[S_OAL("Seat Refund — OAL/STAR Partner Operated Segment (at Eligibility)")]])
seat("ANC-SEAT-TC-020","Seat Refund — Catch-All Not Eligible",1,DOM,[[S_NE("Seat Refund — Catch-All Not Eligible")]])
seat("ANC-SEAT-TC-021","Seat Refund — Catch-All Not Eligible → Customer Disputes",1,DOM,[[S_NE("Seat Refund — Catch-All Not Eligible → Customer Disputes → Dispute Flow")]])
seat("ANC-SEAT-TC-022","Seat Refund — Duplicate Claim Prevention",1,DOM,[[S_NE("Seat Refund — Duplicate Claim Prevention (Same PNR + Segment + EMD)")]],note="dup")
seat("ANC-SEAT-TC-023","Seat Refund — Multi-Passenger — ALL Eligible",3,DOM,
     [[S_EL("Seat Refund — Multi-Passenger — ALL Eligible (Pax1 seat char downgrade)"),
       S_EL("Seat Refund — Multi-Passenger — ALL Eligible (Pax2 denied boarding)"),
       S_EL("Seat Refund — Multi-Passenger — ALL Eligible (Pax3 no travel due to disruption)")]])
seat("ANC-SEAT-TC-024","Seat Refund — Multi-Passenger — ALL Not Eligible",3,DOM,
     [[S_NE("Seat Refund — Multi-Passenger — ALL Not Eligible (Pax1 involuntary upgrade)"),
       S_NE("Seat Refund — Multi-Passenger — ALL Not Eligible (Pax2 no EMD fee paid)"),
       S_NE("Seat Refund — Multi-Passenger — ALL Not Eligible (Pax3 holding ticket)")]])
seat("ANC-SEAT-TC-025","Seat Refund — Multi-Passenger — Passenger Selection Required",2,DOM,
     [[S_EL("Seat Refund — Multi-Passenger — Passenger Selection Required (Pax1)"),
       S_EL("Seat Refund — Multi-Passenger — Passenger Selection Required (Pax2)")]])
seat("ANC-SEAT-TC-026","Denied Boarding – Eligible for Seat Fee Refund",1,DOM,[[S_EL("Denied Boarding – Eligible for Seat Fee Refund")]])
seat("ANC-SEAT-TC-027","Voluntary Upgrade – Paid Upgrade – Eligible",1,DOM,[[S_EL("Voluntary Upgrade – Paid Upgrade – Eligible for Seat Fee Refund")]])
seat("ANC-SEAT-TC-028","Voluntary Upgrade – AC Bid Upgrade – Eligible",1,DOM,[[S_EL("Voluntary Upgrade – AC Bid Upgrade – Eligible for Seat Fee Refund")]])
seat("ANC-SEAT-TC-029","Used EMD – Change in Seat Characteristics (INVOL) – Eligible",1,DOM,[[S_EL("Used EMD – Change in Seat Characteristics (INVOL) – Eligible for Refund")]])
seat("ANC-SEAT-TC-030","Single Passenger – Multiple EMDs on Same Segment – Manual",1,DOM,[[S_NE("Single Passenger – Multiple EMDs on Same Segment – Manual Handling")]],note="multi_emd")
seat("ANC-SEAT-TC-031","Pre-Travel (Before Expected Arrival) – Live Agent Handoff",1,DOM,[[S_NE("Pre-Travel (Before Expected Arrival) – Live Agent Handoff")]],future=True)
seat("ANC-SEAT-TC-032","Seat Refund — Aeroplan Login — Name Not on PNR",2,DOM2,
     [[S_EL("Seat Refund — Name Not on PNR (Jordan eligible)"),
       S_EL("Seat Refund — Name Not on PNR (Avery eligible)")]],note="name_not_on_pnr")
seat("ANC-SEAT-TC-033","Seat Refund — Pre-Travel PNR — Customer Insists on Eligibility",1,DOM2,
     [[dict(**{**S_NE("Seat Refund — Pre-Travel PNR — Customer Insists on Eligibility"),"amount":0})]],future=True)

# --- 21 bag cases ---  bag helper: rows=list over segs; each seg=(ahl_cfg, [pax rows])
B=[]
def bag(tc,name,pax=1,route=DOM,segs=None,note="",recent_ahl=False):
    B.append(dict(tc=tc,suite="bag",name=name,npax=pax,route=[route] if isinstance(route,tuple) else route,
                  bag=segs,note=note,recent_ahl=recent_ahl))
def AHL(present=True,rtype="AHL",wait=None): return dict(isAHL=present,reportType=rtype,wait=wait)
bag("BAG_TC001","Bag Refund — EMD Already Refunded (Status R)",1,DOM,[(AHL(),[B_REF("Bag Refund — EMD Already Refunded (Status R)")])])
bag("BAG_TC002","Bag Refund — EMD Voided (Status V)",1,DOM,[(AHL(),[B_VOID("Bag Refund — EMD Voided (Status V)")])])
bag("BAG_TC003","Bag Refund — No AHL / DPR → Redirect to Report Bag",1,DOM,[(AHL(False,"None"),[B_NE("Bag Refund — No AHL / DPR Exists → Redirect to Report Bag")])])
bag("BAG_TC004","Bag Refund — AHL Exists — Eligible — Manual",1,DOM,[(AHL(True,"AHL",True),[B_EL("Bag Refund — AHL Exists — Eligible — Manual Handling — eligible, routes to manual handling")])])
bag("BAG_TC005","Bag Refund — DPR Exists — Eligible — Manual",1,DOM,[(AHL(True,"DPR",True),[B_EL("Bag Refund — DPR Exists — Eligible — Manual Handling")])])
bag("BAG_TC006","Bag Refund — AHL/DPR — NOT Eligible — Dispute Option",1,DOM,[(AHL(True,"DPR",True),[B_NE("Bag Refund — AHL/DPR Exists — NOT Eligible — End Flow with Dispute Option")])])
bag("BAG_TC007","Bag Refund — Service Downtime : Service Error API",1,DOM,[(AHL(),[B_NE("Bag Refund — Service Downtime : Service Error API")])],note="downtime")
bag("BAG_TC008","Bag Refund — OAL-Collected Bag Fee → Referred to OAL",1,("YYZ","YVR","AC","0123"),[(AHL(),[B_OAL("Bag Refund — OAL-Collected Bag Fee → Referred to OAL (WestJet)","838")])])
bag("BAG_TC009","Bag Refund — Overweight + Regular Bag Fee — Eligible — Manual",1,DOM,[(AHL(True,"AHL",True),[B_EL("Bag Refund — Overweight + Regular Bag Fee — Eligible — Manual — eligible, routes to manual handling")])])
bag("BAG_TC010","Bag Refund — USED EMD → Cover Refund with 72-Hour Wait",1,DOM,[(AHL(True,"AHL",True),[B_EL("Bag Refund — USED EMD → Cover Refund with 72-Hour Wait — eligible, routes to manual handling")])])
bag("BAG_TC011","Bag Refund — USED EMD → 72-Hour Wait NOT Satisfied → Pending",1,DOM,[(AHL(True,"AHL",False),[B_NE("Bag Refund — USED EMD → 72-Hour Wait NOT Satisfied → Pending")])],recent_ahl=True)
bag("BAG_TC012","Bag Refund — Automatable FOP (AC wallet) → Manual",1,DOM,[(AHL(True,"AHL",True),[dict(**{**B_EL("Bag Refund — Automatable FOP (AC wallet) → Manual — eligible, routes to manual handling"),"fop":"AWLTR"})])])
bag("BAG_TC013","Bag Refund — Duplicate Claim Prevention",1,DOM,[(AHL(),[B_NE("Bag Refund — Duplicate Claim Prevention")])],note="dup")
bag("BAG_TC014","Bag Refund — No Paid EMD Exists → No Refund",1,DOM,[(AHL(False,"None"),[])],note="no_emd")
bag("BAG_TC015","Bag Refund — Multi-Passenger — Mixed Eligibility",3,DOM,
    [(AHL(True,"AHL",True),[B_EL("Bag Refund — Multi-Passenger — Mixed (Pax1 AHL eligible)"),
                            B_NE("Bag Refund — Multi-Passenger — Mixed (Pax2 no AHL not eligible)"),
                            B_EL("Bag Refund — Multi-Passenger — Mixed (Pax3 AHL eligible)")])])
bag("BAG_TC016","Bag Refund — Multi-Passenger — ALL Eligible",2,DOM,
    [(AHL(True,"AHL",True),[B_EL("Bag Refund — Multi-Passenger — ALL Eligible (Pax1)"),
                            B_EL("Bag Refund — Multi-Passenger — ALL Eligible (Pax2)")])])
bag("BAG_TC017","Bag Refund — Multi-Passenger — Passenger Selection Required",2,DOM,
    [(AHL(True,"AHL",True),[B_EL("Bag Refund — Multi-Passenger — Passenger Selection Required (Pax1)"),
                            B_EL("Bag Refund — Multi-Passenger — Passenger Selection Required (Pax2)")])])
bag("BAG_TC018","Bag Refund — Multiple AHL Records — Continue (Not Manual)",1,DOM,[(AHL(True,"AHL",True),[B_EL("Bag Refund — Multiple AHL Records — Continue — eligible, routes to manual handling")])])
bag("BAG_TC019","Bag Refund — Multiple Bags — Partial Eligibility (2 Highest Fees)",1,DOM,[(AHL(True,"AHL",True),[dict(**{**B_EL("Bag Refund — Multiple Bags — Partial Eligibility (2 Highest: $50 + $75)"),"amount":125.0})])])
bag("BAG_TC020","Bag Refund — Not Eligible → Customer Disputes → Manual",1,DOM,[(AHL(True,"DPR",True),[B_NE("Bag Refund — Not Eligible → Customer Disputes → Manual Handling")])])
bag("BAG_TC021","Bag Refund — STAR Alliance Partner Bag Fee → Referred to STAR",1,("YYZ","FRA","AC","0870"),[(AHL(),[B_OAL("Bag Refund — STAR Alliance Partner Bag Fee → Referred to STAR Partner (Lufthansa)","016")])])

CASES=S+B

# ---- locator generation ----------------------------------------------------
def gen_locators(n, seed):
    rng=random.Random(seed); A="ABCDEFGHIJKLMNOPQRSTUVWXYZ"; out=[]; taken=set()
    while len(out)<n:
        loc="".join(rng.choice(A) for _ in range(6))
        if loc in taken: continue
        taken.add(loc); out.append(loc)
    return out

def emd_num(prefix,i,j=1):
    # deterministic AC/OAL emd document number: prefix + 8 digits
    base=f"{40000000+i*10+j}"
    return f"{prefix}{base[-8:]}"

def build_index():
    locs=gen_locators(len(CASES),SEED)
    pool=name_pool(NAME_OFFSET)
    recs=[]
    for i,c in enumerate(CASES):
        if c.get("future"):        date=FDATE          # pre-travel: flies in the future
        elif c.get("recent_ahl"):  date=BAG011_DATE    # recent flight so a <72h AHL is plausible
        else:                      date=PDATE          # post-travel: already flown
        loc=locs[i]; pid=f"{loc}-{date}"
        pax_names=[list(next(pool)) for _ in range(c["npax"])]  # globally-unique names, no conflicts
        r_=dict(tc=c["tc"],suite=c["suite"],name=c["name"],loc=loc,pnr_id=pid,date=date,
                npax=c["npax"],route=c["route"],future=c.get("future",False),note=c.get("note",""),
                pax_names=pax_names,
                seat=c.get("seat"),bag=c.get("bag"),
                ticket=f"{TPREFIX}{i+1:06d}",email=EMAIL,phone=PHONE,pin=True)
        if c.get("recent_ahl"): r_["ahl_date"]=BAG011_AHL   # AHL 24h old -> wait genuinely unsatisfied
        recs.append(r_)
    if UNIQ:   # overwrite pax_names with globally-unique DB-absent names + flag uniq_names for the checkpoint
        _c=tt_conn()
        try: U.assign_names(recs, lambda r: r["npax"], _c, seed=771001)
        finally: _c.close()
    json.dump(recs,open(OUT,"w"),indent=1)
    ns=sum(1 for r in recs if r["suite"]=="seat"); nb=len(recs)-ns
    print(f"[index] {len(recs)} cases ({ns} seat + {nb} bag) -> {OUT}")
    return recs

def load_index(): return json.load(open(OUT))

# ---- scenario + DDS generation --------------------------------------------
def seg_times(date,segidx):
    h=12+segidx*4
    dep=f"{date}T{h:02d}:00:00"; arr=f"{date}T{h+3:02d}:00:00"
    return dep,arr,f"{date}T{h+4:02d}:00:00Z",f"{date}T{h+7:02d}:00:00Z"

def make_scenario(r):
    date=r["date"]
    pax=[]
    for k in range(r["npax"]):
        # each passenger uses its pre-assigned globally-unique name (TC032 = name-not-on-PNR
        # is satisfied by OTP contact identity differing from these PNR names)
        nm=r["pax_names"][k]
        pax.append(dict(type="ADT",first_name=nm[0],last_name=nm[1],gender="U",
                        date_of_birth=DOB,email=r["email"],phone=r["phone"]))
    segs=[]
    for j,rt in enumerate(r["route"]):
        o,d,car,fn=rt
        dl,al,du,au=seg_times(date,j)
        segs.append(dict(carrier=car,operating_carrier=car,flight_number=fn,operating_flight_number=fn,
                         origin=o,destination=d,dep_local=dl,arr_local=al,dep_utc=du,arr_utc=au,
                         booking_datetime=None,aircraft="320",cabin="Y",status="HK",arrival_terminal="1"))
    scn=dict(**{"$schema_version":2},scenario_id=r["pnr_id"],title=f"{r['tc']}: {r['name']} [{r['loc']}]",
             description=r["name"],canvas="_canvas/pnr_creation_domestic_ac.json",contains_pii=False,
             identity=dict(pnr=r["loc"],booking_date=date,type="PNR"),
             point_of_sale=dict(office_id="YULAC010V",iata_number="01424012",system_code="1A",agent_type="AIRLINE",
                                agent_numeric_sign="0001",agent_initials="AN",duty_code="SU",agent_country="CA",agent_city="YUL"),
             last_modification_comment=f"SIM-{r['tc']}-ANC-CRT",creation_comment=f"SIM-{r['tc']}-ANC-CRT",
             passengers=pax,segments=segs,
             ticketing=dict(issuance_local_date="2026-06-01",fare=dict(amount="350.00",currency="CAD"),
                            ticket_numbers=[r["ticket"]]),
             timeline=[dict(version=0,at=f"{date}T10:00:00Z",action="bootstrap",description="Pre-ticketing stub"),
                       dict(version=1,at=f"{date}T10:00:01Z",action="ticketing_added",description="Ticketing reference attached")])
    json.dump(scn,open(f"{SCENW}/{r['pnr_id']}.json","w"),indent=1)
    return scn

def itinerary(r):
    pid=r["pnr_id"]; out=[]
    for j,rt in enumerate(r["route"]):
        o,d,car,fn=rt; dl,al,du,au=seg_times(r["date"],j)
        seg=dict(segmentId=f"{pid}-ST-{j+1}",segmentStatus="HK",
                 departureDatetime=du.replace("Z","+00:00"),arrivalDatetime=au.replace("Z","+00:00"),
                 departureAirport=o,arrivalAirport=d,marketingFlightNumber=int(fn),marketingCarrierCode=car,
                 operatingFlightNumber=int(fn),operatingCarrierCode=car,flightId=f"{car}#{int(fn)}#{r['date']}#{o}")
        it=dict(origin=o,destination=d,associatedSegments=[seg])
        out.append(dict(bound=j+1,boundRph=j+1,isOAL=False,promisedItinerary=it,actualItinerary=it))
    return out

def make_dds(r):
    pid=r["pnr_id"]
    dds=dict(eventMetadata=dict(trigger="DISRUPTION_DETECTION_SERVICE",timestamp=f"{r['date']}T05:30:00.000Z"),
             pnrIdentifier=dict(pnrId=pid,pnr=r["loc"]),itineraryDetails=itinerary(r),
             compensationEligibility=[],socFlightEligibility=[],
             seatFeeRefundEligibility=[],baggageRefundEligibility=[])
    if r["suite"]=="seat":
        rows=[]
        # r['seat'] is list over segments; each is list over passengers
        for j,segrows in enumerate(r["seat"]):
            for pidx,sp in enumerate(segrows):
                rows.append(dict(segmentId=f"{pid}-ST-{j+1}",passengerId=f"{pid}-PT-{pidx+1}",passengerType="ADT",
                    emdNumber=emd_num(sp["emd"],hash(pid)%900+100,j+1),eligibilityStatus=sp["status"],
                    systemCode=sp["syscode"],reason=sp["reason"],currency="CAD",amount=sp["amount"],
                    bookingSource="AC_MOBILE",emdCouponStatus=sp["coupon"],
                    hasSeatCharacteristicsChanged=sp["char"],fopCode=sp["fop"],formOfPayment=sp["fop"]))
        dds["seatFeeRefundEligibility"]=rows
    else:
        bsegs=[]
        for j,(ahl,paxrows) in enumerate(r["bag"]):
            o,d,car,fn=r["route"][j]
            pe=[]
            for pidx,bp in enumerate(paxrows):
                pe.append(dict(passengerId=f"{pid}-PT-{pidx+1}",passengerType="ADT",
                    emdNumber=emd_num(bp["emd"],hash(pid)%900+100,j+1),eligibilityStatus=bp["status"],
                    systemCode=bp["syscode"],reason=bp["reason"],currency="CAD",amount=bp["amount"],
                    fopCode=bp["fop"],formOfPayment=bp["fop"]))
            bsegs.append(dict(boundRph=j+1,segmentId=f"{pid}-ST-{j+1}",carrierCode=car,flightNumber=int(fn),
                departureAirport=o,arrivalAirport=d,segmentStatus="HK",
                isAHLPresent=ahl["isAHL"],
                # ahlCreationDate must be CONSISTENT with waitPeriodSatisfied: a "wait NOT satisfied"
                # case (BAG_TC011) needs an AHL <72h old, else the bot computing the wait from this
                # timestamp contradicts the flag. Honour a per-case r["ahl_date"] override.
                ahlCreationDate=(r.get("ahl_date") or f"{r['date']}T10:00:00Z") if ahl["isAHL"] else None,
                reportType=ahl["reportType"],waitPeriodSatisfied=ahl.get("wait"),
                bookingSource="AC_MOBILE",passengerEligibility=pe))
        dds["baggageRefundEligibility"]=bsegs
    json.dump(dds,open(f"{DDSW}/{pid}.dds.json","w"),indent=1)
    return dds

# ---- publish / cascade / finalize -----------------------------------------
def render_publish_one(r):
    make_scenario(r)
    nd=f"{NDJW}/{r['loc']}.ndjson"
    subprocess.run(["python3",SENG,"render","--scenario",f"{SCENW}/{r['pnr_id']}.json","--out",nd,
                    "--canvas",CANVAS],check=True,capture_output=True)
    out=subprocess.run(["python3",PUB,"--ndjson",nd,"--brokers",CRT["brokers"],"--topic",CRT["topic"],"--live"],
                       capture_output=True,text=True)
    return ("produced" in (out.stdout+out.stderr)),(out.stdout+out.stderr)

def cascaded(conn,pids):
    cur=conn.cursor(); cur.execute("select pnr_id from trip where pnr_id = any(%s)",(pids,))
    return {x[0] for x in cur.fetchall()}

def _locdigits(loc):
    """Locator -> 12 numeric digits (2 per char). Letters A-Z map to 01-26, DIGITS 0-9 map to 27-36.
    Digits MUST be handled: `ord('2')-64` is negative, which produced values like '182218-14-16-15'
    (minus signs, >13 chars) and blew up ticket.primary_document_number varchar(13) for locators such
    as RVR201 / AC1525. 6 chars -> 12 digits, + 1 pax digit = exactly 13."""
    out=[]
    for ch in str(loc).upper():
        out.append(f"{ord(ch)-64:02d}" if ch.isalpha() else f"{27+int(ch):02d}")
    return "".join(out)

def finalize_one(r,ttc):
    cur=ttc.cursor(); iss="2026-06-01"; pid=r["pnr_id"]
    # primary_document_number must be GLOBALLY unique — the ticket table has a unique index on it and
    # `on conflict do nothing` silently DROPS a colliding insert (→ 0 ticket rows). The old
    # f"{TPREFIX}{seq}{k}" scheme collided with pre-existing 0143xx tickets. Derive from the locator,
    # which is unique per PNR and steers clear of the 0143xx range.
    locd=_locdigits(r["loc"])
    for k in range(r["npax"]):
        dn=f"{locd}{k}"
        cur.execute("""insert into ticket
            (primary_document_number,pnr_id,passenger_id,ticket_id,document_numbers,issuance_local_date,document_type)
            values (%s,%s,%s,%s,ARRAY[%s],%s,'T') on conflict do nothing""",
            (dn,pid,f"{pid}-PT-{k+1}",f"{dn}-{iss}",dn,iss))
    cur.execute("update passenger set date_of_birth=%s where pnr_id=%s",(DOB,pid))
    ttc.commit()
    key=f"traces/DDS/{r['date']}/{uuid.uuid4()}/response.json"
    make_dds(r)
    _sess.client("s3").put_object(Bucket=CRT["s3_bucket"],Key=key,
        Body=open(f"{DDSW}/{pid}.dds.json","rb").read(),ContentType="application/json")
    return key

def pin_all(recs,keys):
    conn=re_conn(); cur=conn.cursor(); ents=[r["pnr_id"] for r in recs]
    cur.execute("delete from execution_traces where service_type='DDS' and entity_id = any(%s) and correlation_id=%s",(ents,CORR))
    cur.executemany("""insert into execution_traces
        (id,service_type,correlation_id,entity_id,processed_at,request_s3_key,response_s3_key)
        values (gen_random_uuid(),'DDS',%s,%s,%s,NULL,%s)""",
        [(CORR,r["pnr_id"],PIN_TS,keys[r["pnr_id"]]) for r in recs])
    conn.commit(); conn.close(); return len(recs)

_ctx=ssl.create_default_context(); _ctx.check_hostname=False; _ctx.verify_mode=ssl.CERT_NONE
def verify_one(r):
    pid=r["pnr_id"]
    try:
        req=urllib.request.Request(CRT["endpoint"]+pid,headers={"x-api-key":CRT["api_key"]})
        with urllib.request.urlopen(req,context=_ctx,timeout=25) as resp: b=json.load(resp)
    except Exception as e:
        return dict(pnr_id=pid,tc=r["tc"],ok=False,detail=str(e)[:80])
    if r["suite"]=="seat":
        got=b.get("seatFeeRefundEligibility",[]) or []
        exp=[sp for seg in r["seat"] for sp in seg]
        if r["note"]=="no_emd":
            return dict(pnr_id=pid,tc=r["tc"],ok=(len(got)==0),detail=f"seat rows={len(got)} (want 0)")
        codes_ok=len(got)==len(exp) and all(got[i].get("systemCode")==exp[i]["syscode"] for i in range(len(exp)))
        return dict(pnr_id=pid,tc=r["tc"],ok=codes_ok,detail=f"seat {len(got)}/{len(exp)} codes={[g.get('systemCode') for g in got]}")
    else:
        got=b.get("baggageRefundEligibility",[]) or []
        exp=r["bag"]
        if r["note"]=="no_emd":
            allpe=[p for s in got for p in s.get("passengerEligibility",[])]
            return dict(pnr_id=pid,tc=r["tc"],ok=(len(allpe)==0),detail=f"bag pe={len(allpe)} (want 0)")
        ok=len(got)==len(exp)
        for j,(ahl,paxrows) in enumerate(exp):
            if j>=len(got): ok=False; break
            pe=got[j].get("passengerEligibility",[])
            if len(pe)!=len(paxrows) or got[j].get("isAHLPresent")!=ahl["isAHL"]: ok=False
            for k,bp in enumerate(paxrows):
                if k<len(pe) and pe[k].get("systemCode")!=bp["syscode"]: ok=False
        return dict(pnr_id=pid,tc=r["tc"],ok=ok,detail=f"bag segs={len(got)}/{len(exp)}")

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("phase"); ap.add_argument("--start",type=int,default=0); ap.add_argument("--end",type=int,default=10**9)
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
        ttc=tt_conn(); keys={}
        for i,r in enumerate(sl):
            try: keys[r["pnr_id"]]=finalize_one(r,ttc); print(f"  [{a.start+i}] {r['pnr_id']} {r['tc']} finalized",flush=True)
            except Exception as e: print(f"  [{a.start+i}] {r['pnr_id']} ERR {e}",flush=True)
        ttc.close()
        n=pin_all([r for r in sl if r["pnr_id"] in keys],keys)
        print(f"[finalize] tickets/DOB/S3 done; pinned {n} DDS rows")
    elif a.phase=="verify":
        res=[verify_one(r) for r in sl]; ok=sum(1 for x in res if x["ok"])
        for x in res:
            if not x["ok"]: print("  FAIL",x)
        print(f"[verify] {ok}/{len(sl)} match expected systemCodes")
        json.dump(res,open(f"{WORK}/anc_verify.json","w"),indent=1)
    else: print("unknown phase"); sys.exit(2)

if __name__=="__main__": main()
