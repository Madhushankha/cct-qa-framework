#!/usr/bin/env python3
"""Fresh AC-Wallet FD test PNRs in INT — 2 sets x 3 scenarios (set4, set5).
Same recipe as the set2/set3 build (session c80fdb09): clone donor BCNRDY-2026-06-15
(ELIGIBLE FD-APPR-EL-400), inject Aeroplan FQTV loyaltyRequests for wallet rows,
publish to INT PNR Kafka, wait cascade, insert tickets+DOB, S3 DDS + pin
execution_traces (Fargate psql), inject eds_pnr_output from sagarika FD_TC_001 donor,
verify DDS endpoint per PNR."""
import sys, os, json, glob, subprocess, ssl, urllib.request, time, re, random
sys.path.insert(0,f"{KB}/scripts")
import int_fd_build as bf
import crt_uniqnames as U

# OPT-IN unique passenger names: unset -> existing behavior byte-for-byte unchanged.
UNIQ = os.environ.get("CRT_UNIQ_NAMES") == "1"
FD=bf.FD; DDS=bf.DDS
WORK="/tmp/cctqa-datagen/wallet_work"
SCENW=f"{WORK}/scenarios"; DDSW=f"{WORK}/dds"; NDJW=f"{WORK}/ndjson"
for d in (SCENW,DDSW,NDJW): os.makedirs(d,exist_ok=True)
EMAIL="lahiru@ae-qa1-aircanada.mailinator.com"; PHONE="+94712534323"; DOB=bf.DOB
SRC="BCNRDY-2026-06-15"; SRCLOC="BCNRDY"; DATE="2026-06-15"
EXTRA=[("MARIE","GAGNON"),("LUC","BERGERON")]
sag={m['tc']:m['pnr_id'] for m in json.load(open(f"{FD}/_FD_ALL200_sagarika_index.json"))}
DONOR=sag["FD_TC_001"]
CONF=[("Single passenger + AC Wallet",1,True),
      ("Multiple passengers + AC Wallet",3,True),
      ("Multiple passengers - No AC Wallet",3,False)]
SETS=[("set4","014341","9158"),("set5","014342","9159")]
# avoid every locator already used by any FD index
taken=set()
for f in glob.glob(f"{FD}/_FD_*index.json"):
    try:
        for e in json.load(open(f)):
            pid=e.get("pnr_id") or ""
            if pid: taken.add(pid[:6])
    except Exception: pass
random.seed(915841); cons="BCDFGHJKLMNPQRSTVWXYZ"
def mint():
    while True:
        c="".join(random.choice(cons) for _ in range(6))
        if c not in taken and not c.startswith("ZZ"): taken.add(c); return c
# OPT-IN unique names: pre-assign one DB-absent name per pax, in the same (set x CONF) order the
# build loop consumes them. Requires the trip-tracer conn the script already uses (only when UNIQ).
_pn_iter=None
if UNIQ:
    _planned=[dict(npax=npax) for _t in SETS for (_l,npax,_w) in CONF]
    _c=bf.tt_conn(); U.assign_names(_planned, lambda r:r["npax"], _c, seed=760076); _c.close()
    _pn_iter=iter(_planned)
