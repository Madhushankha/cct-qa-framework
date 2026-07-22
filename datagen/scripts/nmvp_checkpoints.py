#!/usr/bin/env python3
"""NON-MVP PNR post-creation CHECKPOINTS (CRT).

Non-MVP is NON-AUTOMATED — there is no pinned DDS and no eligibility endpoint. The ONLY
verification surface is the trip-tracer cascade the chatbot relies on to retrieve the
booking, send OTP, and drive journey/segment selection for MANUAL Claims-Dashboard case
creation. Checks per PNR:
   1. trip ACTIVE            (exactly one ACTIVE trip for the locator)
   2. passenger count == npax
   3. date_of_birth set on every passenger
   4. ticket present (== npax)
   5. eds_pnr_output present
   6. eds contact email == index email  (authenticationContactDetails…apn.email) -> OTP-PNR
   7. eds contact phone == index phone  (…apn.phone/number)                       -> OTP-PNR
   8. flight_segment present (>=1)       -> journey/segment selection
   9. marketing carrier set == design    (all AC)
  10. itinerary geography matches design (origin/destination of every leg) -> US/China/EU routing
  11. travel-state matches design        (POST=departed before today; FUT=departs after today)

Invoke: AWS_PROFILE=ac-cct-crt python3 nmvp_checkpoints.py
"""
import json, sys, datetime
import nmvp_crt_build as B
import crt_uniqnames as U
import pnr_common_checks as C

rows=B.load_index(); ids=[r["pnr_id"] for r in rows]; by={r["pnr_id"]:r for r in rows}
locs=[r["pnr"] for r in rows]
TODAY=datetime.datetime.now(datetime.timezone.utc).date()
cn=B.tt_conn(); cur=cn.cursor()

def col(q,p): cur.execute(q,p); return cur.fetchall()
active={loc:c for loc,c in col("SELECT pnr,count(*) FILTER (WHERE status='ACTIVE') FROM trip WHERE pnr=ANY(%s) GROUP BY pnr",(locs,))}
tripstat={r[0]:r[1] for r in col("SELECT pnr_id,status FROM trip WHERE pnr_id=ANY(%s)",(ids,))}
cur.execute("SELECT pnr_id,count(*),count(*) FILTER (WHERE date_of_birth IS NULL) FROM passenger WHERE pnr_id=ANY(%s) AND NOT is_removed GROUP BY pnr_id",(ids,))
pax={r[0]:(r[1],r[2]) for r in cur.fetchall()}
_uniq_clean, _uniq_off = U.name_uniqueness(cur, ids)
_common = C.collect(cur, ids, rows)   # shared: ticket linkage + eds auth == pax
tkt={r[0]:r[1] for r in col("SELECT pnr_id,count(*) FROM ticket WHERE pnr_id=ANY(%s) GROUP BY pnr_id",(ids,))}
cur.execute("SELECT DISTINCT ON (pnr_id) pnr_id,bounds FROM eds_pnr_output WHERE pnr_id=ANY(%s) ORDER BY pnr_id,received_at DESC",(ids,))
eds={}; edsmail={}; edsphone={}
for pid,b in cur.fetchall():
    eds[pid]=1
    try:
        bb=json.loads(b) if isinstance(b,str) else b
        apn=bb[0]["authenticationContactDetails"]["passengers"][0]["contacts"]["apn"]
        edsmail[pid]=apn.get("email")
        ph=apn.get("phone") or apn.get("number") or apn.get("phoneNumber")
        if isinstance(ph,dict): ph=ph.get("number") or ph.get("phoneNumber")
        edsphone[pid]=ph
    except Exception: edsmail[pid]=None; edsphone[pid]=None
segcnt={}; segmkts={}; segod={}
for pid,cnt,mkts in col("SELECT pnr_id,count(*),array_agg(DISTINCT marketing_carrier_code) FROM flight_segment WHERE pnr_id=ANY(%s) AND NOT is_removed GROUP BY pnr_id",(ids,)):
    segcnt[pid]=cnt; segmkts[pid]=set(mkts)
for pid,ods in col("SELECT pnr_id,array_agg(departure_airport||'-'||arrival_airport ORDER BY departure_airport) FROM flight_segment WHERE pnr_id=ANY(%s) AND NOT is_removed GROUP BY pnr_id",(ids,)):
    segod[pid]=set(ods)
depdates={}
for pid,mn,mx in col("SELECT pnr_id,min(departure_datetime),max(departure_datetime) FROM flight_segment WHERE pnr_id=ANY(%s) AND NOT is_removed GROUP BY pnr_id",(ids,)):
    depdates[pid]=(mn,mx)
cur.close(); cn.close()

def _depdate(pid):
    d=depdates.get(pid,(None,None))[0]
    if d is None: return None
    return d.date() if hasattr(d,"date") else datetime.date.fromisoformat(str(d)[:10])

def design_od(r): return {f"{o}-{d}" for o,d in r["legs"]}
def state_ok(pid):
    dd=_depdate(pid)
    if dd is None: return False
    return (dd<TODAY) if by[pid]["state"]=="POST" else (dd>TODAY)

def off(pred): return [by[p]["pnr"] for p in ids if pred(p)]
checks={
 "trip ACTIVE (1/loc)":   off(lambda p: tripstat.get(p)!="ACTIVE" or active.get(by[p]["pnr"],0)!=1),
 "passenger==npax":       off(lambda p: pax.get(p,(0,0))[0]!=by[p]["npax"]),
 "DOB set":               off(lambda p: pax.get(p,(0,1))[1]>0),
 "ticket==npax":          off(lambda p: tkt.get(p,0)!=by[p]["npax"]),
 "eds_pnr_output":        off(lambda p: p not in eds),
 "eds contact email":     off(lambda p: edsmail.get(p)!=by[p]["email"]),
 "eds contact phone":     off(lambda p: (edsphone.get(p) or "").replace(" ","")!=by[p]["phone"].replace(" ","")),
 "flight_segment >=1":    off(lambda p: segcnt.get(p,0)<1),
 "marketing carrier=AC":  off(lambda p: segmkts.get(p)!={"AC"}),
 "itinerary geography":   off(lambda p: segod.get(p)!=design_od(by[p])),
 "travel-state":          off(lambda p: not state_ok(p)),
}
print(f"NON-MVP CHECKPOINTS — {len(ids)} PNRs (CRT) — trip-tracer cascade (retrieval + OTP + journey/segment)")
ok=True
for name,offx in checks.items():
    n=len(ids)-len(offx); print(f"  {name:24} {n}/{len(ids)}"+("" if not offx else f"  MISS {len(offx)}: {offx[:8]}"))
    if offx: ok=False
_uniq_enf = any((by.get(i) or {}).get("uniq_names") for i in ids)
print(f"  {'name uniqueness' if _uniq_enf else 'name uniq (info)':18} {_uniq_clean}/{len(ids)}" + ("" if not _uniq_off else f"  DUP/INDB {len(_uniq_off)}: {_uniq_off[:8]}"))
if C.print_check(ids, _common): ok=False
if _uniq_off and _uniq_enf: ok = False
print("PASS ✅ all areas" if ok else "FAIL ❌ — see MISS above")
sys.exit(0 if ok else 1)
