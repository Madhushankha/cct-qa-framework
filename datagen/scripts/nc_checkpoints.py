#!/usr/bin/env python3
"""NAME CORRECTION PNR post-creation CHECKPOINTS (CRT) — verify every area the bot needs.

Two verification surfaces (Name Correction has no pinned DDS; eligibility is computed
live and statelessly):
  A. trip-tracer cascade — the chatbot RETRIEVES the PNR + sends OTP from these:
       1. trip ACTIVE            (exactly one ACTIVE trip for the locator)
       2. passenger count == npax
       3. date_of_birth set
       4. ticket present (== npax)
       5. eds_pnr_output present
       6. eds contact email == index email (authenticationContactDetails…apn.email)
       7. cascade fidelity: flight_segment.marketing_carrier_code matches design (seg1),
          passenger_type patched for YTH cases
  B. eligibility endpoint — POST each case's designed pnrData to
       /eligibility-service/execute-with-mapping and assert
       isPnrEligible / processingWindow / reasonCode == expected.

Invoke: AWS_PROFILE=ac-cct-crt python3 nc_checkpoints.py
Reuses the payload builder + endpoint caller from nc_crt_build.py.
"""
import json, sys, datetime
import psycopg2
import nc_crt_build as B
import crt_uniqnames as U
import pnr_common_checks as C

rows=B.load_index(); ids=[r["pnr_id"] for r in rows]; by={r["pnr_id"]:r for r in rows}
locs=[r["pnr"] for r in rows]
cn=B.tt_conn(); cur=cn.cursor()

def col(q,p): cur.execute(q,p); return cur.fetchall()
# one ACTIVE trip per locator?
active={}
for loc,c in col("SELECT pnr,count(*) FILTER (WHERE status='ACTIVE') FROM trip WHERE pnr=ANY(%s) GROUP BY pnr",(locs,)):
    active[loc]=c
tripstat={r[0]:r[1] for r in col("SELECT pnr_id,status FROM trip WHERE pnr_id=ANY(%s)",(ids,))}
cur.execute("SELECT pnr_id,count(*),count(*) FILTER (WHERE date_of_birth IS NULL) FROM passenger WHERE pnr_id=ANY(%s) AND NOT is_removed GROUP BY pnr_id",(ids,))
pax={r[0]:(r[1],r[2]) for r in cur.fetchall()}
_uniq_clean, _uniq_off = U.name_uniqueness(cur, ids)
_common = C.collect(cur, ids, rows)   # shared: ticket linkage + eds auth == pax
tkt={r[0]:r[1] for r in col("SELECT pnr_id,count(*) FROM ticket WHERE pnr_id=ANY(%s) GROUP BY pnr_id",(ids,))}
cur.execute("SELECT DISTINCT ON (pnr_id) pnr_id,bounds FROM eds_pnr_output WHERE pnr_id=ANY(%s) ORDER BY pnr_id,received_at DESC",(ids,))
eds={}; edsmail={}
for pid,b in cur.fetchall():
    eds[pid]=1
    try:
        bb=json.loads(b) if isinstance(b,str) else b
        edsmail[pid]=bb[0]["authenticationContactDetails"]["passengers"][0]["contacts"]["apn"].get("email")
    except Exception: edsmail[pid]=None
segmkts={}
for pid,mkts in col("SELECT pnr_id,array_agg(DISTINCT marketing_carrier_code) FROM flight_segment WHERE pnr_id=ANY(%s) AND NOT is_removed GROUP BY pnr_id",(ids,)):
    segmkts[pid]=set(mkts)
ptypes={}
for pid,pt in col("SELECT pnr_id,array_agg(passenger_type) FROM passenger WHERE pnr_id=ANY(%s) AND NOT is_removed GROUP BY pnr_id",(ids,)):
    ptypes[pid]=pt
cur.close(); cn.close()

def off(pred): return [by[p]["pnr"] for p in ids if pred(p)]
checks={
 "trip ACTIVE (1/loc)": off(lambda p: tripstat.get(p)!="ACTIVE" or active.get(by[p]["pnr"],0)!=1),
 "passenger==npax":     off(lambda p: pax.get(p,(0,0))[0]!=by[p]["npax"]),
 "DOB set":             off(lambda p: pax.get(p,(0,1))[1]>0),
 "ticket==npax":        off(lambda p: tkt.get(p,0)!=by[p]["npax"]),
 "eds_pnr_output":      off(lambda p: p not in eds),
 "eds contact email":   off(lambda p: edsmail.get(p)!=by[p]["email"]),
 "marketing carrier set": off(lambda p: segmkts.get(p)!=set(mkt for _,mkt in by[p]["carriers"])),
 "YTH type patched":    off(lambda p: any(x[2]=="YTH" for x in by[p]["paxs"]) and "YTH" not in (ptypes.get(p) or [])),
}
print(f"NAME CORRECTION CHECKPOINTS — {len(ids)} PNRs (CRT)")
ok=True
print("--- A. trip-tracer cascade (retrieval + OTP) ---")
for name,offx in checks.items():
    n=len(ids)-len(offx); print(f"  {name:24} {n}/{len(ids)}"+("" if not offx else f"  MISS {len(offx)}: {offx[:8]}"))
    if offx: ok=False
# B. eligibility endpoint — SKIP gracefully if the rule-engine gateway is 403-locked env-wide
print("--- B. eligibility endpoint (execute-with-mapping) ---")
if C.gateway_down():
    print(C.skip_area("eligibility outcome", len(rows)))
else:
    elig_ok=0; bad=[]
    for r in rows:
        good,g=B.verify_one(r)
        if good: elig_ok+=1
        else: bad.append((r["pnr"],f"exp {r['exp_elig']}/{r['exp_win']}/{r['exp_reason']} got {g.get('elig')}/{g.get('win')}/{g.get('reason')}"))
    print(f"  eligibility outcome      {elig_ok}/{len(rows)}"+("" if not bad else f"  BAD {len(bad)}: {bad[:6]}"))
    if bad: ok=False
_uniq_enf = any((by.get(i) or {}).get("uniq_names") for i in ids)
print(f"  {'name uniqueness' if _uniq_enf else 'name uniq (info)':18} {_uniq_clean}/{len(ids)}" + ("" if not _uniq_off else f"  DUP/INDB {len(_uniq_off)}: {_uniq_off[:8]}"))
if C.print_check(ids, _common): ok=False
if _uniq_off and _uniq_enf: ok = False
print("PASS ✅ all areas" if ok else "FAIL ❌ — see MISS/BAD above")
sys.exit(0 if ok else 1)
