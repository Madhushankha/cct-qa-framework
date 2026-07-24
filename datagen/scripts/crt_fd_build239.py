#!/usr/bin/env python3
import os
"""Build the full 239-case FD ("Ask AC") test set in CRT by cloning the validated
BAT ALL239 set (_FD_ALL239_bat_index.json) — 152 EL + 68 NE + 16 ND + 3 PE, all
with pinned DDS verdicts. Same rule-engine DDS path as the CRT ELIG91 sets
(S3 cct-ask-ac-crt-logs + execution_traces + /rule-engine/dds/output).

Source index carries src_scn/src_dds (canonical scenario + DDS per case) plus
status/syscode/amount/currency/group/forced/oal/pin. We mint fresh CRT locators +
a fresh ticket series (014298) + the lahiru mailinator contact.

Verification is systemCode-match (NOT eligible-only) via fd_checkpoints.py --env crt.

Phases: index | clone | publish | checkcascade | finalize | verify
Usage: crt_fd_build239.py <phase> [--start N] [--end N]
"""
import json, os, sys, uuid, subprocess, random, ssl, urllib.request, argparse
import boto3, psycopg2

KB   = os.environ.get("CCTQA_DATAGEN_ROOT",
                      os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
FD   = f"{KB}/scenarios/fd-sit"
DDS  = f"{FD}/_dds-templates"
SENG = f"{KB}/scripts/scenario_engine.py"
PUB  = f"{KB}/scripts/publish_raw.py"
WORK = os.environ.get("CRT239_WORK", "/tmp/cctqa-datagen/crt239_work")
SCENW= f"{WORK}/scenarios"; DDSW=f"{WORK}/dds"; NDJW=f"{WORK}/ndjson"
for d in (SCENW, DDSW, NDJW): os.makedirs(d, exist_ok=True)

SRC = f"{FD}/_FD_ALL239_bat_index.json"     # BAT built index (has src_scn/src_dds + metadata)
OUT = os.environ.get("CRT239_OUT", f"{FD}/_FD_ALL239_crt_index.json")
TPREFIX=os.environ.get("CRT239_TPREFIX","014298"); SEED=int(os.environ.get("CRT239_SEED","982098"))
UNIQ = os.environ.get("CRT_UNIQ_NAMES") == "1"   # opt-in DB-absent unique passenger names (default OFF)

CRT = dict(
  profile="ac-cct-crt", region="ca-central-1",
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
  api_key=os.environ.get("DDS_API_KEY", ""),
)
EMAIL=os.environ.get("CRT_EMAIL","lahiru@ae-qa1-aircanada.mailinator.com")
PHONE=os.environ.get("CRT_PHONE","7059873342")
DOB="1986-04-23"
PIN_TS="2028-06-30 00:00:00+00"
TC063_PAX=("SYLVIE","COTE")

_sess=boto3.Session(profile_name=CRT["profile"], region_name=CRT["region"])
_seccache={}
def secret(sid):
    if sid not in _seccache:
        _seccache[sid]=json.loads(_sess.client("secretsmanager").get_secret_value(SecretId=sid)["SecretString"])
    return _seccache[sid]
def tt_conn():
    import _cctdb
    return _cctdb.trip_tracer(CRT["tt_host"], profile=CRT.get("profile"))
def re_conn():
    s=secret(CRT["re_secret"])
    return psycopg2.connect(host=CRT["re_host"],port=5432,dbname=CRT["re_db"],
                            user=s["adminuser"],password=s["adminpassword"],sslmode="require",connect_timeout=20)

def all_taken():
    import glob, os as _os
    taken=set(); outabs=_os.path.abspath(OUT)
    for f in glob.glob(f"{FD}/_FD_*index.json"):
        if _os.path.abspath(f)==outabs: continue   # skip our own output so re-running index is deterministic
        try:
            for e in json.load(open(f)):
                p=e.get("pnr_id","")
                if p: taken.add(p[:6])
        except Exception: pass
    return taken

def gen_locators(n, seed, taken):
    rng=random.Random(seed); A="ABCDEFGHIJKLMNOPQRSTUVWXYZ"; out=[]
    while len(out)<n:
        loc="".join(rng.choice(A) for _ in range(6))
        if loc in taken: continue
        taken.add(loc); out.append(loc)
    return out

# PENDING verdicts only hold while the flight is within +-72h of today, so a PENDING case must be
# dated NEAR-TERM at build time — not left on the stale BAT source date (which ages out immediately).
# We date it ~2 days ago (recently flown, determination pending) and clone_one shifts the scenario
# segments + DDS to match; the cascade then produces a consistent eds promisedWindow automatically.
import datetime as _dt
PENDING_DATE = os.environ.get("CRT239_PENDING_DATE",
                              (_dt.date.today() - _dt.timedelta(days=2)).isoformat())

def _is_pending(status, syscode):
    return status == "PENDING" or "-PE-" in (syscode or "")

def build_index():
    src=json.load(open(SRC)); taken=all_taken()
    locs=gen_locators(len(src), SEED, taken)
    recs=[]
    for i,e in enumerate(src):
        date=e.get("date") or e["pnr_id"][7:]
        loc=locs[i]; new_pid=f"{loc}-{date}"
        forced=bool(e.get("forced"))
        status,syscode,amount,currency,pin=(e.get("status"),e.get("syscode"),e.get("amount"),
                                            e.get("currency"),bool(e.get("pin")))
        if forced:   # TC063 pre-travel forced ELIGIBLE (EL-400 shell), matching the validated v1 build
            status,syscode,amount,currency,pin="ELIGIBLE","FD-APPR-EL-400",400,"CAD",True
        # PENDING -> near-term date; keep the source date so clone_one can shift segments + DDS to it.
        src_date=date
        if _is_pending(status,syscode):
            date=PENDING_DATE; new_pid=f"{loc}-{date}"
        recs.append(dict(
            tc=e.get("tc"), sit=e.get("sit"),
            src_scn=e["src_scn"], src_dds=e["src_dds"],
            loc=loc, pnr_id=new_pid, date=date, src_date=src_date,
            ticket=f"{TPREFIX}{i+1:06d}", pax=e.get("pax"), route=e.get("route",""),
            status=status, syscode=syscode, amount=amount,
            currency=currency, title=e.get("title",""), email=EMAIL, phone=PHONE,
            group=bool(e.get("group")), forced=forced, oal=bool(e.get("oal")),
            family=e.get("family"), pin=pin))
    if UNIQ:
        # DB-absent unique passenger names, same as the domain builders — the 239 flow historically
        # cloned the canonical BAT names (all long-present in the DB). assign_names sets r["pax_names"]
        # (applied by clone_one) + r["pax"] + r["uniq_names"]=True so the checkpoint enforces it.
        import crt_uniqnames as U
        def _npax(r):
            try: return max(1, len(json.load(open(f"{FD}/{r['src_scn']}.json"))["passengers"]))
            except Exception: return 1
        conn=tt_conn(); U.assign_names(recs, _npax, conn, seed=SEED); conn.close()
        print(f"[index] assigned unique DB-absent names to {len(recs)} records")
    json.dump(recs, open(OUT,"w"), indent=1)
    print(f"[index] {len(recs)} records -> {OUT}")
    return recs

def load_index(): return json.load(open(OUT))

def _scn_flight_date(scn):
    """The scenario's actual flight date (first segment dep_local, date-part) — this is the truth to
    shift FROM, and it can differ from the index pnr_id date in the BAT source."""
    for s in scn.get("segments", []):
        v=s.get("dep_local") or s.get("dep_utc")
        if isinstance(v,str) and len(v)>=10: return v[:10]
    return None

def _shift_scn_dates(scn, from_date, to_date):
    """Shift every segment's flight date from `from_date` to `to_date` on all datetime fields. Used
    for PENDING so the flight lands in the +-72h window; the cascade then derives a consistent eds
    promisedWindow from these dates (no post-seed surgery)."""
    if not from_date or from_date == to_date:
        return
    for s in scn.get("segments", []):
        for k in ("dep_local","arr_local","dep_utc","arr_utc","booking_datetime"):
            if isinstance(s.get(k), str):
                s[k]=s[k].replace(from_date, to_date)

def clone_one(r):
    scn=json.load(open(f"{FD}/{r['src_scn']}.json"))
    scn["scenario_id"]=r["pnr_id"]; scn["identity"]["pnr"]=r["loc"]
    scn["identity"]["booking_date"]=r["date"]
    # PENDING: shift the flight from the scenario's real date to the near-term target so it's in-window.
    r["_scn_from"]=_scn_flight_date(scn) if _is_pending(r.get("status"), r.get("syscode")) else None
    if r["_scn_from"]:
        _shift_scn_dates(scn, r["_scn_from"], r["date"])
    scn["ticketing"]["ticket_numbers"]=[r["ticket"]]
    scn["creation_comment"]=scn["last_modification_comment"]=f"SIM-{r['tc']}-all239-CRT"
    scn["title"]=f"{r['tc']}: {r.get('title') or r['status']} [{r['loc']}]"
    for p in scn["passengers"]:
        p["email"]=EMAIL; p["phone"]=PHONE; p["date_of_birth"]=DOB
    if r["oal"]:
        # AC-ify booking legs (non-AC operating_carrier blocks the trip-tracer cascade);
        # the real OAL carrier is preserved in the pinned DDS mslFlight, which drives eligibility.
        for s in scn["segments"]:
            s["carrier"]="AC"; s["operating_carrier"]="AC"
            if s.get("operating_flight_number") is not None:
                s["operating_flight_number"]=s.get("flight_number")
    if r["forced"]:
        scn["passengers"][0]["first_name"],scn["passengers"][0]["last_name"]=TC063_PAX
        scn["passengers"][0]["type"]="ADT"
    # unique-name override (wins over canonical/forced) — one verified DB-absent name per passenger
    if r.get("pax_names"):
        for j,p in enumerate(scn["passengers"]):
            if j < len(r["pax_names"]):
                p["first_name"],p["last_name"]=r["pax_names"][j]
    json.dump(scn, open(f"{SCENW}/{r['pnr_id']}.json","w"), indent=1)
    src_pid=r["src_dds"]; src_loc=src_pid[:6]
    s=open(f"{DDS}/{src_pid}.dds.json").read()
    s=s.replace(src_pid, r["pnr_id"]).replace(f'"pnr": "{src_loc}"', f'"pnr": "{r["loc"]}"')
    # PENDING: move the DDS itinerary date to the near-term flight date so the pinned verdict and the
    # booking agree (booking==dds date + PENDING flight<=72h). Shift from the scenario's real flight
    # date (same value the DDS itinerary uses). Non-PENDING keep their source date.
    if r.get("_scn_from") and r["_scn_from"] != r["date"]:
        s=s.replace(r["_scn_from"], r["date"])
    open(f"{DDSW}/{r['pnr_id']}.dds.json","w").write(s)
    assert src_loc not in open(f"{DDSW}/{r['pnr_id']}.dds.json").read(), f"stray {src_loc} in {r['pnr_id']}"

def render_publish_one(r):
    nd=f"{NDJW}/{r['loc']}.ndjson"
    subprocess.run(["python3",SENG,"render","--scenario",f"{SCENW}/{r['pnr_id']}.json","--out",nd],
                   check=True, capture_output=True)
    out=subprocess.run(["python3",PUB,"--ndjson",nd,"--brokers",CRT["brokers"],
                        "--topic",CRT["topic"],"--live"], capture_output=True, text=True)
    return ("produced" in (out.stdout+out.stderr)), (out.stdout+out.stderr)

def cascaded(conn, pids):
    cur=conn.cursor(); cur.execute("select pnr_id from trip where pnr_id = any(%s)", (pids,))
    return {x[0] for x in cur.fetchall()}

def finalize_one(r, ttc, rec):
    cur=ttc.cursor(); iss="2026-06-01"; pid=r["pnr_id"]; tk=r["ticket"]
    # ONE TICKET PER PASSENGER. PT-1 keeps the index ticket ({prefix}{case:06d}); PT-2..PT-n get
    # {prefix}{case:04d}{pax:02d} — a band above 000239 so it can't collide with the base series.
    # (Previously only PT-1 got a ticket, silently leaving multi-pax/GROUP pax ticketless.)
    prefix, case = tk[:6], int(tk[6:])
    cur.execute("select passenger_id from passenger where pnr_id=%s and not is_removed",(pid,))
    pts=sorted((int(p[0].rsplit("-PT-",1)[1]) for p in cur.fetchall()))
    for k in pts:
        t = tk if k==1 else f"{prefix}{case:04d}{k:02d}"
        cur.execute("""insert into ticket
            (primary_document_number,pnr_id,passenger_id,ticket_id,document_numbers,issuance_local_date,document_type)
            values (%s,%s,%s,%s,ARRAY[%s],%s,'T') on conflict do nothing""",
            (t,pid,f"{pid}-PT-{k}",f"{t}-{iss}",t,iss))
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
    conn=re_conn(); cur=conn.cursor(); ents=[r["pnr_id"] for r in recs]
    cur.execute("delete from execution_traces where service_type='DDS' and entity_id = any(%s) and correlation_id like 'qa-pin-crt-%%'",(ents,))
    rows=[(r["pnr_id"], f"qa-pin-crt-{r['loc']}", keys[r["pnr_id"]]) for r in recs]
    cur.executemany("""insert into execution_traces
        (id,service_type,correlation_id,entity_id,processed_at,request_s3_key,response_s3_key)
        values (gen_random_uuid(),'DDS',%s,%s,%s,NULL,%s)""",
        [(cor,ent,PIN_TS,key) for (ent,cor,key) in rows])
    conn.commit(); conn.close(); return len(rows)

_ctx=ssl.create_default_context(); _ctx.check_hostname=False; _ctx.verify_mode=ssl.CERT_NONE
def verify_one(r):
    pid=r["pnr_id"]
    req=urllib.request.Request(CRT["endpoint"]+pid, headers={"x-api-key":CRT["api_key"]})
    try:
        with urllib.request.urlopen(req, context=_ctx, timeout=25) as resp: body=json.load(resp)
    except Exception as e:
        return dict(pnr_id=pid, ok=False, detail=str(e)[:120])
    try:
        got=body["compensationEligibility"][0]["passengerEligibility"][0]["systemCode"]
    except Exception:
        return dict(pnr_id=pid, ok=False, detail="no systemCode in response")
    return dict(pnr_id=pid, ok=(got==r["syscode"]), expected=r["syscode"], got=got)

def main():
    ap=argparse.ArgumentParser(); ap.add_argument("phase")
    ap.add_argument("--start",type=int,default=0); ap.add_argument("--end",type=int,default=10**9)
    a=ap.parse_args()
    if a.phase=="index": build_index(); return
    recs=load_index(); sl=recs[a.start:a.end]
    if a.phase=="clone":
        for r in sl: clone_one(r)
        print(f"[clone] {len(sl)} scenarios+DDS written")
    elif a.phase=="publish":
        ok=0
        for i,r in enumerate(sl):
            good,log=render_publish_one(r); ok+=good
            print(f"  [{a.start+i}] {r['pnr_id']} {r['status'][:2]} {'OK' if good else 'FAIL '+log[-160:]}",flush=True)
        print(f"[publish] {ok}/{len(sl)} produced")
    elif a.phase=="checkcascade":
        ttc=tt_conn(); have=cascaded(ttc,[r["pnr_id"] for r in sl]); ttc.close()
        miss=[r["pnr_id"] for r in sl if r["pnr_id"] not in have]
        print(f"[cascade] {len(have)}/{len(sl)} present; missing({len(miss)})={miss[:12]}")
    elif a.phase=="finalize":
        ttc=tt_conn(); keys={}
        for i,r in enumerate(sl):
            try:
                keys[r["pnr_id"]]=finalize_one(r,ttc,r); print(f"  [{a.start+i}] {r['pnr_id']} finalized",flush=True)
            except Exception as e:
                # the trip-tracer connection can be dropped by the server during the slow S3 puts
                # between DB ops (idle/statement timeout). Reconnect once and retry so the rest of the
                # batch isn't lost to a single "connection already closed".
                if "closed" in str(e).lower() or "ssl" in str(e).lower():
                    try:
                        try: ttc.close()
                        except Exception: pass
                        ttc=tt_conn()
                        keys[r["pnr_id"]]=finalize_one(r,ttc,r); print(f"  [{a.start+i}] {r['pnr_id']} finalized (reconn)",flush=True)
                        continue
                    except Exception as e2: e=e2
                print(f"  [{a.start+i}] {r['pnr_id']} ERR {e}",flush=True)
        try: ttc.close()
        except Exception: pass
        n=pin_all([r for r in sl if r["pnr_id"] in keys], keys)
        full=load_index(); bypid={r["pnr_id"]:r for r in sl}
        for r in full:
            if r["pnr_id"] in bypid and bypid[r["pnr_id"]].get("s3_key"): r["s3_key"]=bypid[r["pnr_id"]]["s3_key"]
        json.dump(full, open(OUT,"w"), indent=1)
        print(f"[finalize] tickets/DOB/S3 done; pinned {n} DDS rows")
    elif a.phase=="verify":
        res=[verify_one(r) for r in sl]; ok=sum(1 for x in res if x["ok"])
        for x in res:
            if not x["ok"]: print("  BAD",x)
        print(f"[verify] {ok}/{len(sl)} systemCode match")
        json.dump(res, open(f"{WORK}/verify.json","w"), indent=1)
    else: print("unknown phase"); sys.exit(2)

if __name__=="__main__": main()
