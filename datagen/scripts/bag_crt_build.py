#!/usr/bin/env python3
import os
import _cctdb
"""Build BAGGAGE-CLAIM UAT test PNRs in the CRT environment.

UNLIKE FD / SOC / ANC-fee-refund, the baggage-CLAIM flow (delayed bag, lost bag
content reimbursement, interim expenses, live tracking) is NOT rule-engine-DDS
driven.  The rule-engine DB has NO baggage tables.  Baggage eligibility comes
from SmartSuite bag events that cascade into trip-tracer's `baggage_updates`
table.  The chatbot reads those.  SmartSuite itself is PDT-only / no QA access,
so the established workaround (4,945 pre-existing ZZ-prefixed test PNRs prove it)
is to seed `baggage_updates` DIRECTLY.  Clean CCT template rows use
  source_system_id=1, user_name='CONTRAIL', workstation_name='CCT-AUTO'.

AHL lifecycle -> event_type:
  BAG_CREATED / BAG_ACCEPTED           bag checked in
  BAG_DELAYED_RECORD_CREATED           AHL opened      (tracer_reference_id = AHL ref)
  BAG_DELAYED_DELIVERED                bag delivered
  BAG_DELAYED_RECORD_CLOSED            AHL closed
  BAG_ONLOADED / BAG_LOADED_ON_AIRCRAFT / BAG_POSITIONED_ON_FLIGHT_LEG   live tracking
  BAG_DELIVERED_TO_CAROUSEL            tracking finished (expired window)
  BAG_PROPERTY_ADDED (ExceptionData)   RDS / priority flags

Booking (trip / passenger / segments / ticket / DOB + lahiru OTP contact) still
seeds through the normal scenario_engine -> publish_raw -> CRT Kafka path, same
as every other build; the cascade produces eds_pnr_output carrying the contact.

UAT031/032 are Flight-Disruption PAYMENT cases -> they ride the FD
compensationEligibility DDS (S3 + execution_traces pin), not baggage data.

Delay windows are RELATIVE to BAG_TODAY (default 2026-07-10).  Re-run with a
fresh BAG_TODAY to re-date the whole set close to a new test cycle.

Phases (idempotent / resumable):
  index          -> _BAG_crt_index.json  (fresh locators + tickets)
  publish        render scenario -> publish booking to CRT PNR Kafka
  checkcascade   how many landed in trip-tracer
  finalize       ticket + DOB + baggage_updates events + FD DDS pin (031/032)
  verify         assert baggage_updates events (+ FD DDS) match expected
Usage: AWS_PROFILE=ac-cct-crt python3 bag_crt_build.py <phase> [--start N] [--end N]
"""
import json, os, sys, uuid, subprocess, ssl, urllib.request, argparse, random, datetime
import boto3, psycopg2
import crt_uniqnames as U     # shared DB-absent unique-name assigner/checker
import crt_uniqnames as U

UNIQ = os.environ.get("CRT_UNIQ_NAMES") == "1"   # opt-in DB-absent unique passenger names (default OFF)

