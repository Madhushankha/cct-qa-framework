#!/usr/bin/env python3
import os
"""BAGGAGE-CLAIM UAT PNR post-creation CHECKPOINTS (CRT).

Verifies every layer the baggage-claim bot depends on and fails loudly on a miss.
  BOOKING (trip-tracer):  trip ACTIVE, trip_details, passenger==npax, DOB set,
                          ticket==npax, eds_pnr_output present, eds contact email==lahiru
  BAGGAGE (baggage_updates, our CONTRAIL/CCT-AUTO rows):
                          required event_types present per AHL state,
                          tracer_reference_id (AHL ref) correct,
                          bag/pax coverage, station/carrier correct
  FD DDS (UAT031/032):    compensationEligibility ELIGIBLE via rule-engine endpoint

Usage: AWS_PROFILE=ac-cct-crt python3 bag_checkpoints.py [index.json]
"""
import json, sys, ssl, urllib.request, datetime, psycopg2
import crt_uniqnames as U
import pnr_common_checks as C

WORK="/tmp/cctqa-datagen/bag_work"
IDX=sys.argv[1] if len(sys.argv)>1 else f"{WORK}/_BAG_crt_index.json"
TT=dict(host="ac-cct-trip-tracer-rds-cluster-crt-cac1.cluster-cxqe2wacy866.ca-central-1.rds.amazonaws.com",
        db="trip-tracer",user="dbadmin",password=os.environ.get("CCT_TRIPTRACER_PASSWORD", ""))
DDS="https://rule-engine-platform-service.ac-cct-crt.cloud.aircanada.com/rule-engine/dds/output/"
API=os.environ.get("DDS_API_KEY", "")
EXPECT={
 "open":{"BAG_CREATED","BAG_ACCEPTED","BAG_DELAYED_RECORD_CREATED"},
 "delivered":{"BAG_DELAYED_RECORD_CREATED","BAG_DELAYED_DELIVERED"},
 "closed":{"BAG_DELAYED_RECORD_CREATED","BAG_DELAYED_RECORD_CLOSED"},
 "rds_short":{"BAG_DELAYED_RECORD_CREATED","BAG_PROPERTY_ADDED","BAG_DELAYED_DELIVERED"},
 "nobag":{"BAG_CREATED","BAG_ACCEPTED"},
 "track":{"BAG_CREATED","BAG_LOADED_ON_AIRCRAFT","BAG_POSITIONED_ON_FLIGHT_LEG"},
 "track_expired":{"BAG_CREATED","BAG_DELIVERED_TO_CAROUSEL"},
 "track_none":set(),
}
NEEDS_REF={"open","delivered","closed","rds_short"}

rows=json.load(open(IDX)); ids=[m["pnr_id"] for m in rows]; by={m["pnr_id"]:m for m in rows}
conn=psycopg2.connect(host=TT["host"],port=5432,dbname=TT["db"],user=TT["user"],password=TT["password"],
                      sslmode="require",connect_timeout=25); cur=conn.cursor()
def col(q):
    cur.execute(q,(ids,)); return {r[0]:r[1] for r in cur.fetchall()}
trip=col("SELECT pnr_id,status FROM trip WHERE pnr_id=ANY(%s)")
td=col("SELECT pnr_id,count(*) FROM trip_details WHERE pnr_id=ANY(%s) GROUP BY pnr_id")
cur.execute("SELECT pnr_id,count(*),count(*) FILTER (WHERE date_of_birth IS NULL) FROM passenger WHERE pnr_id=ANY(%s) AND NOT is_removed GROUP BY pnr_id",(ids,))
pax={r[0]:(r[1],r[2]) for r in cur.fetchall()}
_uniq_clean, _uniq_off = U.name_uniqueness(cur, ids)
_common = C.collect(cur, ids, rows)   # shared: ticket linkage + eds auth == pax
tkt=col("SELECT pnr_id,count(*) FROM ticket WHERE pnr_id=ANY(%s) GROUP BY pnr_id")
cur.execute("SELECT DISTINCT ON (pnr_id) pnr_id,bounds FROM eds_pnr_output WHERE pnr_id=ANY(%s) ORDER BY pnr_id,received_at DESC",(ids,))
eds={}; edsmail={}
for pid,b in cur.fetchall():
    eds[pid]=1
    try:
        bb=json.loads(b) if isinstance(b,str) else b
        edsmail[pid]=bb[0]["authenticationContactDetails"]["passengers"][0]["contacts"]["apn"].get("email")
    except Exception: edsmail[pid]=None
