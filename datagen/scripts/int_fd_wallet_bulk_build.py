#!/usr/bin/env python3
"""Bulk AC-Wallet FD test PNRs in INT — 10 trios (30 PNRs), set tag bulk30.
Same recipe as int_fd_wallet_build.py (donor BCNRDY ELIGIBLE FD-APPR-EL-400,
FQTV loyalty inject, publish, cascade, tickets/DOB/S3, Fargate pin, eds inject,
verify). Render/publish + verify parallelized with a thread pool."""
import sys, os, json, glob, subprocess, ssl, urllib.request, time, re, random
from concurrent.futures import ThreadPoolExecutor
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
TPX="014343"; LOYBASE="9160"; NTRIOS=10
taken=set()
for f in glob.glob(f"{FD}/_FD_*index.json"):
    try:
        for e in json.load(open(f)):
            pid=e.get("pnr_id") or ""
            if pid: taken.add(pid[:6])
    except Exception: pass
random.seed(916043); cons="BCDFGHJKLMNPQRSTVWXYZ"
def mint():
    while True:
        c="".join(random.choice(cons) for _ in range(6))
        if c not in taken and not c.startswith("ZZ"): taken.add(c); return c
# OPT-IN unique names: pre-assign one DB-absent name per pax, in the same (trio x CONF) order the
# build loop consumes them. Requires the trip-tracer conn the script already uses (only when UNIQ).
_pn_iter=None
if UNIQ:
    _planned=[dict(npax=npax) for _t in range(NTRIOS) for (_l,npax,_w) in CONF]
    _c=bf.tt_conn(); U.assign_names(_planned, lambda r:r["npax"], _c, seed=770077); _c.close()
    _pn_iter=iter(_planned)
allrecs=[]; k=0
for t in range(1,NTRIOS+1):
    for (label,npax,wallet) in CONF:
        k+=1; loc=mint(); pid=f"{loc}-{DATE}"
        tickets=[f"{TPX}{k:04d}{p:02d}" for p in range(1,npax+1)]
        scn=json.load(open(f"{FD}/{SRC}.json")); scn["scenario_id"]=pid; scn["identity"]["pnr"]=loc
        scn["identity"]["booking_date"]=DATE; scn["ticketing"]["ticket_numbers"]=tickets
        scn["title"]=f"WALLET-bulk30-{t}.{label} [{loc}]"; scn["creation_comment"]=scn["last_modification_comment"]=f"SIM-WALLET-bulk30-{k}-INT"
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
                num=f"{LOYBASE}{k:02d}{n:03d}"; memberships.append(num)
                loy.append({"type":"loyaltyRequest","id":f"{pid}-OT-30{n}","code":"FQTV","serviceProvider":{"code":"AC"},
                    "membership":{"number":num,"membershipType":"INDIVIDUAL"},"status":"HK",
                    "traveler":{"type":"stakeholder","id":f"{pid}-PT-{n}","ref":"processedPnr.travelers"}})
            tl=scn.get("timeline") or []
            ev=next((tt for tt in tl if tt.get("version")==1), tl[-1] if tl else None)
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
        allrecs.append(dict(set="bulk30",trio=t,label=label,loc=loc,pnr_id=pid,tickets=tickets,npax=npax,wallet=wallet,
            memberships=memberships,donor=DONOR,email=EMAIL,phone=PHONE,status="ELIGIBLE",syscode="FD-APPR-EL-400",
            amount=400,currency="CAD",pin=True,pax=" / ".join(f"{p['first_name']} {p['last_name']}" for p in scn["passengers"])))
        if UNIQ: allrecs[-1]["pax_names"]=_rp; allrecs[-1]["uniq_names"]=True
        print(f"[{t}.{label[:20]}] {loc} {npax}pax wallet={wallet} mem={memberships}",flush=True)
json.dump(allrecs,open(f"{FD}/_FD_WALLET30_lahiru_index.json","w"),indent=1)

