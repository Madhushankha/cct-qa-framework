#!/usr/bin/env python3
import os
import _cctdb
"""SOC UAT 84-case set in CRT — port of soc_uat_int_build.py (same case derivation
and DDS shapes, imported from it) onto the CRT infra from crt_fd_build.py:
  topic emh-dev.ALTEA-PNRDATA-UAT · trip-tracer direct dbadmin · rule-engine Aurora
  direct adminuser (execution_traces pin, PIN_TS 2028) · S3 cct-ask-ac-crt-logs
Contact: lahiru@ae-qa1-aircanada.mailinator.com / +94712534323 · tickets 014357.
Phases: gen | publish | checkcascade | finalize | edsinject | verify
"""
import json, os, sys, copy, uuid, subprocess, argparse, ssl, urllib.request
import boto3, psycopg2
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import soc_uat_int_build as S      # CASES, derive(), dds(), paxname(), gen_locators via B
import int_fd_build as B           # gen_locators only (no INT session use)
import crt_uniqnames as U
import pnr_common_checks as C      # gateway_down() fallback (rule-engine 403 env-wide lockout)

KB   = os.environ.get("CCTQA_DATAGEN_ROOT",
                      os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
FD=f"{KB}/scenarios/fd-sit"; DDST=f"{FD}/_dds-templates"
SENG=f"{KB}/scripts/scenario_engine.py"; PUB=f"{KB}/scripts/publish_raw.py"
WORK="/tmp/cctqa-datagen/crt_socuat_work"
SCENW=f"{WORK}/scenarios"; DDSW=f"{WORK}/dds"; NDJW=f"{WORK}/ndjson"
for d in (SCENW,DDSW,NDJW): os.makedirs(d, exist_ok=True)

EMAIL="lahiru@ae-qa1-aircanada.mailinator.com"; PHONE="+94712534323"; DOB="1986-04-23"
PIN_TS="2028-06-30 00:00:00+00"
# --tag selects the set: "" = original CRT set (mailinator, tickets 014357);
# B/C = unique-name clone sets (lahiru aircanada email, tickets 014358/014359)
SET_TAGS={"":("014357",575757,"lahiru@ae-qa1-aircanada.mailinator.com"),
          "B":("014358",575758,"lahiru.premathilake@aircanada.ca"),
          "C":("014359",575759,"lahiru.premathilake@aircanada.ca"),
          "D":("014360",575760,"lahiru.premathilake@aircanada.ca"),
          "E":("014361",575761,"lahiru.premathilake@aircanada.ca"),
          "F":("014362",575762,"lahiru@ae-qa1-aircanada.mailinator.com"),
          "G":("014363",575763,"lahiru@ae-qa1-aircanada.mailinator.com"),
          "H":("014364",575764,"lahiru.premathilake@aircanada.ca"),
          "I":("014365",575765,"lahiru@ae-qa1-aircanada.mailinator.com")}
TAG=""; TPREFIX="014357"; SEED=575757
IDX=f"{FD}/_FD_SOCUAT84_crt_index.json"
def set_tag(tag):
    global TAG,TPREFIX,SEED,IDX,EMAIL
    TAG=tag; TPREFIX,SEED,EMAIL=SET_TAGS[tag]
    IDX=f"{FD}/_FD_SOCUAT84_crt{tag}_index.json"

CRT=dict(profile="ac-cct-crt", region="ca-central-1",
  brokers=("b-1.accctmskcrtcac1.05hf7o.c4.kafka.ca-central-1.amazonaws.com:9092,"
           "b-2.accctmskcrtcac1.05hf7o.c4.kafka.ca-central-1.amazonaws.com:9092,"
           "b-3.accctmskcrtcac1.05hf7o.c4.kafka.ca-central-1.amazonaws.com:9092"),
  topic="emh-dev.ALTEA-PNRDATA-UAT",
  tt_host="ac-cct-trip-tracer-rds-cluster-crt-cac1.cluster-cxqe2wacy866.ca-central-1.rds.amazonaws.com",
  tt_db="trip-tracer", tt_user="dbadmin", tt_pass=os.environ.get("CCT_TRIPTRACER_PASSWORD", ""),
  re_host="ac-cct-rule-engine-crt-cac1-rds-cluster.cluster-cxqe2wacy866.ca-central-1.rds.amazonaws.com",
  re_db="postgres", re_secret="/crtca1/ac-cct-rule-engine-crt-cac1-cluster/db-credentials",
  s3_bucket="cct-ask-ac-crt-logs",
  endpoint="https://rule-engine-platform-service-be.ac-cct-crt.cloud.aircanada.com/rule-engine/dds/output/",
  api_key=os.environ.get("DDS_API_KEY", ""))

_sess=boto3.Session(profile_name=CRT["profile"], region_name=CRT["region"])
def tt_conn():
    return _cctdb.trip_tracer(CRT["tt_host"], profile=CRT.get("profile"))
def re_conn():
    s=json.loads(_sess.client("secretsmanager").get_secret_value(SecretId=CRT["re_secret"])["SecretString"])
    return psycopg2.connect(host=CRT["re_host"],port=5432,dbname=CRT["re_db"],
        user=s["adminuser"],password=s["adminpassword"],sslmode="require",connect_timeout=20)

def gen():
    import glob
    base=json.load(open(S.BASE)); taken=set()
    for f in glob.glob(f"{FD}/_FD_*index.json"):
        try:
            for e in json.load(open(f)):
                if e.get("pnr_id"): taken.add(e["pnr_id"][:6])
        except Exception: pass
    locs=B.gen_locators(len(S.CASES), SEED, taken)
    recs=[]
    UNIQ=os.environ.get("CRT_UNIQ_NAMES")=="1"       # opt-in unique passenger names
    urecs=[{"npax":1} for _ in S.CASES]              # one passenger per SOC-UAT PNR
    if UNIQ:
        _c=tt_conn()                                 # CRT trip-tracer passenger table
        try: U.assign_names(urecs, lambda r:r["npax"], _c, seed=911003+SEED%9973)
        finally: _c.close()
    for i,c in enumerate(S.CASES):
        cfg=S.derive(c); loc=locs[i]; pid=f"{loc}-{cfg['date']}"; name=S.paxname(i)
        fn,ln=name.split(" ",1)
        if UNIQ:
            name=urecs[i]["pax"]; fn,ln=urecs[i]["pax_names"][0]
        dep_l,arr_l,dep_u,arr_u=S.times(cfg["date"])
        s=copy.deepcopy(base)
        s["scenario_id"]=pid; s["identity"]["pnr"]=loc; s["identity"]["booking_date"]=cfg["date"]
        s["title"]=f"{c['id']} {c['req']}: {c['name'][:60]} - {name} [{loc}] CRT"
        s["description"]=f"{c['id']} | {c['req']} | {cfg['soc_val']} | CRT"
        s["creation_comment"]=s["last_modification_comment"]=f"SIM-{c['id']}-CRT"
        s["ticketing"]["ticket_numbers"]=[f"{TPREFIX}{i+1:06d}1"[:13]]
        s["classification"]=dict(primary_code=c["id"], primary_name=f"SOC UAT {c['req']} CRT", confidence="high")
        s["tags"]=["synthetic","soc-uat-crt",cfg["reg"].lower(),cfg["st"].lower()]
        s["passengers"]=[dict(type="ADT",first_name=fn,last_name=ln,gender="U",
                              date_of_birth=DOB,email=EMAIL,phone=PHONE)]
        if cfg["emp"]:
            s["point_of_sale"]=dict(s["point_of_sale"]); s["point_of_sale"]["office_id"]="YULAC01ES"
        s["segments"]=[dict(carrier=cfg["carr"], operating_carrier="AC",
            flight_number=cfg["fno"], operating_flight_number=cfg["fno"],
            origin=cfg["orig"], destination=cfg["dest"],
            dep_local=dep_l, arr_local=arr_l, dep_utc=dep_u, arr_utc=arr_u,
            booking_datetime=None, aircraft="789", cabin="Y", status="HK", arrival_terminal="1")]
        if cfg["exc"]:
            loy=[{"type":"loyaltyRequest","id":f"{pid}-OT-300","code":"FQTV",
                  "serviceProvider":{"code":"AC"},
                  "membership":{"number":f"9162{i+1:05d}","membershipType":"INDIVIDUAL"},
                  "status":"HK",
                  "traveler":{"type":"stakeholder","id":f"{pid}-PT-1","ref":"processedPnr.travelers"}}]
            ev=next((t for t in s.get("timeline",[]) if t.get("version")==1),None)
            if ev is not None: ev.setdefault("overrides",{})["/loyaltyRequests"]=loy
        s["expected_cascade"]["db_end_state"]["trip"].update(pnr=loc,pnr_id=pid)
        s["expected_cascade"]["db_end_state"]["flight_segment"]["rows"]=1
        json.dump(s,open(f"{SCENW}/{pid}.json","w"),indent=1)
        json.dump(s,open(f"{FD}/{pid}.json","w"),indent=1)
        d=S.dds(pid,loc,cfg)
        json.dump(d,open(f"{DDSW}/{pid}.dds.json","w"),indent=1)
        json.dump(d,open(f"{DDST}/{pid}.dds.json","w"),indent=1)
        recs.append(dict(tc=c["id"], old_tc=c.get("old_id",c["id"]), req=c["req"], title=c["name"], loc=loc, pnr_id=pid, date=cfg["date"],
            ticket=s["ticketing"]["ticket_numbers"][0], pax=name, route=f"{cfg['orig']}-{cfg['dest']}",
            flight=f"{cfg['carr']}{cfg['fno']}", regime=cfg["reg"], soc_status_class=cfg["st"],
            legs=[dict(n=1, carrier=cfg["carr"], flight=f"{cfg['carr']}{cfg['fno']}",
                       sector=f"{cfg['orig']}-{cfg['dest']}",
                       soc_status={"EL":"ELIGIBLE","NE":"NOT_ELIGIBLE","ND":"NO_DETERMINATION","PE":"PENDING"}[cfg["st"]],
                       soc_code=cfg["soc_code"], role=cfg["st"])],
            status=cfg["comp"]["status"], syscode=cfg["comp"]["code"],
            amount=cfg["comp"]["amount"], currency=cfg["comp"]["currency"],
            delay=cfg["delay"], dcode=cfg["dcode"], dtyp=cfg["dtyp"], cat=cfg["cat"],
            emp=cfg["emp"], exc=cfg["exc"], override=cfg["override"],
            email=EMAIL, phone=PHONE, pin=True, group=False,
            claim_exempt=bool(cfg["date"]<"2024-01-01")))   # outside-limitation cases fly OLD by design
        if UNIQ:
            recs[-1]["pax_names"]=urecs[i]["pax_names"]; recs[-1]["uniq_names"]=True
    json.dump(recs,open(IDX,"w"),indent=1)
    print(f"[gen] {len(recs)} -> {IDX}")

def load(): return json.load(open(IDX))

def publish(sl):
    ok=0
    for i,r in enumerate(sl):
        nd=f"{NDJW}/{r['loc']}.ndjson"
        subprocess.run(["python3",SENG,"render","--scenario",f"{SCENW}/{r['pnr_id']}.json","--out",nd],
                       check=True, capture_output=True)
        out=subprocess.run(["python3",PUB,"--ndjson",nd,"--brokers",CRT["brokers"],
                            "--topic",CRT["topic"],"--live"], capture_output=True, text=True)
        good="produced" in (out.stdout+out.stderr)
        ok+=good; print(f"  [{i}] {r['tc']} {r['pnr_id']} {'OK' if good else 'FAIL '+(out.stdout+out.stderr)[-140:]}",flush=True)
    print(f"[publish] {ok}/{len(sl)}")

def checkcascade(sl):
    cn=tt_conn(); cur=cn.cursor(); pids=[r["pnr_id"] for r in sl]
    cur.execute("select pnr_id from trip where pnr_id=any(%s)",(pids,)); have={x[0] for x in cur.fetchall()}
    cur.execute("select pnr_id,count(*) from eds_pnr_output where pnr_id=any(%s) group by pnr_id",(pids,))
    eds={a:b for a,b in cur.fetchall()}; cn.close()
    print(f"[cascade] trips {len(have)}/{len(pids)} | eds {len(eds)} | missing: {[p for p in pids if p not in have][:6]}")

def finalize(sl):
    cn=tt_conn(); keys={}
    for r in sl:
        cur=cn.cursor(); pid=r["pnr_id"]; tk=r["ticket"]
        cur.execute("""insert into ticket (primary_document_number,pnr_id,passenger_id,ticket_id,document_numbers,issuance_local_date,document_type)
            values (%s,%s,%s,%s,ARRAY[%s],%s,'T') on conflict do nothing""",
            (tk,pid,f"{pid}-PT-1",f"{tk}-2026-06-01",tk,"2026-06-01"))
        cur.execute("update passenger set date_of_birth=%s where pnr_id=%s",(DOB,pid))
        cn.commit()
        key=f"traces/DDS/{r['date']}/{pid}/response.json"
        _sess.client("s3").put_object(Bucket=CRT["s3_bucket"],Key=key,
            Body=open(f"{DDSW}/{pid}.dds.json","rb").read(),ContentType="application/json")
        keys[pid]=key
    cn.close(); print(f"[finalize] tickets/DOB/S3 done for {len(keys)}")
    rc=re_conn(); cur=rc.cursor()
    ents=[r["pnr_id"] for r in sl if r["pnr_id"] in keys]
    cur.execute("delete from execution_traces where service_type='DDS' and entity_id=any(%s) and correlation_id like 'qa-pin-crt-%%'",(ents,))
    for r in sl:
        pid=r["pnr_id"]
        if pid not in keys: continue
        cur.execute("""insert into execution_traces (id,service_type,correlation_id,entity_id,processed_at,request_s3_key,response_s3_key)
                       values (gen_random_uuid(),'DDS',%s,%s,%s,NULL,%s)""",
                    (f"qa-pin-crt-{r['loc']}",pid,PIN_TS,keys[pid]))
    rc.commit(); rc.close(); print(f"[pin] {len(ents)} execution_traces rows (direct psycopg2)")

def edsinject(sl):
    cn=tt_conn(); cur=cn.cursor()
    BC=json.dumps({"bookingSource":"AC_VACATIONS","bookingType":"REVENUE","bookingSubtype":"REVENUE","gdsLocator":"AMADEUS"})
    done=0
    for r in sl:
        pid=r["pnr_id"]
        cur.execute("SELECT count(*) FROM eds_pnr_output WHERE pnr_id=%s",(pid,))
        if cur.fetchone()[0]>0: continue
        segs=[f"{pid}-ST-1"]
        bounds=[{"boundRph":1,"origin":r["route"].split("-")[0],"destination":r["route"].split("-")[-1],
          "boundOriginLocation":"OTHER","boundOriginCountry":"OTHER","regimes":[r["regime"]],
          "promisedSegments":segs,"actualSegments":segs,"originalSegments":segs,
          "promisedWindowStart":f"{r['date']}T00:00:00.000Z",
          "authenticationContactDetails":{"passengers":[{"passengerId":f"{pid}-PT-1",
            "contacts":{"apn":{"email":EMAIL,"phone":PHONE},"ctc":{"email":"","phone":""},"ape":{"email":"","phone":""}}}]}}]
        cur.execute("""INSERT INTO eds_pnr_output (id,pnr_id,booking_context,bounds,changes,last_modified,received_at)
                       VALUES (%s,%s,%s,%s,%s,now(),now())""",
                    (str(uuid.uuid4()),pid,BC,json.dumps(bounds),"[]"))
        done+=1
    cn.commit(); cn.close(); print(f"[edsinject] injected {done}")

def verify(sl):
    ctx=ssl.create_default_context(); ctx.check_hostname=False; ctx.verify_mode=ssl.CERT_NONE
    if C.gateway_down():                       # env-wide rule-engine 403 lockout -> can't verify live
        print(C.skip_area("SOC/comp DDS verify",len(sl)))
        print(f"[verify] SKIP/{len(sl)} (gateway unreachable — retry when restored; seeded data unaffected)")
        return
    ok=0; bad=[]
    for r in sl:
        try:
            req=urllib.request.Request(CRT["endpoint"]+r["pnr_id"],headers={"x-api-key":CRT["api_key"]})
            d=json.load(urllib.request.urlopen(req,timeout=25,context=ctx))
            soc=d["socFlightEligibility"][0]; pe=soc["passengerEligibility"][0]
            comp=d["compensationEligibility"][0]["passengerEligibility"][0]
            errs=[]
            if pe["systemCode"]!=r["legs"][0]["soc_code"]: errs.append(f"soc {pe['systemCode']}")
            if soc["regime"]!=r["regime"]: errs.append(f"regime {soc['regime']}")
            if comp["systemCode"]!=r["syscode"]: errs.append(f"comp {comp['systemCode']}")
            if errs: bad.append((r["tc"],errs))
            else: ok+=1
        except Exception as e: bad.append((r["tc"],str(e)[:60]))
    for b in bad: print("  BAD",b)
    print(f"[verify] {ok}/{len(sl)}")

if __name__=="__main__":
    ap=argparse.ArgumentParser(); ap.add_argument("phase")
    ap.add_argument("--start",type=int,default=0); ap.add_argument("--end",type=int,default=999)
    ap.add_argument("--tag",default="",choices=list(SET_TAGS))
    a=ap.parse_args()
    set_tag(a.tag)
    if a.phase=="gen": gen(); sys.exit()
    sl=load()[a.start:a.end]
    dict(publish=publish,checkcascade=checkcascade,finalize=finalize,edsinject=edsinject,verify=verify)[a.phase](sl)