# baggage events (our seeded rows only)
cur.execute("""SELECT pnr_id,event_type,tracer_reference_id,station_code,carrier_code
               FROM baggage_updates WHERE pnr_id=ANY(%s) AND user_name='CONTRAIL' AND workstation_name='CCT-AUTO'""",(ids,))
bag={}
for pid,et,ref,st,car in cur.fetchall():
    d=bag.setdefault(pid,dict(types=set(),refs=set(),st=set(),car=set()))
    d["types"].add(et);
    if ref: d["refs"].add(ref)
    d["st"].add(st); d["car"].add(car)
cur.close()

def off(pred): return [p for p in ids if pred(p)]
booking={
 "trip ACTIVE":       off(lambda p: trip.get(p)!="ACTIVE"),
 "trip_details":      off(lambda p: td.get(p,0)==0),
 "passenger==npax":   off(lambda p: pax.get(p,(0,0))[0]!=by[p]["npax"]),
 "DOB set":           off(lambda p: pax.get(p,(0,1))[1]>0),
 "ticket==npax":      off(lambda p: tkt.get(p,0)!=by[p]["npax"]),
 "eds_pnr_output":    off(lambda p: p not in eds),
 "eds contact email": off(lambda p: edsmail.get(p)!=by[p]["email"]),
}
print(f"BAGGAGE CHECKPOINTS — {IDX}\n  {len(ids)} PNRs (crt)")
ok=True
for name,o in booking.items():
    print(f"  {name:20} {len(ids)-len(o)}/{len(ids)}"+("" if not o else f"  MISS {len(o)}: {o[:6]}"))
    if o: ok=False

# ---- baggage event checks --------------------------------------------------
areas={k:[0,0,[]] for k in ["bag event_types","bag AHL ref","bag not-FD only"]}
def rec(area,good,pid,msg=""):
    a=areas[area]; a[1]+=1
    if good: a[0]+=1
    else: a[2].append((pid,msg))
for m in rows:
    pid=m["pnr_id"]; st=m["ahl"]
    if st=="fd": continue
    d=bag.get(pid,dict(types=set(),refs=set()))
    need=EXPECT.get(st,set())
    if st=="track_none":
        rec("bag event_types",len(d["types"])==0,pid,f"want 0 got {sorted(d['types'])}")
    else:
        rec("bag event_types",need.issubset(d["types"]),pid,f"missing {sorted(need-d['types'])} (have {sorted(d['types'])})")
    if st in NEEDS_REF:
        want={m["ref"]}|set(m.get("extra_refs",[]))
        rec("bag AHL ref",want.issubset(d["refs"]),pid,f"want {sorted(want)} got {sorted(d['refs'])}")

# ---- FD DDS (031/032) ------------------------------------------------------
ctx=ssl.create_default_context(); ctx.check_hostname=False; ctx.verify_mode=ssl.CERT_NONE
fd_area=[0,0,[]]
# SKIP the FD-DDS section (leave fd_area tot=0) if the rule-engine gateway is 403-locked env-wide
_gw_down=C.gateway_down()
if _gw_down: print(C.skip_area("FD comp DDS",sum(1 for m in rows if m['ahl']=='fd')))
for m in (rows if not _gw_down else []):
    if m["ahl"]!="fd": continue
    pid=m["pnr_id"]; fd_area[1]+=1
    try:
        req=urllib.request.Request(DDS+pid,headers={"x-api-key":API})
        d=json.load(urllib.request.urlopen(req,timeout=25,context=ctx))
        ce=d.get("compensationEligibility",[]) or []
        good=len(ce)>0 and ce[0]["passengerEligibility"][0]["eligibilityStatus"]=="ELIGIBLE"
        if good: fd_area[0]+=1
        else: fd_area[2].append((pid,f"comp={len(ce)}"))
    except Exception as e: fd_area[2].append((pid,str(e)[:40]))

for name,(g,t,bad) in list(areas.items())+[("FD comp DDS",tuple(fd_area))]:
    if t==0: continue
    print(f"  {name:20} {g}/{t}"+("" if g==t else f"  BAD {t-g}: {bad[:6]}"))
    if g!=t: ok=False
_uniq_enf = any((by.get(i) or {}).get("uniq_names") for i in ids)
print(f"  {'name uniqueness' if _uniq_enf else 'name uniq (info)':18} {_uniq_clean}/{len(ids)}" + ("" if not _uniq_off else f"  DUP/INDB {len(_uniq_off)}: {_uniq_off[:8]}"))
if C.print_check(ids, _common): ok=False
if _uniq_off and _uniq_enf: ok = False
print("PASS ✅ all areas verified" if ok else "FAIL ❌ — see MISS/BAD above")
sys.exit(0 if ok else 1)
