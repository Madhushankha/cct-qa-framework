#!/usr/bin/env python3
import os
"""Build NON-MVP UAT test PNRs in the CRT environment (trip-tracer cascade only).

Non-MVP use cases are NON-AUTOMATED: the chatbot routes them to the Claims Dashboard
for MANUAL handling. There is NO eligibility service, NO DDS, NO entitlement/compensation
logic (manual_path = "non_mvp_topic"). So — unlike FD/ANC (pinned DDS) or Name Correction
(live stateless eligibility endpoint) — this builder ONLY needs to cascade a retrievable
booking into trip-tracer so the chatbot can:
    * IDENTIFY the customer (GenUC-01)  -> name + PNR in trip/passenger
    * AUTHENTICATE via OTP-PNR (GenUC-05) -> email/phone in eds contact
    * JOURNEY / SEGMENT selection (GenUC-08 / GenUC-18a) -> flight_segment rows

Dimensions the PNR ENCODES (seedable): passenger name, itinerary geography
(domestic-CA / transborder-US / China / EU country), travel-state (post vs future),
pax count, ticket.
Dimensions the PNR does NOT encode (loyalty-service / chatbot gated, documented per case):
    * loyalty tier SE / VIP        -> SLA override, skill CR Exec (loyalty service)
    * Aeroplan membership          -> OTP-Aeroplan, TO routing (loyalty service)
    * country of RESIDENCE          -> collected in chat at GLOB-20c (not from PNR)
    * team / SLA / manual_path      -> Claims Dashboard routing (agentic layer)
The raw ALTEA-PNRDATA schema has no loyalty field, so SE/VIP/Aeroplan identification
must be seeded by the loyalty/CP service or driven manually in the chat — noted in `note`.

Cases with NO booking (Denied Boarding-No-Booking, pure FAQ Joining-Aeroplan, generic
routing / OTP-not-required non-booking complaints) are listed in NO_PNR and NOT seeded.

Phases (idempotent / resumable):
  index        -> _NMVP_crt_index.json  (fresh locators + tickets)
  publish      render scenario -> publish booking to CRT PNR Kafka
  checkcascade how many landed in trip-tracer
  finalize     ticket + DOB + supersede dup ACTIVE trips
Usage: AWS_PROFILE=ac-cct-crt python3 nmvp_crt_build.py <phase> [--start N] [--end N]
Validate with:  AWS_PROFILE=ac-cct-crt python3 nmvp_checkpoints.py
"""
import json, os, sys, subprocess, argparse, datetime, random, glob
import psycopg2
import _cctdb
import crt_uniqnames as U
UNIQ = os.environ.get("CRT_UNIQ_NAMES") == "1"   # opt-in: shared unique-name assignment (default OFF)