# ---- render + publish (8 threads) ----
def pub(r):
    nd=f"{NDJW}/{r['loc']}.ndjson"
    subprocess.run(["python3",bf.SENG,"render","--scenario",f"{SCENW}/{r['pnr_id']}.json","--out",nd],check=True,capture_output=True)
    body=open(nd).read(); has=all(m in body for m in r["memberships"]) if r["wallet"] else ("loyaltyRequest" not in body)
    o=subprocess.run(["python3",bf.PUB,"--ndjson",nd,"--brokers",bf.BAT["brokers"],"--topic",bf.BAT["topic"],"--live"],capture_output=True,text=True)
    ok="produced" in (o.stdout+o.stderr)
    return r["loc"], ok, has, (o.stdout+o.stderr)[-120:]
with ThreadPoolExecutor(8) as ex:
    for loc,ok,has,tail in ex.map(pub, allrecs):
        print(f"  publish {loc}: {'OK' if ok else 'FAIL '+tail} | loyalty-render {'OK' if has else 'MISMATCH'}",flush=True)

# ---- wait cascade ----
ttc=bf.tt_conn(); ids=[r["pnr_id"] for r in allrecs]
for _ in range(40):
    if len(bf.cascaded(ttc,ids))==len(ids): break
    time.sleep(10)
print("cascaded:",len(bf.cascaded(ttc,ids)),"/",len(ids),flush=True)

# ---- finalize: tickets + DOB + S3 DDS (S3 puts threaded) ----
cur=ttc.cursor(); keys={}
for r in allrecs:
    for n,tk in enumerate(r["tickets"],1):
        cur.execute("""insert into ticket (primary_document_number,pnr_id,passenger_id,ticket_id,document_numbers,issuance_local_date,document_type) values (%s,%s,%s,%s,ARRAY[%s],%s,'T') on conflict do nothing""",
            (tk,r["pnr_id"],f"{r['pnr_id']}-PT-{n}",f"{tk}-2026-06-01",tk,"2026-06-01"))
    cur.execute("update passenger set date_of_birth=%s where pnr_id=%s",(DOB,r["pnr_id"]))
ttc.commit()
def s3put(r):
    key=f"traces/DDS/{DATE}/{r['pnr_id']}/response.json"
    bf._sess.client("s3").put_object(Bucket=bf.BAT["s3_bucket"],Key=key,Body=open(f"{DDSW}/{r['pnr_id']}.dds.json","rb").read(),ContentType="application/json")
    return r["pnr_id"],key
with ThreadPoolExecutor(8) as ex:
    for pid,key in ex.map(s3put, allrecs): keys[pid]=key
print("tickets/DOB/S3 done",flush=True)

# ---- pin execution_traces (single Fargate psql task) ----
bf.pin_all(allrecs,keys)

# ---- eds_pnr_output injection from donor (fetch donor once) ----
cur2=ttc.cursor()
cur2.execute("select bounds::text,booking_context::text,changes::text from eds_pnr_output where pnr_id=%s order by received_at desc limit 1",(DONOR,))
row=cur2.fetchone(); dloc=DONOR[:6]
if not row: print("EDS DONOR MISSING",flush=True)
else:
    b,bc,ch=row
    for r in allrecs:
        def sub(x): return None if x is None else re.sub(r"[\w.\-]+@aircanada\.ca",EMAIL,x.replace(DONOR,r["pnr_id"]).replace(dloc,r["loc"]))
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

# ---- verify (8 threads on HTTP; pax counts from one query) ----
cur.execute("select pnr_id,count(*) from passenger where pnr_id=any(%s) and not is_removed group by pnr_id",(ids,))
tpax={r[0]:r[1] for r in cur.fetchall()}; ttc.close()
ctx=ssl.create_default_context();ctx.check_hostname=False;ctx.verify_mode=ssl.CERT_NONE
def ver(r):
    d=json.load(urllib.request.urlopen(urllib.request.Request(bf.BAT["endpoint"]+r["pnr_id"],headers={"x-api-key":bf.BAT["api_key"]}),context=ctx,timeout=25))
    pe=d["compensationEligibility"][0]["passengerEligibility"]; amt=(pe[0].get("compensationDetails") or {}).get("amount")
    return f"VERIFY [{r['trio']}] {r['label'][:22]}: {r['loc']} {pe[0]['eligibilityStatus']} ${amt} DDS-pax={len(pe)} trip-pax={tpax.get(r['pnr_id'])} wallet={r['wallet']}"
with ThreadPoolExecutor(8) as ex:
    for line in ex.map(ver, allrecs): print(line,flush=True)
print("WALLET BULK30 DONE")
