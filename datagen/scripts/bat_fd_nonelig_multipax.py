#!/usr/bin/env python3
"""Build MULTI-PASSENGER (3 pax) BAT PNRs for the 87 NON-ELIGIBLE FD flows (68 NOT_ELIGIBLE +
16 NO_DETERMINATION + 3 PENDING). PO request: cover the ineligible flows with multi-pax bookings.
Each PNR carries 3 ADT passengers; the DDS passengerEligibility (in compensationEligibility[*] AND
socFlightEligibility[*]) is triplicated so all 3 pax carry the same ineligible verdict.
Reuses bat_fd_build (BAT config, render/publish, tt_conn, pin_all). Phases: index|clone|publish|
checkcascade|finalize|verify. Usage: bat_fd_nonelig_multipax.py <phase> [--start N] [--end N]
"""
import sys, os, json, time, ssl, urllib.request, subprocess, argparse, random
sys.path.insert(0,f"{KB}/scripts")
import bat_fd_build as bf

SRC=f"{bf.FD}/_FD_ALL239_bat_src_index.json"
# Per-set params via env (defaults = set 1). To mint another set, pass MPX_* env vars.
OUT=os.environ.get("MPX_OUT", f"{bf.FD}/_FD_NONELIG_MULTIPAX_bat_index.json")
EMAIL=os.environ.get("MPX_EMAIL","doha.al-dujaili@aircanada.ca")
PHONE=os.environ.get("MPX_PHONE","+14163520336")
TPREFIX=os.environ.get("MPX_TPREFIX","014312")
SEED=int(os.environ.get("MPX_SEED","870870"))
EXTRA_PAX=[("MARIE","GAGNON"),("LUC","BERGERON")]   # pax 2 + 3 (pax 1 stays the canonical claimant)
NONELIG={"NOT_ELIGIBLE","NO_DETERMINATION","PENDING"}

def build_index():
    import glob
    taken=set()
    for f in glob.glob(f"{bf.FD}/_FD_*_bat_index.json"):
        for e in json.load(open(f)):
            if e.get("pnr_id"): taken.add(e["pnr_id"][:6])
    src=[e for e in json.load(open(SRC)) if e["status"] in NONELIG]
    locs=bf.gen_locators(len(src), SEED, taken)
    recs=[]
    for i,e in enumerate(src):
        loc=locs[i]; date=e["pnr_id"][7:]; pid=f"{loc}-{date}"
        tickets=[f"{TPREFIX}{i+1:04d}{p:02d}" for p in (1,2,3)]
        recs.append(dict(tc=e["tc"], family=e.get("family"), src_scn=e["pnr_id"], src_dds=e["pnr_id"],
            loc=loc, pnr_id=pid, date=date, tickets=tickets, pax_n=3,
            claimant=e["pax"], status=e["status"], syscode=e["syscode"], amount=e["amount"],
            currency=e["currency"], route=e.get("route",""), email=EMAIL, phone=PHONE, pin=True,
            oal=(e["tc"] in bf.OAL_TCS)))
    json.dump(recs, open(OUT,"w"), indent=1)
    print(f"[index] {len(recs)} non-eligible multi-pax records -> {OUT}")

def load(): return json.load(open(OUT))

def clone_one(r):
    # scenario: canonical + 2 extra pax = 3 ADT
    scn=json.load(open(f"{bf.FD}/{r['src_scn']}.json"))
    scn["scenario_id"]=r["pnr_id"]; scn["identity"]["pnr"]=r["loc"]; scn["identity"]["booking_date"]=r["date"]
    scn["ticketing"]["ticket_numbers"]=r["tickets"]
    scn["creation_comment"]=scn["last_modification_comment"]=f"SIM-{r['tc']}-nonelig-multipax-BAT"
    scn["title"]=f"{r['tc']}: {r['status']} 3-PAX [{r['loc']}]"
    base=scn["passengers"][0]
    for (fn,ln) in EXTRA_PAX:
        scn["passengers"].append(dict(type="ADT", first_name=fn, last_name=ln, gender="U",
                                      date_of_birth=bf.DOB, email=r["email"], phone=r["phone"]))
    for p in scn["passengers"]:
        p["email"]=r["email"]; p["phone"]=r["phone"]; p["date_of_birth"]=bf.DOB
    if r.get("oal"):
        for seg in scn["segments"]: seg["carrier"]="AC"; seg["operating_carrier"]="AC"
    json.dump(scn, open(f"{bf.SCENW}/{r['pnr_id']}.json","w"), indent=1)
    # DDS: retarget locator, then triplicate passengerEligibility (comp + soc)
    src_pid=r["src_dds"]; src_loc=src_pid[:6]
    d=json.loads(open(f"{bf.DDS}/{src_pid}.dds.json").read().replace(src_pid,r["pnr_id"]).replace(f'"pnr": "{src_loc}"',f'"pnr": "{r["loc"]}"'))
    def triple(container):
        pe0=container["passengerEligibility"][0]
        out=[]
        for n in (1,2,3):
            x=json.loads(json.dumps(pe0)); x["passengerId"]=f"{r['pnr_id']}-PT-{n}"; out.append(x)
        container["passengerEligibility"]=out
    for ce in d.get("compensationEligibility",[]): triple(ce)
    for soc in d.get("socFlightEligibility",[]): triple(soc)
    open(f"{bf.DDSW}/{r['pnr_id']}.dds.json","w").write(json.dumps(d,indent=1))
    assert src_loc not in open(f"{bf.DDSW}/{r['pnr_id']}.dds.json").read()

