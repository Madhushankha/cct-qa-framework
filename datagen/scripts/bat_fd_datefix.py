#!/usr/bin/env python3
"""Fix the flight DATE on the temporal-edge FD cases so the booking date matches the case intent
(the bot's date pre-checks: departed? 72h? 366d?). Shifts EVERY date in scenario+DDS by
(newdate - 2026-06-15) so relative offsets (expiry +1yr, promised-window -14d) stay consistent.
FRESH locator (Altea PNRs are locator-keyed: reuse would drop eds). Republish->cascade->finalize
->pin->verify->update index in place. Usage: bat_fd_datefix.py <set_index.json>
  FD_TC_063 -> future (pre-travel, NO DDS pin -> endpoint 404)
  FD_TC_060/116/145 -> within 72h (keep PENDING) ; FD_TC_039 -> >366d ago (keep NE)
Dates are relative to a TODAY passed via env FIX_TODAY=YYYY-MM-DD (default: derived below)."""
import sys, os, json, re, time, datetime, ssl, urllib.request, glob
sys.path.insert(0,f"{KB}/scripts")
import bat_fd_build as bf
BASE=datetime.date(2026,6,15)
TODAY=datetime.date.fromisoformat(os.environ.get("FIX_TODAY","2026-07-05"))
FUT=(TODAY+datetime.timedelta(days=30)).isoformat()
NEAR=(TODAY-datetime.timedelta(days=1)).isoformat()
OLD=(TODAY-datetime.timedelta(days=401)).isoformat()
FIX={"FD_TC_063":(FUT,False),"FD_TC_060":(NEAR,True),"FD_TC_116":(NEAR,True),"FD_TC_145":(NEAR,True),"FD_TC_039":(OLD,True)}
idxf=sys.argv[1]
def shift(text, delta):
    def repl(m):
        try: d=datetime.date.fromisoformat(m.group(0))
        except ValueError: return m.group(0)
        return (d+datetime.timedelta(days=delta)).isoformat()
    return re.sub(r'\d{4}-\d{2}-\d{2}', repl, text)
def build_one(tc, entry, newdate, loc):
    delta=(datetime.date.fromisoformat(newdate)-BASE).days
    new_pid=f"{loc}-{newdate}"; src_scn=entry["src_scn"]; src_dds=entry["src_dds"]; src_loc=src_scn[:6]
    scn=json.loads(shift(open(f"{bf.FD}/{src_scn}.json").read(), delta))
    scn["scenario_id"]=new_pid; scn["identity"]["pnr"]=loc; scn["identity"]["booking_date"]=newdate
    scn["ticketing"]["ticket_numbers"]=[entry["ticket"]]
    scn["creation_comment"]=scn["last_modification_comment"]=f"SIM-{tc}-datefix-BAT"
    scn["title"]=f"{tc}: DATEFIX {newdate} [{loc}]"
    for p in scn["passengers"]: p["email"]=entry["email"]; p["phone"]=entry["phone"]; p["date_of_birth"]=bf.DOB
    if tc=="FD_TC_063": scn["passengers"][0]["first_name"],scn["passengers"][0]["last_name"]=bf.TC063_PAX; scn["passengers"][0]["type"]="ADT"
    json.dump(scn, open(f"{bf.SCENW}/{new_pid}.json","w"), indent=1)
    s=shift(open(f"{bf.DDS}/{src_dds}.dds.json").read(), delta).replace(src_loc, loc)
    open(f"{bf.DDSW}/{new_pid}.dds.json","w").write(s); assert src_loc not in open(f"{bf.DDSW}/{new_pid}.dds.json").read()
    return new_pid
idx=json.load(open(idxf)); pos={r["tc"]:i for i,r in enumerate(idx)}
taken=set()
for f in glob.glob(f"{bf.FD}/_FD_*_bat_index.json"):
    for e in json.load(open(f)):
        if e.get("pnr_id"): taken.add(e["pnr_id"][:6])
locs=bf.gen_locators(len(FIX), 730730, taken); jobs=[]; fi=0
for tc,(newdate,pin) in FIX.items():
    if tc not in pos: continue
    e=dict(idx[pos[tc]]); loc=locs[fi]; fi+=1
    e["loc"]=loc; e["date"]=newdate; e["pnr_id"]=f"{loc}-{newdate}"; e["ticket"]=f"{e['ticket'][:6]}8{int(tc.split('_')[-1]):05d}"
    e["forced"]=(tc=="FD_TC_063"); e["pin"]=pin
    if tc=="FD_TC_063": e["status"]=""; e["syscode"]=""; e["amount"]=0
    jobs.append([pos[tc],tc,e,newdate,pin])
for j in jobs: j[2]["pnr_id"]=build_one(j[1],j[2],j[3],j[2]["loc"]); print(f"  clone {j[1]} -> {j[2]['pnr_id']}")
for j in jobs: ok,log=bf.render_publish_one(j[2]); print(f"  publish {j[2]['pnr_id']} {'OK' if ok else 'FAIL'}")
print("waiting 55s..."); time.sleep(55)
ttc=bf.tt_conn(); have=bf.cascaded(ttc,[j[2]["pnr_id"] for j in jobs]); print("  cascaded:",len(have),"/",len(jobs))
keys={}
for j in jobs:
    e=j[2]; pin=j[4]; pid=e["pnr_id"]; cur=ttc.cursor()
    cur.execute("""insert into ticket (primary_document_number,pnr_id,passenger_id,ticket_id,document_numbers,issuance_local_date,document_type) values (%s,%s,%s,%s,ARRAY[%s],%s,'T') on conflict do nothing""",(e["ticket"],pid,f"{pid}-PT-1",f"{e['ticket']}-2026-06-01",e["ticket"],"2026-06-01"))
    cur.execute("update passenger set date_of_birth=%s where pnr_id=%s",(bf.DOB,pid)); ttc.commit()
    if pin:
        key=f"traces/DDS/{e['date']}/{pid}/response.json"
        bf._sess.client("s3").put_object(Bucket=bf.BAT["s3_bucket"],Key=key,Body=open(f"{bf.DDSW}/{pid}.dds.json","rb").read(),ContentType="application/json"); keys[pid]=key
bf.pin_all([j[2] for j in jobs if j[4]], keys); ttc.close(); time.sleep(4)
ctx=ssl.create_default_context(); ctx.check_hostname=False; ctx.verify_mode=ssl.CERT_NONE
for j in jobs:
    e=j[2]; tc=j[1]; pid=e["pnr_id"]
    try:
        b=json.load(urllib.request.urlopen(urllib.request.Request(bf.BAT["endpoint"]+pid,headers={"x-api-key":bf.BAT["api_key"]}),context=ctx,timeout=20))
        got=b["compensationEligibility"][0]["passengerEligibility"][0]["eligibilityStatus"]+"/"+b["compensationEligibility"][0]["passengerEligibility"][0].get("systemCode","")
    except urllib.error.HTTPError as x: got=f"HTTP {x.code}"
    print(f"  verify {tc} {pid} date={e['date']}: {got}")
for p,tc,e,nd,pin in jobs: idx[p]=e
json.dump(idx, open(idxf,"w"), indent=1); print("DATEFIX_DONE ->",idxf)