allrecs=[]
for tag,tpx,loybase in SETS:
    recs=[]
    for i,(label,npax,wallet) in enumerate(CONF,1):
        loc=mint(); pid=f"{loc}-{DATE}"; tickets=[f"{tpx}{i:04d}{p:02d}" for p in range(1,npax+1)]
        scn=json.load(open(f"{FD}/{SRC}.json")); scn["scenario_id"]=pid; scn["identity"]["pnr"]=loc
        scn["identity"]["booking_date"]=DATE; scn["ticketing"]["ticket_numbers"]=tickets
        scn["title"]=f"WALLET-{tag}-{i}: {label} [{loc}]"; scn["creation_comment"]=scn["last_modification_comment"]=f"SIM-WALLET-{tag}-{i}-INT"
        if npax>1:
            for (fn,ln) in EXTRA[:npax-1]:
                scn["passengers"].append(dict(type="ADT",first_name=fn,last_name=ln,gender="U",date_of_birth=DOB,email=EMAIL,phone=PHONE))
        for p in scn["passengers"]: p["email"]=EMAIL; p["phone"]=PHONE; p["date_of_birth"]=DOB
        _rp=None
        if UNIQ:
            _rp=next(_pn_iter)["pax_names"]
            for j,p in enumerate(scn["passengers"]):
                if j<len(_rp): p["first_name"],p["last_name"]=_rp[j]
        memberships=[]
        if wallet:
            loy=[]
            for n in range(1,npax+1):
                num=f"{loybase}{i}{n:04d}"; memberships.append(num)
                loy.append({"type":"loyaltyRequest","id":f"{pid}-OT-30{n}","code":"FQTV","serviceProvider":{"code":"AC"},
                    "membership":{"number":num,"membershipType":"INDIVIDUAL"},"status":"HK",
                    "traveler":{"type":"stakeholder","id":f"{pid}-PT-{n}","ref":"processedPnr.travelers"}})
            tl=scn.get("timeline") or []
            ev=next((t for t in tl if t.get("version")==1), tl[-1] if tl else None)
            if ev is not None: ev.setdefault("overrides",{})["/loyaltyRequests"]=loy
        json.dump(scn,open(f"{SCENW}/{pid}.json","w"),indent=1)
        d=json.loads(open(f"{DDS}/{SRC}.dds.json").read().replace(SRC,pid).replace(f'"pnr": "{SRCLOC}"',f'"pnr": "{loc}"'))
        def multi(c):
            pe0=c["passengerEligibility"][0]; out=[]
            for n in range(1,npax+1):
                x=json.loads(json.dumps(pe0)); x["passengerId"]=f"{pid}-PT-{n}"; out.append(x)
            c["passengerEligibility"]=out
        if npax>1:
            for ce in d.get("compensationEligibility",[]): multi(ce)
            for soc in d.get("socFlightEligibility",[]): multi(soc)
        open(f"{DDSW}/{pid}.dds.json","w").write(json.dumps(d,indent=1))
        recs.append(dict(set=tag,label=label,loc=loc,pnr_id=pid,tickets=tickets,npax=npax,wallet=wallet,
            memberships=memberships,donor=DONOR,email=EMAIL,phone=PHONE,status="ELIGIBLE",syscode="FD-APPR-EL-400",
            amount=400,currency="CAD",pin=True,pax=" / ".join(f"{p['first_name']} {p['last_name']}" for p in scn["passengers"])))
        if UNIQ: recs[-1]["pax_names"]=_rp; recs[-1]["uniq_names"]=True
        print(f"[{tag}-{i}] {loc} {label}: {npax}pax wallet={wallet} memberships={memberships}",flush=True)
    json.dump(recs,open(f"{FD}/_FD_WALLET3_lahiru_{tag}_index.json","w"),indent=1); allrecs+=recs
json.dump(allrecs,open(f"{FD}/_FD_WALLET6_lahiru_set45_index.json","w"),indent=1)

# ---- publish (verify loyalty renders into the ndjson) ----
for r in allrecs:
    nd=f"{NDJW}/{r['loc']}.ndjson"
    subprocess.run(["python3",bf.SENG,"render","--scenario",f"{SCENW}/{r['pnr_id']}.json","--out",nd],check=True,capture_output=True)
    body=open(nd).read(); has=all(m in body for m in r["memberships"]) if r["wallet"] else ("loyaltyRequest" not in body)
    o=subprocess.run(["python3",bf.PUB,"--ndjson",nd,"--brokers",bf.BAT["brokers"],"--topic",bf.BAT["topic"],"--live"],capture_output=True,text=True)
    print(f"  publish {r['loc']}: {'OK' if 'produced' in (o.stdout+o.stderr) else 'FAIL '+(o.stdout+o.stderr)[-120:]} | loyalty-render {'OK' if has else 'MISMATCH'}",flush=True)

