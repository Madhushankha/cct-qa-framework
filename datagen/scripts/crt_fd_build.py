#!/usr/bin/env python3
import os
"""Build FD ("Ask AC") test PNRs in the CRT environment by cloning validated INT
scenarios. CRT uses the INT/BAT-style rule-engine DDS path (S3 + execution_traces +
/rule-engine/dds/output endpoint), reachable via direct psycopg2/boto3 — the
rule-engine Aurora cluster endpoint accepts adminuser/adminpassword (db=postgres),
and execution_traces lives there (NOT in trip-tracer; dds_pnr_output is a 54k-row decoy).

Discovered CRT specifics (2026-06-30, account 050752605169, profile ac-cct-crt):
  PNR topic        emh-dev.ALTEA-PNRDATA-UAT  (CRT == "UAT" suffix; SIT==CRT)
  trip-tracer      ac-cct-trip-tracer-rds-cluster-crt-cac1.cluster-cxqe2wacy866...  (dbadmin direct)
  rule-engine RDS  ac-cct-rule-engine-crt-cac1-rds-cluster.cluster-cxqe2wacy866...  (adminuser/adminpassword, db=postgres)
  S3 bucket        cct-ask-ac-crt-logs   key=traces/DDS/<date>/<uuid>/response.json
  endpoint         https://rule-engine-platform-service-be.ac-cct-crt.cloud.aircanada.com/rule-engine/dds/output/
  api key          $DDS_API_KEY  (same as INT/BAT)
  NOTE: existing pins use processed_at=2027-12-31 -> our pins use 2028 to win ORDER BY DESC.

Phases (idempotent / resumable, driven off a per-set index JSON):
  index   build the <set> index (fresh locators + fresh ticket numbers) -> _FD_<set>_crt_index.json
  clone   write cloned scenario + DDS to WORK dir
  publish render + publish booking to CRT PNR Kafka
  checkcascade  how many landed in trip-tracer
  finalize ticket insert + DOB + GROUP flag + S3 put + execution_traces pin
  verify  GET the dds/output endpoint, assert ELIGIBLE + amount>0
Usage: crt_fd_build.py <set> <phase> [--start N] [--end N]
  <set> = elig91 | sit44
"""
import json, os, sys, uuid, subprocess, time, random, datetime, ssl, urllib.request, argparse
import boto3, psycopg2
import crt_uniqnames as U

# OPT-IN unique passenger names: unset -> existing behavior byte-for-byte unchanged.
UNIQ = os.environ.get("CRT_UNIQ_NAMES") == "1"

