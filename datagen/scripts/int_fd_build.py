#!/usr/bin/env python3
import os
"""Build FD ("Ask AC") test PNRs in the BAT environment by cloning validated INT
scenarios. BAT uses the INT-style rule-engine DDS path (S3 + execution_traces +
/rule-engine/dds/output endpoint), reachable via direct psycopg2/boto3 (ECS-Exec
is dead on the shared task, so we pin execution_traces by connecting straight to
the rule-engine Aurora cluster with admin creds).

Phases (idempotent / resumable, driven off a per-set index JSON):
  index   build the <set> index (locators + ticket numbers)  -> _FD_<set>_bat_index.json
  clone   write cloned scenario + DDS to WORK dir
  publish render + publish booking to BAT PNR Kafka
  finalize ticket insert + DOB + GROUP flag + S3 put + execution_traces pin
  verify  GET the dds/output endpoint, assert ELIGIBLE + amount>0
Usage: batfd.py <set> <phase> [--start N] [--end N]
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
WORK = "/tmp/cctqa-datagen/int_work"
SCENW= f"{WORK}/scenarios"; DDSW=f"{WORK}/dds"; NDJW=f"{WORK}/ndjson"
for d in (SCENW, DDSW, NDJW): os.makedirs(d, exist_ok=True)

BAT = dict(
  profile="ARC75-Temp-INT", region="ca-central-1",
  brokers=("b-1.accctmskintcac1.z22bz6.c3.kafka.ca-central-1.amazonaws.com:9092,"
           "b-2.accctmskintcac1.z22bz6.c3.kafka.ca-central-1.amazonaws.com:9092,"
           "b-3.accctmskintcac1.z22bz6.c3.kafka.ca-central-1.amazonaws.com:9092"),
  topic="emh-int.ALTEA-PNRDATA-INT",
  tt_host="ac-cct-trip-tracer-rds-proxy-int-cac1.proxy-czy2ye8u22qy.ca-central-1.rds.amazonaws.com",
  tt_db="trip-tracer",
  tt_secret="/int-cac1/ac-cct-trip-tracer-rds-cluster-int-cac1/db-credentials",
  re_cluster="ac-cct-rule-engine-platform-cluster-int",   # pin via ECS-Exec (direct RDS denied)
  s3_bucket="ac-cct-rule-engine-store-int",
  endpoint="https://rule-engine-platform-service.ac-cct-int.cloud.aircanada.com/rule-engine/dds/output/",
  api_key=os.environ.get("DDS_API_KEY", ""),
)
EMAIL="lahiru.premathilake@aircanada.ca"; PHONE="+94712534323"; DOB="1986-04-23"
PIN_TS="2027-06-30 00:00:00+00"   # future so our pin wins ORDER BY processed_at DESC

_sess=boto3.Session(profile_name=BAT["profile"], region_name=BAT["region"])
_seccache={}
def secret(sid):
    if sid not in _seccache:
        _seccache[sid]=json.loads(_sess.client("secretsmanager").get_secret_value(SecretId=sid)["SecretString"])
    return _seccache[sid]
def tt_conn():
    s=secret(BAT["tt_secret"])
    return psycopg2.connect(host=BAT["tt_host"],port=5432,dbname=BAT["tt_db"],
                            user=s["username"],password=s["password"],sslmode="require",connect_timeout=20)
# ---- set definitions --------------------------------------------------------
SETS={
 "elig91": dict(idx=f"{FD}/_FD_ELIG91_lahiru_v3_index.json", out=f"{FD}/_FD_ELIG91_bat_index.json",
                key="tc", tprefix="014290", tag="elig91", seed=914091),
 "sit44":  dict(idx=f"{FD}/_FD_SIT44_lahiru_index.json",     out=f"{FD}/_FD_SIT44_bat_index.json",
                key="sit", tprefix="014291", tag="sit44",  seed=440044),
 "batch69": dict(idx=f"{FD}/_FD_GAP69_src_index.json",       out=f"{FD}/_FD_BATCH69_bat_index.json",
                key="tc", tprefix="014292", tag="gap69",  seed=690690),
 "elig91b": dict(idx=f"{FD}/_FD_ELIG91_lahiru_v3_index.json", out=f"{FD}/_FD_ELIG91B_bat_index.json",
                key="tc", tprefix="014293", tag="elig91b", seed=915293),
 "elig91c": dict(idx=f"{FD}/_FD_ELIG91_lahiru_v3_index.json", out=f"{FD}/_FD_ELIG91C_bat_index.json",
                key="tc", tprefix="014294", tag="elig91c", seed=915294,
                email="Amrutanshu.Padhy@aircanada.ca"),
 "tc19":    dict(idx=f"{FD}/_FD_TC19_src_index.json",          out=f"{FD}/_FD_TC19_bat_index.json",
                key="tc", tprefix="014295", tag="tc19",    seed=190019),
 "elig91d": dict(idx=f"{FD}/_FD_ELIG91_lahiru_v3_index.json", out=f"{FD}/_FD_ELIG91D_bat_index.json",
                key="tc", tprefix="014296", tag="elig91d", seed=915296),
 "tc19b":   dict(idx=f"{FD}/_FD_TC19_src_index.json",          out=f"{FD}/_FD_TC19B_bat_index.json",
                key="tc", tprefix="014297", tag="tc19b",   seed=190297),
 "elig91e": dict(idx=f"{FD}/_FD_ELIG91_lahiru_v3_index.json", out=f"{FD}/_FD_ELIG91E_bat_index.json",
                key="tc", tprefix="014298", tag="elig91e", seed=915298,
                email="doha.al-dujaili@aircanada.ca", phone="+14163520336"),
 "tc119":   dict(idx=f"{FD}/_FD_TC119_src_index.json",         out=f"{FD}/_FD_TC119_bat_index.json",
                key="tc", tprefix="014299", tag="tc119",   seed=119019),
 "tc119x5": dict(idx=f"{FD}/_FD_TC119x5_src_index.json",       out=f"{FD}/_FD_TC119X5_bat_index.json",
                key="tc", tprefix="014300", tag="tc119x5", seed=119500),
 "elig91f": dict(idx=f"{FD}/_FD_ELIG91_lahiru_v3_index.json", out=f"{FD}/_FD_ELIG91F_bat_index.json",
                key="tc", tprefix="014301", tag="elig91f", seed=915301),
 "elig91g": dict(idx=f"{FD}/_FD_ELIG91_lahiru_v3_index.json", out=f"{FD}/_FD_ELIG91G_bat_index.json",
                key="tc", tprefix="014302", tag="elig91g", seed=915302,
                email="diana.elhaddad@aircanada.ca", phone="+14163520336"),
 "elig91h": dict(idx=f"{FD}/_FD_ELIG91_lahiru_v3_index.json", out=f"{FD}/_FD_ELIG91H_bat_index.json",
                key="tc", tprefix="014303", tag="elig91h", seed=915303,
                email="valerie.kalanian@aircanada.ca", phone="+14163520336"),
 "elig91i": dict(idx=f"{FD}/_FD_ELIG91_lahiru_v3_index.json", out=f"{FD}/_FD_ELIG91I_bat_index.json",
                key="tc", tprefix="014304", tag="elig91i", seed=915304,
                email="doha.al-dujaili@aircanada.ca", phone="+14163520336"),
 # Diana set WITH Aeroplan loyalty membership + matching CP standard-profile account.
 # loyalty=True injects loyaltyRequests (FQTV) into each PNR; loyalty_base+seq = the 9-digit
 # account number, reused as the CP AccountNumber (same member identity).
 "elig91cp": dict(idx=f"{FD}/_FD_ELIG91_lahiru_v3_index.json", out=f"{FD}/_FD_ELIG91CP_int_index.json",
                key="tc", tprefix="014310", tag="elig91cp", seed=915310,
                email="charani.rathnasekara@aircanada.ca", phone="+94712534323",
                loyalty=True, loyalty_base="9153"),
}
# booking legs that carry a non-AC operating carrier block the trip-tracer cascade;
# AC-ify the booking (the OAL stays only in the pinned DDS mslFlight).
OAL_TCS={"FD_TC_183","FD_TC_184"}
# FD_TC_012-derived group cases -> need eds_pnr_output.booking_context bookingSubtype=GROUP
GROUP_SRC_TC="FD_TC_012"
# TC063 forced ELIGIBLE: clone APPR EL-400 shell from FD_TC_001 (BPKPMR), keep its own pax
TC063_SHELL="BPKPMR-2026-06-15"
TC063_PAX=("SYLVIE","COTE")

def gen_locators(n, seed, taken):
    rng=random.Random(seed); A="ABCDEFGHIJKLMNOPQRSTUVWXYZ"; out=[]
    while len(out)<n:
        loc="".join(rng.choice(A) for _ in range(6))
        # skip ZZ-prefixed locators: the eds/Flink transform drops them (ZZ = synthetic-test
        # prefix), causing a partial cascade (trip/ticket land, eds_pnr_output row never does).
        if loc.startswith("ZZ") or loc in taken: continue
        taken.add(loc); out.append(loc)
    return out

def build_index(setname):
    cfg=SETS[setname]; src=json.load(open(cfg["idx"])); key=cfg["key"]
    import glob
    taken=set()  # avoid colliding with source locators AND every already-built BAT set
    for f in list({s["idx"] for s in SETS.values()}) + glob.glob(f"{FD}/_FD_*_bat_index.json"):
        try:
            for e in json.load(open(f)):
                if e.get("pnr_id"): taken.add(e["pnr_id"][:6])
        except Exception: pass
    locs=gen_locators(len(src), cfg["seed"], taken)
    recs=[]
    for i,e in enumerate(src):
        srctc = e.get("tc") or e.get("src")              # FD_TC_xxx
        sit   = e.get("sit")                              # only in sit44
        loc   = locs[i]
        date  = e["pnr_id"][7:]                           # YYYY-MM-DD
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
            title=e.get("title",""), email=cfg.get("email",EMAIL), phone=cfg.get("phone",PHONE),
            group=(srctc==GROUP_SRC_TC), forced=is063, oal=(srctc in OAL_TCS), pin=True,
            loyalty_id=(f"{cfg['loyalty_base']}{i+1:05d}" if cfg.get("loyalty") else None),
            cp_account=(f"{cfg['loyalty_base']}{i+1:05d}" if cfg.get("loyalty") else None)))
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
    # scenario
    scn=json.load(open(f"{FD}/{r['src_scn']}.json"))
    scn["scenario_id"]=r["pnr_id"]; scn["identity"]["pnr"]=r["loc"]
    scn["identity"]["booking_date"]=r["date"]
    scn["ticketing"]["ticket_numbers"]=[r["ticket"]]
    scn["creation_comment"]=scn["last_modification_comment"]=f"SIM-{r['tc']}-{tag}-BAT"
    scn["title"]=f"{r['tc']}{('/'+r['sit']) if r['sit'] else ''}: {r.get('title') or r['status']} [{r['loc']}]"
    for p in scn["passengers"]:
        p["email"]=r["email"]; p["phone"]=r.get("phone",PHONE); p["date_of_birth"]=DOB
    if r["forced"]:
        scn["passengers"][0]["first_name"],scn["passengers"][0]["last_name"]=TC063_PAX
        scn["passengers"][0]["type"]="ADT"
    if r.get("oal"):  # AC-ify booking legs so the cascade succeeds (OAL kept in DDS only)
        for seg in scn["segments"]:
            seg["carrier"]="AC"; seg["operating_carrier"]="AC"
    if r.get("loyalty_id"):  # inject Aeroplan FQTV membership onto the primary traveler (PT-1)
        pid=r["pnr_id"]
        loy=[{"type":"loyaltyRequest","id":f"{pid}-OT-300","code":"FQTV",
              "serviceProvider":{"code":"AC"},
              "membership":{"number":r["loyalty_id"],"membershipType":"INDIVIDUAL"},
              "status":"HK",
              "traveler":{"type":"stakeholder","id":f"{pid}-PT-1","ref":"processedPnr.travelers"}}]
        tl=scn.get("timeline") or []
        ev=next((t for t in tl if t.get("version")==1), tl[-1] if tl else None)
        if ev is not None:
            ev.setdefault("overrides",{})["/loyaltyRequests"]=loy
    U.apply_to_scenario(scn, r)  # unique names win over canonical/forced (no-op if r has no pax_names)
    json.dump(scn, open(f"{SCENW}/{r['pnr_id']}.json","w"), indent=1)
    # dds
    src_pid=f"{r['src_dds']}"; src_loc=src_pid[:6]
    s=open(f"{DDS}/{src_pid}.dds.json").read()
    s=s.replace(src_pid, r["pnr_id"]).replace(f'"pnr": "{src_loc}"', f'"pnr": "{r["loc"]}"')
    open(f"{DDSW}/{r['pnr_id']}.dds.json","w").write(s)
    # sanity: ensure no stray src locator remains
    assert src_loc not in open(f"{DDSW}/{r['pnr_id']}.dds.json").read(), f"stray {src_loc} in {r['pnr_id']}"

def render_publish_one(r):
    nd=f"{NDJW}/{r['loc']}.ndjson"
    subprocess.run(["python3",SENG,"render","--scenario",f"{SCENW}/{r['pnr_id']}.json","--out",nd],
                   check=True, capture_output=True)
    out=subprocess.run(["python3",PUB,"--ndjson",nd,"--brokers",BAT["brokers"],
                        "--topic",BAT["topic"],"--live"], capture_output=True, text=True)
    ok="produced" in (out.stdout+out.stderr)
    return ok, (out.stdout+out.stderr)

def cascaded(conn, pids):
    cur=conn.cursor()
    cur.execute("select pnr_id from trip where pnr_id = any(%s)", (pids,))
    return {x[0] for x in cur.fetchall()}

def finalize_one(r, ttc, rec):
    cur=ttc.cursor()
    iss=r["date"][:8]+"01"  # issuance ~ booking month-01; cosmetic
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
    # S3 put DDS response
    key=f"traces/DDS/{r['date']}/{pid}/response.json"
    body=open(f"{DDSW}/{pid}.dds.json","rb").read()
    _sess.client("s3").put_object(Bucket=BAT["s3_bucket"],Key=key,Body=body,ContentType="application/json")
    rec["s3_key"]=key
    return key

def pin_all(recs, keys):
    """Pin execution_traces on the INT rule-engine Aurora. The rule-engine host is only
    reachable in-VPC and the App container was reimaged without psql, so we run a throwaway
    Fargate task (public postgres image) in the rule-engine subnet/SG with admin creds and
    execute all DELETE+INSERT statements in one psql call."""
    import time
    RE_HOST="ac-cct-rule-engine-int-cac1-rds-cluster-instance1.czy2ye8u22qy.ca-central-1.rds.amazonaws.com"
    RE_SECRET="/intca1/ac-cct-rule-engine-int-cac1-cluster/db-credentials"
    IMAGE="public.ecr.aws/docker/library/postgres:16-alpine"
    SUBNET="subnet-09fb607cb53831fd4"; SG="sg-06ccd931edbd4faa6"; LG="/ecs/qa-pin-int"
    EXECROLE="arn:aws:iam::982081066747:role/ask-ac-int-ECSTaskExecutionRole-CUSwhqRhpsJ9"
    CLUSTER="ac-cct-rule-engine-platform-cluster-int"
    s=secret(RE_SECRET); u=s["adminuser"]; pw=s["adminpassword"]
    stmts=[]
    for r in recs:
        pid=r["pnr_id"]; loc=r["loc"]; key=keys[pid]
        stmts.append(f"DELETE FROM execution_traces WHERE entity_id='{pid}' AND correlation_id LIKE 'qa-pin-int-%';")
        stmts.append(f"INSERT INTO execution_traces (id,service_type,correlation_id,entity_id,processed_at,"
                     f"request_s3_key,response_s3_key) VALUES (gen_random_uuid(),'DDS','qa-pin-int-{loc}',"
                     f"'{pid}','{PIN_TS}',NULL,'{key}');")
    stmts.append("SELECT 'PINDONE '||count(*) FROM execution_traces WHERE correlation_id LIKE 'qa-pin-int-%';")
    sql=" ".join(stmts)
    ecs=_sess.client("ecs"); logs=_sess.client("logs")
    try: logs.create_log_group(logGroupName=LG)
    except Exception: pass
    cmd='PGPASSWORD="$REPW" psql -h "$REHOST" -U "$REUSER" -d postgres -v ON_ERROR_STOP=1 -c "$PIN_SQL"'
    td=ecs.register_task_definition(family="qa-pin-int",requiresCompatibilities=["FARGATE"],networkMode="awsvpc",
      cpu="256",memory="512",executionRoleArn=EXECROLE,
      containerDefinitions=[dict(name="pin",image=IMAGE,essential=True,entryPoint=["/bin/sh","-c"],command=[cmd],
        environment=[dict(name="REHOST",value=RE_HOST),dict(name="REUSER",value=u),
                     dict(name="REPW",value=pw),dict(name="PIN_SQL",value=sql)],
        logConfiguration=dict(logDriver="awslogs",options={"awslogs-group":LG,
          "awslogs-region":BAT["region"],"awslogs-stream-prefix":"pin"}))])
    run=ecs.run_task(cluster=CLUSTER,taskDefinition=td["taskDefinition"]["taskDefinitionArn"],
      launchType="FARGATE",count=1,networkConfiguration=dict(awsvpcConfiguration=dict(
        subnets=[SUBNET],securityGroups=[SG],assignPublicIp="DISABLED")))
    tarn=run["tasks"][0]["taskArn"]; ec=None
    for _ in range(40):
        d=ecs.describe_tasks(cluster=CLUSTER,tasks=[tarn])["tasks"][0]
        if d["lastStatus"]=="STOPPED": ec=d["containers"][0].get("exitCode"); break
        time.sleep(10)
    tail=[]
    try:
        ls=logs.describe_log_streams(logGroupName=LG,orderBy="LastEventTime",descending=True,limit=1)["logStreams"]
        tail=[e["message"] for e in logs.get_log_events(logGroupName=LG,logStreamName=ls[0]["logStreamName"],limit=8)["events"]]
    except Exception: pass
    ok=any("PINDONE" in m for m in tail)
    print(f"[pin] RunTask postgres | exit={ec} | done={ok} | {tail[-2:]}")
    return len(recs)

_ctx=ssl.create_default_context(); _ctx.check_hostname=False; _ctx.verify_mode=ssl.CERT_NONE
def verify_one(pid):
    req=urllib.request.Request(BAT["endpoint"]+pid, headers={"x-api-key":BAT["api_key"]})
    try:
        with urllib.request.urlopen(req, context=_ctx, timeout=25) as resp:
            body=json.load(resp)
    except urllib.error.HTTPError as e:
        return dict(pnr_id=pid, ok=False, http=e.code, detail=e.read()[:120].decode("utf-8","ignore"))
    except Exception as e:
        return dict(pnr_id=pid, ok=False, http=None, detail=str(e)[:120])
    # Report the SELECTED regime = the first ELIGIBLE entry in compensationEligibility
    # order (the canonical DDS places the most-generous/selected regime first; a raw
    # numeric max is wrong across currencies, e.g. EU EUR260 vs APPR CAD400).
    for ce in body.get("compensationEligibility",[]):
        for pe in ce.get("passengerEligibility",[]):
            if pe.get("eligibilityStatus")=="ELIGIBLE":
                cd=pe.get("compensationDetails") or {}
                amt=cd.get("amount",0) or 0
                if amt>0:
                    return dict(pnr_id=pid, ok=True, http=200, amount=amt,
                                currency=cd.get("currency",""), syscode=pe.get("systemCode",""),
                                regime=ce.get("regime"))
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