# ---- wait cascade ----
ttc=bf.tt_conn(); ids=[r["pnr_id"] for r in allrecs]
for _ in range(30):
    if len(bf.cascaded(ttc,ids))==len(ids): break
    time.sleep(10)
print("cascaded:",len(bf.cascaded(ttc,ids)),"/",len(ids),flush=True)

# ---- finalize: tickets + DOB + S3 DDS ----
cur=ttc.cursor(); keys={}
for r in allrecs:
    for n,tk in enumerate(r["tickets"],1):
        cur.execute("""insert into ticket (primary_document_number,pnr_id,passenger_id,ticket_id,document_numbers,issuance_local_date,document_type) values (%s,%s,%s,%s,ARRAY[%s],%s,'T') on conflict do nothing""",
            (tk,r["pnr_id"],f"{r['pnr_id']}-PT-{n}",f"{tk}-2026-06-01",tk,"2026-06-01"))
    cur.execute("update passenger set date_of_birth=%s where pnr_id=%s",(DOB,r["pnr_id"]))
    key=f"traces/DDS/{DATE}/{r['pnr_id']}/response.json"
    bf._sess.client("s3").put_object(Bucket=bf.BAT["s3_bucket"],Key=key,Body=open(f"{DDSW}/{r['pnr_id']}.dds.json","rb").read(),ContentType="application/json"); keys[r["pnr_id"]]=key
ttc.commit(); print("tickets/DOB/S3 done",flush=True)

# ---- pin execution_traces (Fargate psql) ----
bf.pin_all(allrecs,keys)

# ---- eds_pnr_output injection from donor ----
cur2=ttc.cursor()
for r in allrecs:
    dpid=r["donor"]; dloc=dpid[:6]
    cur2.execute("select bounds::text,booking_context::text,changes::text from eds_pnr_output where pnr_id=%s order by received_at desc limit 1",(dpid,))
    row=cur2.fetchone()
    if not row: print(f"  EDS DONOR MISSING for {r['pnr_id']}",flush=True); continue
    b,bc,ch=row
    def sub(x): return None if x is None else re.sub(r"[\w.\-]+@aircanada\.ca",EMAIL,x.replace(dpid,r["pnr_id"]).replace(dloc,r["loc"]))
    nb=json.loads(sub(b))
    for bd in nb:
        ac=bd.get("authenticationContactDetails",{})
        if ac.get("passengers"):
            base=ac["passengers"][0]["contacts"]
            ac["passengers"]=[{"passengerId":f"{r['pnr_id']}-PT-{n}","contacts":json.loads(json.dumps(base))} for n in range(1,r["npax"]+1)]
    cur2.execute("delete from eds_pnr_output where pnr_id=%s",(r["pnr_id"],))
    cur2.execute("insert into eds_pnr_output (id,last_modified,received_at,changes,bounds,pnr_id,booking_context) values (gen_random_uuid(),now(),now(),%s::jsonb,%s::jsonb,%s,%s::jsonb)",
        (sub(ch),json.dumps(nb),r["pnr_id"],sub(bc)))
ttc.commit(); print("eds injected",flush=True)

# ---- verify ----
ctx=ssl.create_default_context();ctx.check_hostname=False;ctx.verify_mode=ssl.CERT_NONE
for r in allrecs:
    d=json.load(urllib.request.urlopen(urllib.request.Request(bf.BAT["endpoint"]+r["pnr_id"],headers={"x-api-key":bf.BAT["api_key"]}),context=ctx,timeout=25))
    pe=d["compensationEligibility"][0]["passengerEligibility"]; amt=(pe[0].get("compensationDetails") or {}).get("amount")
    cur.execute("select count(*) from passenger where pnr_id=%s and not is_removed",(r["pnr_id"],)); tp=cur.fetchone()[0]
    print(f"VERIFY [{r['set']}] {r['label']}: {r['loc']} {pe[0]['eligibilityStatus']} ${amt} DDS-pax={len(pe)} trip-pax={tp} wallet={r['wallet']} mem={r['memberships']}",flush=True)
ttc.close(); print("WALLET SET4+SET5 DONE")