KB   = os.environ.get("CCTQA_DATAGEN_ROOT",
                      os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
FD   = f"{KB}/scenarios/fd-sit"
DDS  = f"{FD}/_dds-templates"
SENG = f"{KB}/scripts/scenario_engine.py"
PUB  = f"{KB}/scripts/publish_raw.py"
WORK = "/tmp/cctqa-datagen/crt_work"
SCENW= f"{WORK}/scenarios"; DDSW=f"{WORK}/dds"; NDJW=f"{WORK}/ndjson"
for d in (SCENW, DDSW, NDJW): os.makedirs(d, exist_ok=True)

CRT = dict(
  profile="ac-cct-crt", region="ca-central-1",
  brokers=("b-1.accctmskcrtcac1.05hf7o.c4.kafka.ca-central-1.amazonaws.com:9092,"
           "b-2.accctmskcrtcac1.05hf7o.c4.kafka.ca-central-1.amazonaws.com:9092,"
           "b-3.accctmskcrtcac1.05hf7o.c4.kafka.ca-central-1.amazonaws.com:9092"),
  topic="emh-dev.ALTEA-PNRDATA-UAT",
  tt_host="ac-cct-trip-tracer-rds-cluster-crt-cac1.cluster-cxqe2wacy866.ca-central-1.rds.amazonaws.com",
  tt_db="trip-tracer",
  tt_secret="/crt-cac1/ac-cct-trip-tracer-rds-cluster-crt-cac1/db-credentials",
  re_host="ac-cct-rule-engine-crt-cac1-rds-cluster.cluster-cxqe2wacy866.ca-central-1.rds.amazonaws.com",
  re_db="postgres",
  re_secret="/crtca1/ac-cct-rule-engine-crt-cac1-cluster/db-credentials",
  s3_bucket="cct-ask-ac-crt-logs",
  endpoint="https://rule-engine-platform-service-be.ac-cct-crt.cloud.aircanada.com/rule-engine/dds/output/",
  api_key=os.environ.get("DDS_API_KEY", ""),
)
EMAIL=os.environ.get("CRT_EMAIL","lahiru.premathilake@aircanada.ca")
PHONE=os.environ.get("CRT_PHONE","+94712534323")
DOB="1986-04-23"
PIN_TS="2028-06-30 00:00:00+00"   # beats existing 2027-12-31 pins on ORDER BY processed_at DESC

_sess=boto3.Session(profile_name=CRT["profile"], region_name=CRT["region"])
_seccache={}
def secret(sid):
    if sid not in _seccache:
        _seccache[sid]=json.loads(_sess.client("secretsmanager").get_secret_value(SecretId=sid)["SecretString"])
    return _seccache[sid]
def tt_conn():
    # Credentials from Secrets Manager, not inline. The secret carries BOTH username/password and
    # adminuser/adminpassword and which one authenticates differs per database, so try each.
    s=secret(CRT["tt_secret"])
    err=None
    for u,pw in ((s.get("username"),s.get("password")),(s.get("adminuser"),s.get("adminpassword"))):
        if not u or not pw: continue
        try:
            return psycopg2.connect(host=CRT["tt_host"],port=5432,dbname=CRT["tt_db"],
                                    user=u,password=pw,sslmode="require",connect_timeout=20)
        except psycopg2.OperationalError as e:
            if "password authentication failed" not in str(e): raise
            err=e
    raise err or RuntimeError("no usable credential pair for trip-tracer")
def re_conn():
    s=secret(CRT["re_secret"])
    return psycopg2.connect(host=CRT["re_host"],port=5432,dbname=CRT["re_db"],
                            user=s["adminuser"],password=s["adminpassword"],sslmode="require",connect_timeout=20)

# ---- set definitions --------------------------------------------------------
SETS={
 "elig91": dict(idx=f"{FD}/_FD_ELIG91_lahiru_v3_index.json", out=f"{FD}/_FD_ELIG91_crt_index.json",
                key="tc", tprefix="014292", tag="elig91", seed=920092),
 "sit44":  dict(idx=f"{FD}/_FD_SIT44_lahiru_index.json",     out=f"{FD}/_FD_SIT44_crt_index.json",
                key="sit", tprefix="014293", tag="sit44",  seed=930093),
 # 2nd 91-case ELIG set, distinct contact (marizza->mailinator) + fresh ticket series 014294 + fresh locators
 "elig91m": dict(idx=f"{FD}/_FD_ELIG91_lahiru_v3_index.json", out=f"{FD}/_FD_ELIG91_crt_marizza_index.json",
                key="tc", tprefix="014294", tag="elig91m", seed=940094),
 # 3rd 91-case ELIG set, reuses set-2 mailinator contact + fresh ticket series 014295 + fresh locators
 "elig91c": dict(idx=f"{FD}/_FD_ELIG91_lahiru_v3_index.json", out=f"{FD}/_FD_ELIG91_crt_set3_index.json",
                key="tc", tprefix="014295", tag="elig91c", seed=950095),
 # 4th 91-case ELIG set, reuses mailinator lahiru contact + fresh ticket series 014296 + fresh locators
 "elig91d": dict(idx=f"{FD}/_FD_ELIG91_lahiru_v3_index.json", out=f"{FD}/_FD_ELIG91_crt_set4_index.json",
                key="tc", tprefix="014296", tag="elig91d", seed=960096),
}
# any already-built CRT index whose locators must NOT be reused (avoid clobbering existing PNRs)
CRT_BUILT_INDEXES=[f"{FD}/_FD_ELIG91_crt_index.json", f"{FD}/_FD_SIT44_crt_index.json",
                   f"{FD}/_FD_ELIG91_crt_marizza_index.json", f"{FD}/_FD_ELIG91_crt_set3_index.json",
                   f"{FD}/_FD_ELIG91_crt_set4_index.json"]
# Per-build overrides. HOWTO §6 requires a FREE ticket prefix for every build — reusing a consumed
# one does not error, the insert is ON CONFLICT DO NOTHING, so the ticket is silently dropped and only
# the `ticket` checkpoint catches it later. The prefix/seed/output baked into SETS above belong to the
# build that first used them, so a rebuild must override rather than edit the table.
#   CRT_TPREFIX  free 6-digit ticket prefix (scan first)
#   CRT_SEED     locator RNG seed — a new value mints new locators
#   CRT_OUT      index output path, so an earlier set's index is not clobbered
for _k in SETS:
    if os.environ.get("CRT_TPREFIX"): SETS[_k]["tprefix"] = os.environ["CRT_TPREFIX"]
    if os.environ.get("CRT_SEED"):    SETS[_k]["seed"]    = int(os.environ["CRT_SEED"])
    if os.environ.get("CRT_OUT"):     SETS[_k]["out"]     = os.environ["CRT_OUT"]

GROUP_SRC_TC="FD_TC_012"            # -> eds_pnr_output.booking_context bookingSubtype=GROUP
TC063_SHELL="BPKPMR-2026-06-15"     # FD_TC_001 (APPR EL-400) shell; TC063 forced ELIGIBLE
TC063_PAX=("SYLVIE","COTE")

def gen_locators(n, seed, taken):
    rng=random.Random(seed); A="ABCDEFGHIJKLMNOPQRSTUVWXYZ"; out=[]
    while len(out)<n:
        loc="".join(rng.choice(A) for _ in range(6))
        if loc in taken: continue
        taken.add(loc); out.append(loc)
    return out

def build_index(setname):
    cfg=SETS[setname]; src=json.load(open(cfg["idx"])); key=cfg["key"]
    taken=set()  # avoid colliding with source locators of either set + any already-built CRT set
    for f in (SETS["elig91"]["idx"], SETS["sit44"]["idx"], *CRT_BUILT_INDEXES):
        if not os.path.exists(f) or os.path.abspath(f)==os.path.abspath(cfg["out"]): continue
        for e in json.load(open(f)): taken.add(e["pnr_id"][:6])
    locs=gen_locators(len(src), cfg["seed"], taken)
    recs=[]
    for i,e in enumerate(src):
        srctc = e.get("tc") or e.get("src")
        sit   = e.get("sit")
        loc   = locs[i]
        date  = e["pnr_id"][7:]
        is063 = (srctc=="FD_TC_063")
        if is063:
            date="2026-06-15"; src_scn=TC063_SHELL; src_dds=TC063_SHELL
            status,syscode,amount,currency="ELIGIBLE","FD-APPR-EL-400",400,"CAD"
        else:
            src_scn=e["pnr_id"]; src_dds=e["pnr_id"]
            status,syscode,amount,currency=e["status"],e["syscode"],e["amount"],e["currency"]
        new_pid=f"{loc}-{date}"
        recs.append(dict(
            key=e.get(key), tc=srctc, sit=sit,
            src_scn=src_scn, src_dds=src_dds,
            loc=loc, pnr_id=new_pid, date=date,
            ticket=f"{cfg['tprefix']}{i+1:06d}", pax=e["pax"], route=e.get("route",""),
            status=status, syscode=syscode, amount=amount, currency=currency,
            title=e.get("title",""), email=EMAIL, phone=PHONE,
            group=(srctc==GROUP_SRC_TC), forced=is063, pin=True))
    if UNIQ:
        def _npax(r):
            try: return len(json.load(open(f"{FD}/{r['src_scn']}.json")).get("passengers",[])) or 1
            except Exception: return 1
        c=tt_conn(); U.assign_names(recs, _npax, c, seed=cfg["seed"]); c.close()
    json.dump(recs, open(cfg["out"],"w"), indent=1)
    print(f"[index] {setname}: {len(recs)} records -> {cfg['out']}")
    return recs

def load_index(setname): return json.load(open(SETS[setname]["out"]))

def clone_one(r, tag):
    scn=json.load(open(f"{FD}/{r['src_scn']}.json"))
    scn["scenario_id"]=r["pnr_id"]; scn["identity"]["pnr"]=r["loc"]
    scn["identity"]["booking_date"]=r["date"]
    scn["ticketing"]["ticket_numbers"]=[r["ticket"]]
    scn["creation_comment"]=scn["last_modification_comment"]=f"SIM-{r['tc']}-{tag}-CRT"
    scn["title"]=f"{r['tc']}{('/'+r['sit']) if r['sit'] else ''}: {r.get('title') or r['status']} [{r['loc']}]"
    for p in scn["passengers"]:
        p["email"]=EMAIL; p["phone"]=PHONE; p["date_of_birth"]=DOB
    if r["forced"]:
        scn["passengers"][0]["first_name"],scn["passengers"][0]["last_name"]=TC063_PAX
        scn["passengers"][0]["type"]="ADT"
    U.apply_to_scenario(scn, r)  # unique names win over canonical/forced (no-op if r has no pax_names)
    json.dump(scn, open(f"{SCENW}/{r['pnr_id']}.json","w"), indent=1)
    src_pid=f"{r['src_dds']}"; src_loc=src_pid[:6]
    s=open(f"{DDS}/{src_pid}.dds.json").read()
    s=s.replace(src_pid, r["pnr_id"]).replace(f'"pnr": "{src_loc}"', f'"pnr": "{r["loc"]}"')
    open(f"{DDSW}/{r['pnr_id']}.dds.json","w").write(s)
    assert src_loc not in open(f"{DDSW}/{r['pnr_id']}.dds.json").read(), f"stray {src_loc} in {r['pnr_id']}"

def render_publish_one(r):
    nd=f"{NDJW}/{r['loc']}.ndjson"
    subprocess.run(["python3",SENG,"render","--scenario",f"{SCENW}/{r['pnr_id']}.json","--out",nd],
                   check=True, capture_output=True)
    out=subprocess.run(["python3",PUB,"--ndjson",nd,"--brokers",CRT["brokers"],
                        "--topic",CRT["topic"],"--live"], capture_output=True, text=True)
    ok="produced" in (out.stdout+out.stderr)
    return ok, (out.stdout+out.stderr)

def cascaded(conn, pids):
    cur=conn.cursor()
    cur.execute("select pnr_id from trip where pnr_id = any(%s)", (pids,))
    return {x[0] for x in cur.fetchall()}

def finalize_one(r, ttc, rec):
    cur=ttc.cursor()
    iss="2026-06-01"
    pid=r["pnr_id"]; tk=r["ticket"]
    # ONE TICKET PER PASSENGER. PT-1 keeps the index ticket ({prefix}{case:06d}); PT-2..PT-n get
    # {prefix}{case:04d}{pax:02d} — a band above 000239 so it cannot collide with the base series.
    # (Previously only PT-1 got a ticket, silently leaving multi-pax/GROUP passengers ticketless.)
    _pfx, _case = tk[:6], int(tk[6:])
    cur.execute("select passenger_id from passenger where pnr_id=%s and not is_removed",(pid,))
    _pts=sorted(int(p[0].rsplit("-PT-",1)[1]) for p in cur.fetchall()) or [1]
    for _k in _pts:
        _t = tk if _k==1 else f"{_pfx}{_case:04d}{_k:02d}"
        cur.execute("""insert into ticket
            (primary_document_number,pnr_id,passenger_id,ticket_id,document_numbers,issuance_local_date,document_type)
            values (%s,%s,%s,%s,ARRAY[%s],%s,'T') on conflict do nothing""",
            (_t,pid,f"{pid}-PT-{_k}",f"{_t}-{iss}",_t,iss))
    cur.execute("update passenger set date_of_birth=%s where pnr_id=%s",(DOB,pid))
    if r["group"]:
        cur.execute("select id, booking_context from eds_pnr_output where pnr_id=%s",(pid,))
        for row in cur.fetchall():
            bc=row[1] or {}
            if isinstance(bc,str): bc=json.loads(bc)
            bc["bookingSubtype"]="GROUP"
            cur.execute("update eds_pnr_output set booking_context=%s where id=%s",(json.dumps(bc),row[0]))
    ttc.commit()
    key=f"traces/DDS/{r['date']}/{uuid.uuid4()}/response.json"
    body=open(f"{DDSW}/{pid}.dds.json","rb").read()
    _sess.client("s3").put_object(Bucket=CRT["s3_bucket"],Key=key,Body=body,ContentType="application/json")
    rec["s3_key"]=key
    return key

def pin_all(recs, keys):
    conn=re_conn(); cur=conn.cursor()
    ents=[r["pnr_id"] for r in recs]
    cur.execute("delete from execution_traces where service_type='DDS' and entity_id = any(%s) and correlation_id like 'qa-pin-crt-%%'",(ents,))
    rows=[(r["pnr_id"], f"qa-pin-crt-{r['loc']}", keys[r["pnr_id"]]) for r in recs]
    cur.executemany("""insert into execution_traces
        (id,service_type,correlation_id,entity_id,processed_at,request_s3_key,response_s3_key)
        values (gen_random_uuid(),'DDS',%s,%s,%s,NULL,%s)""",
        [(cor,ent,PIN_TS,key) for (ent,cor,key) in rows])
    conn.commit(); conn.close()
    return len(rows)

_ctx=ssl.create_default_context(); _ctx.check_hostname=False; _ctx.verify_mode=ssl.CERT_NONE
def verify_one(pid):
    req=urllib.request.Request(CRT["endpoint"]+pid, headers={"x-api-key":CRT["api_key"]})
    try:
        with urllib.request.urlopen(req, context=_ctx, timeout=25) as resp:
            body=json.load(resp)
    except urllib.error.HTTPError as e:
        return dict(pnr_id=pid, ok=False, http=e.code, detail=e.read()[:120].decode("utf-8","ignore"))
    except Exception as e:
        return dict(pnr_id=pid, ok=False, http=None, detail=str(e)[:120])
    best=None
    for ce in body.get("compensationEligibility",[]):
        for pe in ce.get("passengerEligibility",[]):
            if pe.get("eligibilityStatus")=="ELIGIBLE":
                amt=(pe.get("compensationDetails") or {}).get("amount",0) or 0
                cur=(pe.get("compensationDetails") or {}).get("currency","")
                sc=pe.get("systemCode","")
                if best is None or amt>best[0]: best=(amt,cur,sc,ce.get("regime"))
    if best and best[0]>0:
        return dict(pnr_id=pid, ok=True, http=200, amount=best[0], currency=best[1], syscode=best[2], regime=best[3])
    return dict(pnr_id=pid, ok=False, http=200, detail="no ELIGIBLE>0 in compensationEligibility")

# ---- phase runners ----------------------------------------------------------
def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("setname",choices=list(SETS)); ap.add_argument("phase")
    ap.add_argument("--start",type=int,default=0); ap.add_argument("--end",type=int,default=10**9)
    a=ap.parse_args(); cfg=SETS[a.setname]
    if a.phase=="index": build_index(a.setname); return
    recs=load_index(a.setname); sl=recs[a.start:a.end]
    if a.phase=="clone":
        for r in sl: clone_one(r, cfg["tag"])
        print(f"[clone] {len(sl)} scenarios+DDS written")
    elif a.phase=="publish":
        ok=0
        for i,r in enumerate(sl):
            good,log=render_publish_one(r)
            ok+=good; print(f"  [{a.start+i}] {r['pnr_id']} {'OK' if good else 'FAIL '+log[-160:]}",flush=True)
        print(f"[publish] {ok}/{len(sl)} produced")
    elif a.phase=="checkcascade":
        ttc=tt_conn(); have=cascaded(ttc, [r["pnr_id"] for r in sl]); ttc.close()
        miss=[r["pnr_id"] for r in sl if r["pnr_id"] not in have]
        print(f"[cascade] {len(have)}/{len(sl)} present; missing={miss}")
    elif a.phase=="finalize":
        ttc=tt_conn(); keys={}
        for i,r in enumerate(sl):
            try:
                keys[r["pnr_id"]]=finalize_one(r,ttc,r); print(f"  [{a.start+i}] {r['pnr_id']} finalized",flush=True)
            except Exception as e:
                print(f"  [{a.start+i}] {r['pnr_id']} ERR {e}",flush=True)
        ttc.close()
        n=pin_all([r for r in sl if r["pnr_id"] in keys], keys)
        # persist s3_key back into index
        full=load_index(a.setname)
        bypid={r["pnr_id"]:r for r in sl}
        for r in full:
            if r["pnr_id"] in bypid and bypid[r["pnr_id"]].get("s3_key"):
                r["s3_key"]=bypid[r["pnr_id"]]["s3_key"]
        json.dump(full, open(cfg["out"],"w"), indent=1)
        print(f"[finalize] tickets/DOB/S3 done; pinned {n} DDS rows")
    elif a.phase=="verify":
        res=[verify_one(r["pnr_id"]) for r in sl]
        elig=sum(1 for x in res if x["ok"])
        for x in res:
            if not x["ok"]: print("  FAIL",x)
        print(f"[verify] {elig}/{len(sl)} ELIGIBLE")
        json.dump(res, open(f"{WORK}/{a.setname}_verify.json","w"), indent=1)
    else:
        print("unknown phase"); sys.exit(2)

if __name__=="__main__": main()