KB   = os.environ.get("CCTQA_DATAGEN_ROOT",
                      os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SENG = f"{KB}/scripts/scenario_engine.py"
PUB  = f"{KB}/scripts/publish_raw.py"
CANVAS = f"{KB}/scenarios/_canvas/pnr_creation_domestic_ac.json"
WORK = os.environ.get("BAG_WORK","/tmp/cctqa-datagen/bag_work")
SCENW=f"{WORK}/scenarios"; DDSW=f"{WORK}/dds"; NDJW=f"{WORK}/ndjson"
for d in (SCENW,DDSW,NDJW): os.makedirs(d, exist_ok=True)
OUT = os.environ.get("BAG_OUT", f"{WORK}/_BAG_crt_index.json")

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
DOB="1986-04-23"                       # established lahiru identity (matches prior builds)
PIN_TS="2028-12-31 00:00:00+00"        # FD DDS pin wins ORDER BY (031/032 only)
TPREFIX=os.environ.get("BAG_TPREFIX","014305")
SEED=int(os.environ.get("BAG_SEED","424242"))
NAME_OFFSET=int(os.environ.get("BAG_NAME_OFFSET","0"))
CORR="qa-bag-crt"
TODAY=datetime.date.fromisoformat(os.environ.get("BAG_TODAY","2026-07-10"))

# passenger-name pool (globally unique first x last)
FIRST=["OLIVIA","LIAM","EMMA","NOAH","AVA","WILLIAM","SOPHIA","BENJAMIN","ISABELLA","LUCAS",
       "MIA","HENRY","CHARLOTTE","THEODORE","AMELIA","JACK","HARPER","OLIVER","EVELYN","JAMES",
       "ABIGAIL","ETHAN","EMILY","ALEXANDER","ELIZABETH","DANIEL","SOFIA","MATTHEW","VICTORIA","JOSEPH",
       "GRACE","SAMUEL","CHLOE","DAVID","PENELOPE","CARTER","LAYLA","OWEN","RILEY","GABRIEL"]
LAST =["OSBORNE","WHITFIELD","LANGDON","PRESCOTT","ELLERY","FAIRBANKS","HOLLOWAY","MERCER","REDMOND","SINCLAIR",
       "THORNE","VANCE","WESTBROOK","ASHWORTH","BRAMBLE","CALDWELL"]
def name_pool(offset=0):
    i=0
    for ln in LAST:
        for fn in FIRST:
            if i>=offset: yield (fn, ln)
            i+=1

_sess=boto3.Session(profile_name=CRT["profile"], region_name=CRT["region"])
def tt_conn(): return _cctdb.trip_tracer(CRT["tt_host"], profile=CRT.get("profile"))
def re_conn(): return psycopg2.connect(host=CRT["re_host"],port=5432,dbname=CRT["re_db"],user=CRT["re_user"],password=CRT["re_pass"],sslmode="require",connect_timeout=25)

# ---- routes (leg = origin,dest,marketing_carrier,operating_carrier,flight_no) --
ACDOM =[("YYZ","YVR","AC","AC","456")]                 # AC last carrier, domestic
ACLHR =[("YUL","LHR","AC","AC","100")]                 # AC operated intl
ACYYC =[("YUL","YYC","AC","AC","789")]
OALAST=[("YYZ","FRA","AC","AC","870"),("FRA","MUC","LH","LH","1234")]  # last carrier OAL (LH)
OALFULL=[("YYZ","LAX","UA","UA","456")]                # fully OAL-operated (responsible airline OAL)
TWOLEG=[("YYZ","YUL","AC","AC","456"),("YUL","YVR","AC","AC","789")]   # 2 legs (2 bags UAT021)

# ---- 39-case table ----------------------------------------------------------
# ahl states: open|delivered|closed|none|nobag|track|track_none|track_expired|rds_short|fd
C=[]
def case(tc,feat,npax=1,route=ACDOM,off=-10,ahl="open",ref=None,nbag=1,samelast=True,
         extra_refs=None,indep=None,note=""):
    C.append(dict(tc=tc,feat=feat,npax=npax,route=route,off=off,ahl=ahl,ref=ref,nbag=nbag,
                  samelast=samelast,extra_refs=extra_refs or [],indep=indep,note=note))

case("UAT_TC001","Delayed Bag within 21d, AC last carrier, AHL found -> Bag Recovery",off=-10,ahl="open",ref="YYZAC12345")
case("UAT_TC002","Delayed Bag past 21d -> End Flow",off=-28,ahl="open")
case("UAT_TC003","Delayed Bag, OAL last carrier -> Redirect",route=OALAST,off=-10,ahl="nobag",note="last carrier OAL")
case("UAT_TC004","Delayed Bag, OAL last carrier, dispute -> Manual",route=OALAST,off=-10,ahl="nobag",indep="dispute")
case("UAT_TC005","Delayed Bag within 21d, no AHL -> Redirect to creation",off=-10,ahl="nobag")
case("UAT_TC006","Delayed Bag no AHL, dispute -> Manual",off=-10,ahl="nobag",indep="dispute")
case("UAT_TC007","Delayed Bag exactly day 21 -> Accepted",off=-21,ahl="open")
case("UAT_TC008","Lost Bag Content <SDR single pax Canada Interac -> Payment",off=-28,ahl="open",indep="Canada/Interac/<SDR")
case("UAT_TC009","Lost Bag Content item >$300 proof -> Manual",off=-28,ahl="open",indep="item>$300")
case("UAT_TC010","Lost Bag duplicate claim -> Blocked",off=-28,ahl="open",indep="duplicate(prior claim not seedable)")
case("UAT_TC011","Lost Bag but delivered -> Not eligible",off=-28,ahl="delivered")
case("UAT_TC012","Lost Bag report >51d -> End Flow",off=-56,ahl="open")
case("UAT_TC013","Lost Bag item>$300 invalid proof retry -> Manual",off=-28,ahl="open",indep="item>$300/proof")
case("UAT_TC014","Lost Bag multi-pax same AHL all<$300 -> Automated",npax=2,off=-28,ahl="open",samelast=True)
case("UAT_TC015","Content+Interim >SDR US bank transfer -> Capped",off=-28,ahl="open",indep="US/combined>SDR")
case("UAT_TC016","Lost Bag life-event keywords -> Disclaimer -> Automated",off=-28,ahl="open",indep="life-event kw")
case("UAT_TC017","Interim Expenses within 21d Nigeria EFT -> Payment",off=-10,ahl="open",indep="Nigeria/EFT/non-Aeroplan")
case("UAT_TC018","Interim past 21d dispute -> Manual",off=-28,ahl="open",indep="dispute")
case("UAT_TC019","Interim non-essential rejected -> Partial",off=-10,ahl="open",indep="non-essential items")
case("UAT_TC020","Live Tracking single bag -> Real-time status",off=2,ahl="track",nbag=1)
case("UAT_TC021","Live Tracking multiple bags -> Status cards",route=TWOLEG,off=2,ahl="track",nbag=2)
case("UAT_TC022","Live Tracking no record dispute -> Manual",off=2,ahl="track_none",indep="dispute")
case("UAT_TC023","Live Tracking expired -> End",off=-30,ahl="track_expired")
case("UAT_TC024","Baggage service unavailable -> End",off=-10,ahl="open",indep="service downtime (env)")
case("UAT_TC025","Other airline responsible -> Redirect",route=OALFULL,off=-10,ahl="nobag",note="responsible airline OAL (booking-level)")
case("UAT_TC026","Bag content dispute -> Manual",off=-28,ahl="open",indep="dispute amount")
case("UAT_TC027","Interim expense dispute -> Manual",off=-28,ahl="open",indep="dispute rejected items")
case("UAT_TC028","Combined claim disputes both -> Manual",off=-28,ahl="open",indep="dispute both")
case("UAT_TC029","Content exceeds SDR items>$300 -> Manual",off=-28,ahl="open",indep="content>SDR/item>$300")
case("UAT_TC030","Check Delivery Status -> Redirect to Live Tracking",off=2,ahl="track",nbag=1)
case("UAT_TC031","FD cheque France not supported -> Bank transfer",route=ACLHR,off=-3,ahl="fd",indep="France")
case("UAT_TC032","FD cheque Canada no Interac -> Automated",route=ACDOM,off=-3,ahl="fd",indep="Canada/no-Interac")
case("UAT_TC033","AHL closed -> End Flow",off=-28,ahl="closed")
case("UAT_TC034","Interim multi-pax same last name same AHL -> Automated",npax=3,off=-10,ahl="open",samelast=True)
case("UAT_TC035","Interim multi-pax diff last names 2 AHLs -> Automated",npax=2,off=-10,ahl="open",
     samelast=False,ref="YYZAC11111",extra_refs=["YYZAC22222"])
case("UAT_TC036","Delayed>21d bag delivered, interim only -> Manual",off=-28,ahl="delivered",ref="YYZAC36036")
case("UAT_TC037","Content alone exceeds SDR -> Interim not allowed",off=-28,ahl="open",ref="YYZAC37037",indep="content>SDR")
case("UAT_TC038","Lost Bag >51d interim -> End Flow",off=-56,ahl="open",ref="YYZAC38038")
case("UAT_TC039","Short delay 1h20m AHL delivered RDS flag -> Manual",off=-10,ahl="rds_short",ref="YYZAC39039")

CASES=C

# ---- locator generation (fresh, collision-checked at index time) -----------
def gen_locators(n, seed):
    rng=random.Random(seed); A="ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"; out=[]; taken=set()
    while len(out)<n:
        loc="BG"+"".join(rng.choice(A) for _ in range(4))     # BG-prefix, identifiable
        if loc in taken: continue
        taken.add(loc); out.append(loc)
    return out

def flight_date(off): return (TODAY+datetime.timedelta(days=off)).isoformat()

def build_index():
    locs=gen_locators(len(CASES),SEED)
    # collision check against live trip
    ttc=tt_conn(); cur=ttc.cursor()
    pids0=[f"{locs[i]}-{flight_date(CASES[i]['off'])}" for i in range(len(CASES))]
    cur.execute("select pnr_id from trip where pnr_id=any(%s)",(pids0,)); clash={r[0] for r in cur.fetchall()}
    ttc.close()
    if clash: print("[WARN] locator collision, bump BAG_SEED:",clash); sys.exit(3)
    pool=name_pool(NAME_OFFSET); recs=[]
    for i,c in enumerate(CASES):
        loc=locs[i]; date=flight_date(c["off"]); pid=f"{loc}-{date}"
        if c["samelast"]:
            fn,ln=next(pool); pax_names=[[next(pool)[0],ln] for _ in range(c["npax"])]
        else:
            pax_names=[]; seenln=set()                     # force DISTINCT last names
            while len(pax_names)<c["npax"]:
                f,l=next(pool)
                if l in seenln: continue
                seenln.add(l); pax_names.append([f,l])
        ref=c["ref"] or f"{c['route'][-1][0]}AC{10000+i*7:05d}"
        recs.append(dict(tc=c["tc"],feat=c["feat"],loc=loc,pnr_id=pid,date=date,off=c["off"],
                         npax=c["npax"],route=c["route"],ahl=c["ahl"],ref=ref,extra_refs=c["extra_refs"],
                         nbag=c["nbag"],samelast=c["samelast"],indep=c["indep"],note=c["note"],
                         pax_names=pax_names,ticket=f"{TPREFIX}{i+1:06d}",email=EMAIL,phone=PHONE))
    if UNIQ:   # overwrite pax_names with globally-unique DB-absent names + flag uniq_names for the checkpoint
        _c=tt_conn()
        try: U.assign_names(recs, lambda r: r["npax"], _c, seed=772001)
        finally: _c.close()
        # preserve same-last-name scenarios (TC014/TC034): share pax[0]'s (globally-unique,
        # DB-absent) surname across the family with DISTINCT first names -> pairs stay unique
        for r in recs:
            if r["samelast"] and r["npax"]>1:
                ln=r["pax_names"][0][1]
                for j,nm in enumerate(r["pax_names"]):
                    nm[0]=U._FIRST[(sum(map(ord,r["pnr_id"]))+j)%len(U._FIRST)].upper(); nm[1]=ln
                r["pax"]=f"{r['pax_names'][0][0]} {ln}"
    json.dump(recs,open(OUT,"w"),indent=1)
    print(f"[index] {len(recs)} baggage cases -> {OUT}  (TODAY={TODAY})")
    return recs

def load_index(): return json.load(open(OUT))

# ---- booking scenario -------------------------------------------------------
def seg_times(date,segidx):
    h=9+segidx*4
    dep=f"{date}T{h:02d}:00:00"; arr=f"{date}T{h+3:02d}:00:00"
    return dep,arr,f"{date}T{h+4:02d}:00:00Z",f"{date}T{h+7:02d}:00:00Z"

def make_scenario(r):
    date=r["date"]; pax=[]
    for k in range(r["npax"]):
        nm=r["pax_names"][k]
        pax.append(dict(type="ADT",first_name=nm[0],last_name=nm[1],gender="U",
                        date_of_birth=DOB,email=r["email"],phone=r["phone"]))
    segs=[]
    for j,rt in enumerate(r["route"]):
        o,d,mc,oc,fn=rt; dl,al,du,au=seg_times(date,j)
        segs.append(dict(carrier=mc,operating_carrier=oc,flight_number=fn,operating_flight_number=fn,
                         origin=o,destination=d,dep_local=dl,arr_local=al,dep_utc=du,arr_utc=au,
                         booking_datetime=None,aircraft="320",cabin="Y",status="HK",arrival_terminal="1"))
    scn=dict(**{"$schema_version":2},scenario_id=r["pnr_id"],title=f"{r['tc']}: {r['feat']} [{r['loc']}]",
             description=r["feat"],canvas="_canvas/pnr_creation_domestic_ac.json",contains_pii=False,
             identity=dict(pnr=r["loc"],booking_date=date,type="PNR"),
             point_of_sale=dict(office_id="YULAC010V",iata_number="01424012",system_code="1A",agent_type="AIRLINE",
                                agent_numeric_sign="0001",agent_initials="AN",duty_code="SU",agent_country="CA",agent_city="YUL"),
             last_modification_comment=f"SIM-{r['tc']}-BAG-CRT",creation_comment=f"SIM-{r['tc']}-BAG-CRT",
             passengers=pax,segments=segs,
             ticketing=dict(issuance_local_date="2026-06-01",fare=dict(amount="450.00",currency="CAD"),
                            ticket_numbers=[r["ticket"]]),
             timeline=[dict(version=0,at=f"{date}T08:00:00Z",action="bootstrap",description="Pre-ticketing stub"),
                       dict(version=1,at=f"{date}T08:00:01Z",action="ticketing_added",description="Ticketing reference attached")])
    json.dump(scn,open(f"{SCENW}/{r['pnr_id']}.json","w"),indent=1)
    return scn

# ---- FD compensation DDS (UAT031/032 only) --------------------------------
def itinerary(r):
    pid=r["pnr_id"]; out=[]
    for j,rt in enumerate(r["route"]):
        o,d,mc,oc,fn=rt; dl,al,du,au=seg_times(r["date"],j)
        seg=dict(segmentId=f"{pid}-ST-{j+1}",segmentStatus="HK",
                 departureDatetime=du.replace("Z","+00:00"),arrivalDatetime=au.replace("Z","+00:00"),
                 departureAirport=o,arrivalAirport=d,marketingFlightNumber=int(fn),marketingCarrierCode=mc,
                 operatingFlightNumber=int(fn),operatingCarrierCode=oc,flightId=f"{oc}#{int(fn)}#{r['date']}#{o}")
        it=dict(origin=o,destination=d,associatedSegments=[seg])
        out.append(dict(bound=j+1,boundRph=j+1,isOAL=False,promisedItinerary=it,actualItinerary=it))
    return out

def make_fd_dds(r):
    pid=r["pnr_id"]; o,d,mc,oc,fn=r["route"][0]
    regime="EU" if r["tc"]=="UAT_TC031" else "CA"
    comp=[dict(regime=regime,boundRph=1,
        mslFlight=dict(segmentId=f"{pid}-ST-1",carrierCode=mc,flightNumber=fn,departureAirport=o,
                       arrivalAirport=d,isStarSegment=False,isOalSegment=False),
        disruptionType="INVOLUNTARY",delayMinutes=240,delayType="CONTROLLABLE",delayCode="64",
        customerFriendlyDisruptionReason="Eligible for expense reimbursement.",disruptionReason="MECHANICAL",
        passengerEligibility=[dict(passengerId=f"{pid}-PT-{k+1}",passengerType="ADT",
            eligibilityStatus="ELIGIBLE",systemCode=("FD-EU-EL-01" if regime=="EU" else "FD-CA-EL-01"),
            reason="Eligible for compensation",failureReasons=None) for k in range(r["npax"])])]
    dds=dict(eventMetadata=dict(trigger="DISRUPTION_DETECTION_SERVICE",timestamp=f"{r['date']}T05:30:00.000Z"),
             pnrIdentifier=dict(pnrId=pid,pnr=r["loc"]),itineraryDetails=itinerary(r),
             compensationEligibility=comp,socFlightEligibility=[],seatFeeRefundEligibility=[])
    json.dump(dds,open(f"{DDSW}/{pid}.dds.json","w"),indent=1)
    return dds

# ---- baggage_updates event generation -------------------------------------
def _epoch_ms(dt): return int((dt-datetime.datetime(1970,1,1,tzinfo=datetime.timezone.utc)).total_seconds()*1000)

def bag_tag(pid,b): return "0014"+f"{(abs(hash((pid,b)))%900000)+100000}"

def bag_events(r):
    """Return list of baggage_updates row-dicts for this PNR."""
    pid=r["pnr_id"]; date=r["date"]; ahl=r["ahl"]
    if ahl=="fd" or ahl=="track_none": return []          # no baggage rows
    o,d,mc,oc,fn=r["route"][-1]                             # last leg = mishandle station
    base=datetime.datetime.fromisoformat(date+"T13:00:00+00:00")
    rows=[]
    def row(bag_idx,etype,ts,**kw):
        d0=dict(bag_tag_number=bag_tag(pid,bag_idx),event_type=etype,pnr_id=pid,
                station_code=o,event_time=_epoch_ms(ts),event_store_id=(abs(hash((pid,etype,bag_idx)))%9_000_000_000)+1_000_000_000,
                source_system_id=1,carrier_code=oc,inbound_carrier_code=oc,
                flight_carrier_code=oc,flight_number=fn.rjust(4),flight_departure_station_code=o,
                flight_arrival_station_code=d,flight_departure_date_local=date,
                user_name="CONTRAIL",workstation_name="CCT-AUTO",commodity_id=1001,
                master_bag_id=(abs(hash(pid))%9_000_000)+100_000,
                passenger_name=(f"{r['pax_names'][min(bag_idx,r['npax']-1)][1]}/{r['pax_names'][min(bag_idx,r['npax']-1)][0]}"),
                timestamp=ts,received_at=ts+datetime.timedelta(seconds=15))
        d0.update(kw); rows.append(d0)
    nb=max(r["nbag"],r["npax"])
    refs=[r["ref"]]+r["extra_refs"]
    for b in range(nb):
        ref=refs[b] if b<len(refs) else r["ref"]
        # every bag: created + accepted
        row(b,"BAG_CREATED",base,bag_tag_status="Active",bag_category="B  ")
        row(b,"BAG_ACCEPTED",base+datetime.timedelta(minutes=5),bag_tag_status="Accepted")
        if ahl in ("open","delivered","closed","rds_short"):
            row(b,"BAG_DELAYED_RECORD_CREATED",base+datetime.timedelta(hours=1),
                tracer_reference_id=ref,mishandled_type="DELAYED",mishandled_trigger_type="AHL",
                bag_tag_status="DELAYED",bag_category="BAG")
        if ahl=="rds_short":
            row(b,"BAG_PROPERTY_ADDED",base+datetime.timedelta(hours=1,minutes=2),
                property_name="ExceptionData",property_value="RDS;PRIO",tracer_reference_id=ref)
            row(b,"BAG_DELAYED_DELIVERED",base+datetime.timedelta(hours=1,minutes=20),
                tracer_reference_id=ref,delivery_timestamp=base+datetime.timedelta(hours=1,minutes=20),
                delivery_info='{"status":"delivered"}',bag_tag_status="Delivered")
        if ahl=="delivered":
            row(b,"BAG_DELAYED_DELIVERED",base+datetime.timedelta(days=1),
                tracer_reference_id=ref,delivery_timestamp=base+datetime.timedelta(days=1),
                delivery_info='{"status":"delivered"}',bag_tag_status="Delivered")
        if ahl=="closed":
            row(b,"BAG_DELAYED_RECORD_CLOSED",base+datetime.timedelta(days=2),
                tracer_reference_id=ref,is_success=True,bag_tag_status="Accepted")
        if ahl=="track":
            row(b,"BAG_ONLOADED",base+datetime.timedelta(minutes=30),bag_tag_status="Loaded")
            row(b,"BAG_LOADED_ON_AIRCRAFT",base+datetime.timedelta(minutes=45),bag_tag_status="Loaded",load_position_name=f"FWD-{b+1}")
            row(b,"BAG_POSITIONED_ON_FLIGHT_LEG",base+datetime.timedelta(minutes=50),bag_tag_status="Loaded")
        if ahl=="track_expired":
            row(b,"BAG_DELIVERED_TO_CAROUSEL",base+datetime.timedelta(hours=4),
                delivery_timestamp=base+datetime.timedelta(hours=4),bag_tag_status="Delivered")
        # ahl=="nobag": only created+accepted (bag checked, no delayed record)
    return rows

BAG_COLS=["bag_tag_number","event_type","pnr_id","station_code","event_time","event_store_id",
  "source_system_id","carrier_code","inbound_carrier_code","flight_carrier_code","flight_number",
  "flight_departure_station_code","flight_arrival_station_code","flight_departure_date_local",
  "user_name","workstation_name","commodity_id","master_bag_id","passenger_name","timestamp",
  "received_at","tracer_reference_id","mishandled_type","mishandled_trigger_type","bag_tag_status",
  "bag_category","property_name","property_value","delivery_timestamp","delivery_info",
  "load_position_name","is_success"]

def insert_bag_rows(ttc,rows):
    cur=ttc.cursor()
    for row in rows:
        vals=[row.get(c) for c in BAG_COLS]
        ph=",".join(["%s"]*len(BAG_COLS))
        cur.execute(f"insert into baggage_updates (id,{','.join(BAG_COLS)}) values (gen_random_uuid(),{ph})",vals)
    ttc.commit()

# ---- publish / cascade / finalize -----------------------------------------
def render_publish_one(r):
    make_scenario(r); nd=f"{NDJW}/{r['loc']}.ndjson"
    subprocess.run(["python3",SENG,"render","--scenario",f"{SCENW}/{r['pnr_id']}.json","--out",nd,
                    "--canvas",CANVAS],check=True,capture_output=True)
    out=subprocess.run(["python3",PUB,"--ndjson",nd,"--brokers",CRT["brokers"],"--topic",CRT["topic"],"--live"],
                       capture_output=True,text=True)
    return ("produced" in (out.stdout+out.stderr)),(out.stdout+out.stderr)

def cascaded(conn,pids):
    cur=conn.cursor(); cur.execute("select pnr_id from trip where pnr_id = any(%s)",(pids,))
    return {x[0] for x in cur.fetchall()}

def finalize_one(r,ttc):
    cur=ttc.cursor(); iss="2026-06-01"; pid=r["pnr_id"]; tk=r["ticket"]
    for k in range(r["npax"]):
        cur.execute("""insert into ticket
            (primary_document_number,pnr_id,passenger_id,ticket_id,document_numbers,issuance_local_date,document_type)
            values (%s,%s,%s,%s,ARRAY[%s],%s,'T') on conflict do nothing""",
            (f"{tk}{k}",pid,f"{pid}-PT-{k+1}",f"{tk}{k}-{iss}",f"{tk}{k}",iss))
    cur.execute("update passenger set date_of_birth=%s where pnr_id=%s",(DOB,pid))
    ttc.commit()
    # baggage events (idempotent: clear our prior rows for this pnr first)
    cur.execute("delete from baggage_updates where pnr_id=%s and user_name='CONTRAIL' and workstation_name='CCT-AUTO'",(pid,))
    ttc.commit()
    rows=bag_events(r); insert_bag_rows(ttc,rows)
    return len(rows)

def finalize_fd(recs):
    fd=[r for r in recs if r["ahl"]=="fd"]
    if not fd: return 0
    keys={}
    for r in fd:
        make_fd_dds(r); key=f"traces/DDS/{r['date']}/{uuid.uuid4()}/response.json"
        _sess.client("s3").put_object(Bucket=CRT["s3_bucket"],Key=key,
            Body=open(f"{DDSW}/{r['pnr_id']}.dds.json","rb").read(),ContentType="application/json")
        keys[r["pnr_id"]]=key
    conn=re_conn(); cur=conn.cursor(); ents=[r["pnr_id"] for r in fd]
    cur.execute("delete from execution_traces where service_type='DDS' and entity_id = any(%s) and correlation_id=%s",(ents,CORR))
    cur.executemany("""insert into execution_traces
        (id,service_type,correlation_id,entity_id,processed_at,request_s3_key,response_s3_key)
        values (gen_random_uuid(),'DDS',%s,%s,%s,NULL,%s)""",
        [(CORR,r["pnr_id"],PIN_TS,keys[r["pnr_id"]]) for r in fd])
    conn.commit(); conn.close(); return len(fd)

# ---- verify ----------------------------------------------------------------
EXPECT={   # ahl state -> set of event_types that MUST be present (per bag)
 "open":{"BAG_CREATED","BAG_ACCEPTED","BAG_DELAYED_RECORD_CREATED"},
 "delivered":{"BAG_DELAYED_RECORD_CREATED","BAG_DELAYED_DELIVERED"},
 "closed":{"BAG_DELAYED_RECORD_CREATED","BAG_DELAYED_RECORD_CLOSED"},
 "rds_short":{"BAG_DELAYED_RECORD_CREATED","BAG_PROPERTY_ADDED","BAG_DELAYED_DELIVERED"},
 "nobag":{"BAG_CREATED","BAG_ACCEPTED"},
 "track":{"BAG_CREATED","BAG_LOADED_ON_AIRCRAFT","BAG_POSITIONED_ON_FLIGHT_LEG"},
 "track_expired":{"BAG_CREATED","BAG_DELIVERED_TO_CAROUSEL"},
 "track_none":set(),
}
def verify_one(r,ttc):
    pid=r["pnr_id"]; cur=ttc.cursor()
    if r["ahl"]=="fd":
        try:
            req=urllib.request.Request(CRT["endpoint"]+pid,headers={"x-api-key":CRT["api_key"]})
            ctx=ssl.create_default_context(); ctx.check_hostname=False; ctx.verify_mode=ssl.CERT_NONE
            with urllib.request.urlopen(req,context=ctx,timeout=25) as resp: b=json.load(resp)
            ce=b.get("compensationEligibility",[]) or []
            ok=len(ce)>0 and ce[0]["passengerEligibility"][0]["eligibilityStatus"]=="ELIGIBLE"
            return dict(tc=r["tc"],pid=pid,ok=ok,detail=f"FD comp={len(ce)} status={ce[0]['passengerEligibility'][0]['eligibilityStatus'] if ce else 'NONE'}")
        except Exception as e: return dict(tc=r["tc"],pid=pid,ok=False,detail=f"FD endpoint err {str(e)[:50]}")
    cur.execute("select event_type,tracer_reference_id from baggage_updates where pnr_id=%s and user_name='CONTRAIL'",(pid,))
    got=cur.fetchall(); types={x[0] for x in got}; refs={x[1] for x in got if x[1]}
    need=EXPECT.get(r["ahl"],set())
    ok=need.issubset(types)
    if r["ahl"] not in ("nobag","track","track_expired","track_none","fd"):
        ok=ok and (r["ref"] in refs)
    if r["ahl"]=="track_none": ok=(len(got)==0)
    return dict(tc=r["tc"],pid=pid,ok=ok,detail=f"types={sorted(types)} refs={sorted(refs)}")

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
        ttc=tt_conn(); tot=0
        for i,r in enumerate(sl):
            try: n=finalize_one(r,ttc); tot+=n; print(f"  [{a.start+i}] {r['pnr_id']} {r['tc']} {n} bag rows",flush=True)
            except Exception as e: print(f"  [{a.start+i}] {r['pnr_id']} ERR {e}",flush=True)
        ttc.close()
        nfd=finalize_fd(sl)
        print(f"[finalize] tickets/DOB/{tot} baggage rows done; FD DDS pinned {nfd}")
    elif a.phase=="verify":
        ttc=tt_conn(); res=[verify_one(r,ttc) for r in sl]; ttc.close()
        ok=sum(1 for x in res if x["ok"])
        for x in res:
            if not x["ok"]: print("  FAIL",x)
        print(f"[verify] {ok}/{len(sl)} match expected events")
        json.dump(res,open(f"{WORK}/bag_verify.json","w"),indent=1)
    else: print("unknown phase"); sys.exit(2)

if __name__=="__main__": main()