def publish_one(r):
    nd=f"{bf.NDJW}/{r['loc']}.ndjson"
    subprocess.run(["python3",bf.SENG,"render","--scenario",f"{bf.SCENW}/{r['pnr_id']}.json","--out",nd],check=True,capture_output=True)
    o=subprocess.run(["python3",bf.PUB,"--ndjson",nd,"--brokers",bf.BAT["brokers"],"--topic",bf.BAT["topic"],"--live"],capture_output=True,text=True)
    return "produced" in (o.stdout+o.stderr)

def finalize_one(r, ttc):
    cur=ttc.cursor(); pid=r["pnr_id"]
    for n,tk in enumerate(r["tickets"],1):
        cur.execute("""insert into ticket (primary_document_number,pnr_id,passenger_id,ticket_id,document_numbers,issuance_local_date,document_type)
                       values (%s,%s,%s,%s,ARRAY[%s],%s,'T') on conflict do nothing""",
                    (tk,pid,f"{pid}-PT-{n}",f"{tk}-2026-06-01",tk,"2026-06-01"))
    cur.execute("update passenger set date_of_birth=%s where pnr_id=%s",(bf.DOB,pid)); ttc.commit()
    key=f"traces/DDS/{r['date']}/{pid}/response.json"
    bf._sess.client("s3").put_object(Bucket=bf.BAT["s3_bucket"],Key=key,Body=open(f"{bf.DDSW}/{pid}.dds.json","rb").read(),ContentType="application/json")
    return key

_ctx=ssl.create_default_context(); _ctx.check_hostname=False; _ctx.verify_mode=ssl.CERT_NONE
def verify_one(r):
    pid=r["pnr_id"]
    try:
        b=json.load(urllib.request.urlopen(urllib.request.Request(bf.BAT["endpoint"]+pid,headers={"x-api-key":bf.BAT["api_key"]}),context=_ctx,timeout=20))
    except Exception as e: return dict(pnr_id=pid,ok=False,err=str(e)[:50])
    ce=b["compensationEligibility"][0]; pes=ce.get("passengerEligibility",[])
    st=pes[0]["eligibilityStatus"] if pes else None; sc=pes[0].get("systemCode") if pes else None
    npax=len(pes); ids={p.get("passengerId","")[-4:] for p in pes}
    ok=(st==r["status"] and sc==r["syscode"] and npax==3)
    return dict(pnr_id=pid,ok=ok,status=st,syscode=sc,npax=npax,ptids=sorted(ids))

def main():
    ap=argparse.ArgumentParser(); ap.add_argument("phase"); ap.add_argument("--start",type=int,default=0); ap.add_argument("--end",type=int,default=10**9)
    a=ap.parse_args()
    if a.phase=="index": build_index(); return
    recs=load(); sl=recs[a.start:a.end]
    if a.phase=="clone":
        for r in sl: clone_one(r)
        print(f"[clone] {len(sl)} multi-pax scenarios+DDS written")
    elif a.phase=="publish":
        ok=0
        for i,r in enumerate(sl):
            g=publish_one(r); ok+=g; print(f"  [{a.start+i}] {r['pnr_id']} {r['tc']} {'OK' if g else 'FAIL'}",flush=True)
        print(f"[publish] {ok}/{len(sl)} produced")
    elif a.phase=="checkcascade":
        ttc=bf.tt_conn(); have=bf.cascaded(ttc,[r["pnr_id"] for r in sl]); ttc.close()
        print(f"[cascade] {len(have)}/{len(sl)} present; missing={[r['pnr_id'] for r in sl if r['pnr_id'] not in have]}")
    elif a.phase=="finalize":
        ttc=bf.tt_conn(); keys={}
        for i,r in enumerate(sl):
            try: keys[r["pnr_id"]]=finalize_one(r,ttc); print(f"  [{a.start+i}] {r['pnr_id']} finalized (3 tickets)",flush=True)
            except Exception as e: print(f"  [{a.start+i}] {r['pnr_id']} ERR {e}",flush=True)
        ttc.close()
        bf.pin_all([r for r in sl if r["pnr_id"] in keys], keys)
        print(f"[finalize] {len(keys)} finalized + pinned")
    elif a.phase=="verify":
        res=[verify_one(r) for r in sl]; ok=sum(1 for x in res if x["ok"])
        for x in res:
            if not x["ok"]: print("  FAIL",x)
        print(f"[verify] {ok}/{len(sl)} correct (status+syscode match, 3 pax)")
        json.dump(res,open(f"{bf.WORK}/nonelig_multipax_verify.json","w"),indent=1)

if __name__=="__main__": main()