KB   = os.environ.get("CCTQA_DATAGEN_ROOT",
                      os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SENG = f"{KB}/scripts/scenario_engine.py"
PUB  = f"{KB}/scripts/publish_raw.py"
CANVAS = f"{KB}/scenarios/_canvas/pnr_creation_domestic_ac.json"
WORK = "/tmp/cctqa-datagen/nmvp_work"
SCENW=f"{WORK}/scenarios"; NDJW=f"{WORK}/ndjson"
for d in (SCENW,NDJW): os.makedirs(d, exist_ok=True)
OUT = os.environ.get("NMVP_OUT", f"{WORK}/_NMVP_crt_index.json")

CRT = dict(
  profile=os.environ.get("AWS_PROFILE","ac-cct-crt"), region="ca-central-1",
  brokers=("b-1.accctmskcrtcac1.05hf7o.c4.kafka.ca-central-1.amazonaws.com:9092,"
           "b-2.accctmskcrtcac1.05hf7o.c4.kafka.ca-central-1.amazonaws.com:9092,"
           "b-3.accctmskcrtcac1.05hf7o.c4.kafka.ca-central-1.amazonaws.com:9092"),
  topic="emh-dev.ALTEA-PNRDATA-UAT",
  tt_host="ac-cct-trip-tracer-rds-cluster-crt-cac1.cluster-cxqe2wacy866.ca-central-1.rds.amazonaws.com",
  tt_db="trip-tracer", tt_user="dbadmin", tt_pass=os.environ.get("CCT_TRIPTRACER_PASSWORD", ""),
)
EMAIL=os.environ.get("CRT_EMAIL","lahiru@ae-qa1-aircanada.mailinator.com")
PHONE=os.environ.get("CRT_PHONE","+94712534323")
DOB="1986-04-23"
TPREFIX=os.environ.get("NMVP_TPREFIX","014312")     # ticket series (block 9000000+ verified free)
TBASE0 =int(os.environ.get("NMVP_TBASE","9000000"))
SEED   =int(os.environ.get("NMVP_SEED","312312"))
def docnum(r,k): return f"{TPREFIX}{r['tbase']+k:07d}"

TODAY=datetime.datetime.now(datetime.timezone.utc).date()
POST_DEP=(TODAY-datetime.timedelta(days=5)).isoformat()    # travel completed 5d ago
POST_BOOK=(TODAY-datetime.timedelta(days=45)).isoformat()  # booked 45d before travel
FUT_DEP=(TODAY+datetime.timedelta(days=30)).isoformat()    # future travel +30d
FUT_BOOK=(TODAY-datetime.timedelta(days=5)).isoformat()    # booked 5d ago

# itinerary presets: list of (origin, destination) legs, all AC-marketed/operated
ITIN={
 "DOM":   [("YYZ","YUL")],   # domestic Canada (Toronto-Montreal)
 "DOM_R": [("YUL","YYZ")],   # Montreal origin (TC-002 blurb)
 "US":    [("YYZ","LGA")],   # transborder US (to/from US -> APPR/US regs)
 "CHINA": [("YVR","PVG")],   # China itinerary
 "FR":    [("YYZ","CDG")],   # France (EU)
 "DE":    [("YYZ","FRA")],   # Germany (EU)
 "UK":    [("YYZ","LHR")],   # United Kingdom
 "ES":    [("YYZ","MAD")],   # Spain (EU)
 "PT":    [("YYZ","LIS")],   # Portugal (EU)
}

# ---- CASES ------------------------------------------------------------------
# C(tc, name, itin_key, state, npax, team, otp, note)
#   state: "POST"=completed travel | "FUT"=upcoming travel
#   otp:   "PNR" | "Aeroplan" | "NotRequired"
#   note:  loyalty / residence / routing dimension NOT encoded in the PNR (documented)
def C(tc,name,itin,state,npax,team,otp,note=""):
    return dict(tc=tc,name=name,itin=itin,state=state,npax=npax,team=team,otp=otp,note=note)

CASES=[
 C("TC-NMVP-001","Baggage Damage — Post-Travel (BG)","DOM","POST",1,"BG","PNR"),
 C("TC-NMVP-002","Baggage Pilferage — Post-Travel (BG)","DOM_R","POST",1,"BG","PNR","YUL origin per blurb"),
 C("TC-NMVP-003","Baggage/Special Items — Insurance Requests (BG)","DOM","POST",1,"BG","PNR"),
 C("TC-NMVP-004","Baggage/Special Items — On Board Damages (BG)","DOM","POST",1,"BG","PNR"),
 C("TC-NMVP-005","Non-MVP Topic Must Not Route into Automated Flows","DOM","POST",1,"BG","PNR","proves manual_path=non_mvp_topic (no DDS)"),
 C("TC-NMVP-006","Denied Boarding — Post-Travel (CR)","DOM","POST",1,"CR","PNR"),
 C("TC-NMVP-007","Downgrade — Post-Travel (CR)","DOM","POST",1,"CR","PNR"),
 C("TC-NMVP-009","Insurance Request (Travel Disruptions) (CR)","DOM","POST",1,"CR","PNR"),
 C("TC-NMVP-011","Service Experience — Airport & Ground — Post-Travel (CR)","DOM","POST",1,"CR","PNR"),
 C("TC-NMVP-012","Service Experience — In-Flight — Post-Travel (CR)","DOM","POST",1,"CR","PNR"),
 C("TC-NMVP-018","Accessibility — Seating & Extra Space — Post-Travel (CR)","DOM","POST",1,"CR","PNR","pre-travel branch = LAH/CC"),
 C("TC-NMVP-019","Accessibility — ATPDR/DOT382 — Post-Travel (CR)","US","POST",1,"CR","PNR","US itinerary invokes DOT382"),
 C("TC-NMVP-020","Accessibility — Medical Devices — Post-Travel (CR)","DOM","POST",1,"CR","PNR","pre-travel branch = LAH/CC"),
 C("TC-NMVP-021","Aeroplan — Account Merges (TO)","DOM","POST",1,"TO","Aeroplan","LOYALTY: Aeroplan member (loyalty-service gated)"),
 C("TC-NMVP-022","Aeroplan — Missing Flight Points — Post-Travel (TO)","DOM","POST",1,"TO","Aeroplan","LOYALTY: Aeroplan member + flown segment for missing points"),
 C("TC-NMVP-023","Aeroplan — Booking Issues — Post-Travel (CR)","DOM","POST",1,"CR","Aeroplan","LOYALTY: Aeroplan member; routing flip to CR"),
 C("TC-NMVP-024","Aeroplan — Account Closure (TO)","DOM","POST",1,"TO","Aeroplan","LOYALTY: Aeroplan member (loyalty-service gated)"),
 C("TC-NMVP-025","Aeroplan — Profile Updates (TO)","DOM","POST",1,"TO","Aeroplan","LOYALTY: Aeroplan member (loyalty-service gated)"),
 C("TC-NMVP-029","Ancillary Refund (Wi-Fi) — Post-Travel (CR)","DOM","POST",1,"CR","PNR"),
 C("TC-NMVP-030","Death/Imminent Death Refund — Post-Travel (RS)","DOM","POST",1,"RS","PNR"),
 C("TC-NMVP-031","Passenger Ticket Refund Request — Post-Travel (CR)","DOM","POST",1,"CR","PNR"),
 C("TC-NMVP-032","Call to Duty Refund Request (RS)","DOM","POST",1,"RS","PNR"),
 C("TC-NMVP-033","Tax Exemption Refund Request (RS)","DOM","POST",1,"RS","PNR"),
 C("TC-NMVP-039","Baggage Damage — SE Passenger — SLA 2d — CR Exec","DOM","POST",1,"CR Exec","PNR","LOYALTY: Super Elite -> SLA override 2d (loyalty-service gated)"),
 C("TC-NMVP-041","Baggage Damage — SE + EU Resident (France) — BGE LHR","FR","POST",1,"BGE LHR","PNR","LOYALTY: SE; RESIDENCE: France (chat); itinerary EU"),
 C("TC-NMVP-042","Baggage Pilferage — EU Resident (Germany) — BGE LHR","DE","POST",1,"BGE LHR","PNR","RESIDENCE: Germany (chat); itinerary EU"),
 C("TC-NMVP-043","SE — Airport & Ground — EU Resident (UK) — CR LHR","UK","POST",1,"CR LHR","PNR","RESIDENCE: United Kingdom (chat); itinerary UK"),
 C("TC-NMVP-044","Denied Boarding — US Itinerary — SLA 1d","US","POST",1,"CR","PNR","US itinerary (to/from US) -> SLA 24h"),
 C("TC-NMVP-045","Denied Boarding — Canada/Intl Itinerary — SLA 2d","DOM","POST",1,"CR","PNR","non-US itinerary -> SLA 48h"),
 C("TC-NMVP-046","Ancillary Refund — US Itinerary — SLA 7d","US","POST",1,"CR","PNR","US itinerary -> SLA override 7d"),
 C("TC-NMVP-047","Baggage Damage — China Itinerary — SLA 7d","CHINA","POST",1,"BG","PNR","China itinerary -> SLA override 7d"),
 C("TC-NMVP-048","Ticket Refund — China Resident — SLA 7d","CHINA","POST",1,"RS","PNR","RESIDENCE: China (chat); itinerary China"),
 C("TC-NMVP-049","Denied Boarding — Spain Resident — SLA 15d","ES","POST",1,"CR","PNR","RESIDENCE: Spain (chat); itinerary EU"),
 C("TC-NMVP-050","Downgrade — Portugal Resident — SLA 15d","PT","POST",1,"CR","PNR","RESIDENCE: Portugal (chat); itinerary EU"),
 C("TC-NMVP-051","Denied Boarding — SE + Spain Resident — SLA 2d (shortest wins)","ES","POST",1,"CR Exec","PNR","LOYALTY: SE; RESIDENCE: Spain (chat)"),
 C("TC-NMVP-052","Ancillary Refund — VIP + US Itinerary — SLA 2d (shortest wins)","US","POST",1,"CR Exec","PNR","LOYALTY: VIP; US itinerary"),
 C("TC-NMVP-054","Ancillary Refund Mid-Flow — Context Parking (mobility question)","DOM","POST",1,"CR","PNR","multi-intent context-parking test"),
 C("TC-NMVP-055","Delayed Baggage — Future Travel PNR — Travel-State Mismatch","DOM","FUT",1,"BG","PNR","UPCOMING travel (not yet departed) -> mismatch handling"),
]

# Cases NOT seeded (no retrievable booking / pure routing / FAQ) — documented, not built.
NO_PNR=[
 ("TC-NMVP-008","Denied Boarding — No Booking — N/A Handling: customer has NO PNR by design."),
 ("TC-NMVP-010","Service Experience — Contact Centre (CR) — OTP Not Required, non-booking complaint."),
 ("TC-NMVP-013","Service Experience — Social Media (CR) — OTP Not Required, non-booking."),
 ("TC-NMVP-014","Service Experience — Tarmac Delay (CR) — OTP Not Required, non-booking."),
 ("TC-NMVP-015","Service Experience — Customer Recovery & Care (CR) — OTP Not Required, non-booking."),
 ("TC-NMVP-016","Tech/Digital — Mobile App (CR) — routing-flip test, no booking dependency."),
 ("TC-NMVP-017","Tech/Digital — Website — pre/post routing (CC/CR) — OTP Not Required, no booking."),
 ("TC-NMVP-026","Aeroplan — Partners/Charities (TO) — third-party, OTP TBD, no member booking."),
 ("TC-NMVP-027","AC Product — eUpgrades (CR) — routing-flip test, no booking dependency."),
 ("TC-NMVP-028","AC Product — AC Wallet (CC/CR) — OTP Not Required, no booking dependency."),
 ("TC-NMVP-034","OAL Initiated Ticket Refund (RS) — OTP Not Required, OAL-issued, no AC booking retrieval."),
 ("TC-NMVP-035","TA Initiated Refund (RS) — OTP Not Required, travel-agent-issued."),
 ("TC-NMVP-036","Billing & Payments — Fraud Concerns (CR) — OTP Not Required, no booking dependency."),
 ("TC-NMVP-037","Miscellaneous Intent — travel-state routing test, no booking dependency."),
 ("TC-NMVP-038","OTP Failure — 'Not Required' OTP allows continuation — OTP-not-required category."),
 ("TC-NMVP-040","Service Experience — VIP Contact Centre (CR Exec) — loyalty-only, OTP not required, no booking."),
 ("TC-NMVP-053","Joining Aeroplan — FAQ Only — no case creation, no booking."),
]

# ---- fresh globally-unique names --------------------------------------------
_FIRSTS=["ELENA","MARCUS","NADIA","OLIVER","PRIYA","QUENTIN","ROSALIE","TOBIAS","URSULA","VICTOR",
         "WENDELL","XIMENA","YOSEF","ZARA","ADRIANO","BIANCA","CEDRIC","DELPHINE","EMILIO","FREYA",
         "GAVINO","HELENA","ISMAEL","JOSEPHINE","KAMAL","LOUISA","MATEO","NORAH","OSVALDO","PAOLA",
         "RAFAEL","SIENNA","THEODORE","VALENTINA","WESLEY","YOLANDA","ARTURO","BEATRIX","CONRAD","DIANNE"]
_LASTS =["OKAFOR","VANCE","LINDGREN","BARRERA","FONTAINE","HALVORSEN","IBARRA","KOWALSKI",
         "MARCHESI","NAKASHIMA","OYELARAN","PRZYBYLSKI","QUIROGA","ROSSETTI","SVENSSON","TANIGUCHI",
         "URBANEK","VILLANUEVA","WEATHERBY","ZIELINSKI","ASHWORTH","BRENNAN","CALDERON","DUBOIS",
         "ELLSWORTH","FAIRWEATHER","GALLAGHER","HOLM","IRIARTE","JANSEN","KILBRIDE","LARSSON",
         "MONTALVO","NORDSTROM","ODUYA","PENHALIGON","RADFORD","STRANDBERG","THORNTON","VESTERGAARD"]

def tt_conn(): return _cctdb.trip_tracer(CRT["tt_host"], profile=CRT.get("profile"))

def prior_full_names():
    names=set()
    try:
        conn=tt_conn(); cur=conn.cursor()
        cur.execute("select distinct first_name,last_name from passenger")
        for f,l in cur.fetchall():
            if f and l: names.add(f"{f} {l}")
        conn.close()
    except Exception as e: print(f"[warn] prior_full_names DB read failed: {e}")
    for fp in glob.glob(f"{WORK}/_NMVP_crt*_index.json"):
        try:
            for r in json.load(open(fp)):
                for p in r["paxs"]: names.add(f"{p[0]} {p[1]}")
        except Exception: pass
    return names

def taken_locators():
    conn=tt_conn(); cur=conn.cursor(); cur.execute("select distinct pnr from trip"); t={r[0] for r in cur.fetchall()}
    conn.close(); return t

def gen_locators(n, seed, taken):
    rng=random.Random(seed); A="ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"; out=[]; used=set()
    while len(out)<n:
        loc="".join(rng.choice(A) for _ in range(6))
        if loc in used or loc in taken or not loc[0].isalpha(): continue
        used.add(loc); out.append(loc)
    return out

def plan_names(n, seed, exclude):
    rng=random.Random(seed+7); used=set(exclude); out=[]
    lasts=_LASTS[:]; rng.shuffle(lasts); firsts=_FIRSTS[:]; rng.shuffle(firsts)
    li=fi=0
    for _ in range(n):
        while True:
            fn=firsts[fi%len(firsts)]; ln=lasts[li%len(lasts)]; fi+=1
            if fi%len(firsts)==0: li+=1
            if f"{fn} {ln}" not in used: break
        used.add(f"{fn} {ln}"); out.append((fn,ln))
    return out

# ---- index ------------------------------------------------------------------
def build_index():
    taken=taken_locators(); excl=prior_full_names()
    locs=gen_locators(len(CASES), SEED, taken)
    npax_total=sum(c["npax"] for c in CASES)
    names=plan_names(npax_total, SEED, excl)
    clash=excl & {f"{f} {l}" for f,l in names}
    assert not clash, f"name collision: {clash}"
    print(f"[index] fresh locators: {locs[:5]}... | {len(excl)} prior names excluded, 0 collisions")
    recs=[]; ni=0
    for i,c in enumerate(CASES):
        state=c["state"]
        bdate = POST_BOOK if state=="POST" else FUT_BOOK
        dep   = POST_DEP  if state=="POST" else FUT_DEP
        paxs=[(names[ni+k][0],names[ni+k][1],"ADT") for k in range(c["npax"])]; ni+=c["npax"]
        pid=f"{locs[i]}-{bdate}"
        recs.append(dict(tc=c["tc"],name=c["name"],pnr=locs[i],pnr_id=pid,
            booking_date=bdate,dep_date=dep,state=state,itin=c["itin"],legs=ITIN[c["itin"]],
            paxs=paxs,npax=c["npax"],team=c["team"],otp=c["otp"],note=c["note"],
            tbase=TBASE0+i*10,ticket=f"{TPREFIX}{TBASE0+i*10:07d}",email=EMAIL,phone=PHONE))
    if UNIQ:                                            # opt-in shared unique names (sets pax_names/uniq_names)
        _c=tt_conn(); U.assign_names(recs, lambda r: r["npax"], _c, seed=8502); _c.close()
        print(f"[index] CRT_UNIQ_NAMES: assigned DB-absent unique names to {sum(r['npax'] for r in recs)} pax")
    json.dump(recs,open(OUT,"w"),indent=1)
    print(f"[index] {len(recs)} PNRs -> {OUT}  (+{len(NO_PNR)} NO-PNR cases documented)")
    return recs
def load_index(): return json.load(open(OUT))

# ---- scenario ---------------------------------------------------------------
def seg_times(dep_date, segidx):
    h=8+segidx*4
    dl=f"{dep_date}T{h:02d}:30:00"; al=f"{dep_date}T{h+3:02d}:45:00"
    du=f"{dep_date}T{h+4:02d}:30:00Z"; au=f"{dep_date}T{h+7:02d}:45:00Z"
    return dl,al,du,au

def make_scenario(r):
    bdate=r["booking_date"]; dep=r["dep_date"]
    pax=[dict(type="ADT",first_name=p[0],last_name=p[1],gender="U",
              date_of_birth=DOB,email=r["email"],phone=r["phone"]) for p in r["paxs"]]
    segs=[]
    for j,(o,d) in enumerate(r["legs"]):
        dl,al,du,au=seg_times(dep,j)
        segs.append(dict(carrier="AC",operating_carrier="AC",flight_number=str(870+j),operating_flight_number=str(870+j),
                         origin=o,destination=d,dep_local=dl,arr_local=al,dep_utc=du,arr_utc=au,
                         booking_datetime=f"{bdate}T10:00:00Z",aircraft="789",cabin="Y",status="HK",arrival_terminal="2A"))
    scn=dict(**{"$schema_version":2},scenario_id=r["pnr_id"],title=f"{r['tc']}: {r['name']} [{r['pnr']}]",
        description=r["name"],canvas="_canvas/pnr_creation_domestic_ac.json",contains_pii=False,
        identity=dict(pnr=r["pnr"],booking_date=bdate,type="PNR"),
        point_of_sale=dict(office_id="YTOAA08AA",iata_number="01424012",system_code="AC",agent_type="AIRLINE",
                           agent_numeric_sign="0001",agent_initials="NM",duty_code="SU",agent_country="CA",agent_city="YUL"),
        last_modification_comment=f"SIM-{r['tc']}-NMVP-CRT",creation_comment=f"SIM-{r['tc']}-NMVP-CRT",
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
    for k in range(r["npax"]):
        tk=docnum(r,k)
        cur.execute("""insert into ticket
            (primary_document_number,pnr_id,passenger_id,ticket_id,document_numbers,issuance_local_date,document_type)
            values (%s,%s,%s,%s,ARRAY[%s],%s,'T') on conflict do nothing""",
            (tk,pid,f"{pid}-PT-{k+1}",f"{tk}-{bdate}",tk,bdate))
    cur.execute("update passenger set date_of_birth=%s where pnr_id=%s",(DOB,pid))
    cur.execute("update trip set status='INACTIVE' where pnr=%s and pnr_id<>%s and status='ACTIVE'",(r["pnr"],pid))
    cur.execute("update trip set status='ACTIVE' where pnr_id=%s",(pid,))
    ttc.commit()

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
        ttc.close(); print("[finalize] tickets/DOB/supersede done")
    else: print("unknown phase"); sys.exit(2)

if __name__=="__main__": main()
