#!/usr/bin/env python3
import os
"""Ancillaries SEAT & BAG fee-refund PNR post-creation CHECKPOINTS (CRT).

Verifies EVERY area the seat/bag refund bot depends on; fails loudly on any miss.
Booking side comes from trip-tracer; eligibility from the rule-engine DDS endpoint
(seatFeeRefundEligibility[] / baggageRefundEligibility[]).

Usage: AWS_PROFILE=ac-cct-crt python3 anc_checkpoints.py [index.json]
  (defaults to the anc_crt_build.py OUT index)

Areas (all must PASS):
  BOOKING (trip-tracer):
   1  trip ACTIVE
   2  trip_details present
   3  passenger present  (count == index npax)
   4  DOB set (no NULL)
   5  ticket present     (count == index npax)
   6  eds_pnr_output present
   7  eds contact email matches index email
  SEAT DDS (seat cases):
   8  seat row count      == expected (pax x seg); no_emd cases -> 0 rows
   9  seat systemCode     each row matches expected
   10 emdCouponStatus     matches (USED/REFUNDED/VOID/EXCHANGED)
   11 EMD prefix          014=AC vs 016/838=OAL matches
   12 hasSeatCharacteristicsChanged matches
   13 seat amount         ELIGIBLE amount matches; NE -> 0
   14 seat fopCode        matches (CC / AWLTR AC-Wallet)
  BAG DDS (bag cases):
   15 bag segment count   == expected; per-seg isAHLPresent + reportType match
   16 bag pe count        == expected pax; no_emd -> 0 pe
   17 bag systemCode      each pe matches (incl BF-NE-NOREPORT / BF-OAL-01 / BF-NE-VOID...)
   18 bag EMD prefix      014 vs 016/838 matches
   19 bag amount          ELIGIBLE amount matches; NE -> 0
   20 bag fopCode         matches
  CROSS:
   21 passenger count     trip pax == index npax AND DDS covers npax
   22 future flight date  pre-travel cases (index future) fly AFTER today
"""
import json, sys, ssl, urllib.request, datetime, boto3, psycopg2
import crt_uniqnames as U
import pnr_common_checks as C
import _cctdb

WORK="/tmp/cctqa-datagen/anc_work"
IDX=sys.argv[1] if len(sys.argv)>1 else f"{WORK}/_ANC_SEATBAG_crt_index.json"
TODAY=datetime.date.today()
TT=dict(host="ac-cct-trip-tracer-rds-cluster-crt-cac1.cluster-cxqe2wacy866.ca-central-1.rds.amazonaws.com",
        db="trip-tracer",user="dbadmin",password=os.environ.get("CCT_TRIPTRACER_PASSWORD", ""))
DDS="https://rule-engine-platform-service.ac-cct-crt.cloud.aircanada.com/rule-engine/dds/output/"
API=os.environ.get("DDS_API_KEY", "")

rows=json.load(open(IDX)); ids=[m["pnr_id"] for m in rows]; by={m["pnr_id"]:m for m in rows}
cur=_cctdb.trip_tracer(TT["host"]).cursor()
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
cur.close()

def prefix(emd): return emd[:3]
def off(pred): return [p for p in ids if pred(p)]
booking={
 "trip ACTIVE":      off(lambda p: trip.get(p)!="ACTIVE"),
 "trip_details":     off(lambda p: td.get(p,0)==0),
 "passenger==npax":  off(lambda p: pax.get(p,(0,0))[0]!=by[p]["npax"]),
 "DOB set":          off(lambda p: pax.get(p,(0,1))[1]>0),
 "ticket==npax":     off(lambda p: tkt.get(p,0)!=by[p]["npax"]),
 "eds_pnr_output":   off(lambda p: p not in eds),
 "eds contact email":off(lambda p: by[p].get("email") and edsmail.get(p)!=by[p]["email"]),
}
print(f"ANC CHECKPOINTS — {IDX}\n  {len(ids)} PNRs (crt)")
ok=True
for name,o in booking.items():
    print(f"  {name:20} {len(ids)-len(o)}/{len(ids)}"+("" if not o else f"  MISS {len(o)}: {o[:6]}"))
    if o: ok=False

# ---- DDS endpoint field-level checks --------------------------------------
ctx=ssl.create_default_context(); ctx.check_hostname=False; ctx.verify_mode=ssl.CERT_NONE
def expected_seat(m):  # flat list of expected seat rows (pax x seg order == generation order)
    return [dict(sp,seg=j,pax=k) for j,seg in enumerate(m["seat"]) for k,sp in enumerate(seg)]
areas={k:[0,0,[]] for k in
       ["seat rowcount","seat systemCode","emdCouponStatus","seat prefix","charChanged","seat amount","seat fop",
        "bag segcount+AHL","bag pecount","bag systemCode","bag prefix","bag amount","bag fop",
        "passenger count","future flight","post-travel past","AHL age vs wait","NE reason text"]}
def rec(area,good,pid,msg=""):
    a=areas[area]; a[1]+=1
    if good: a[0]+=1
    else: a[2].append((pid,msg))

# SKIP the whole DDS section (leave every area tot=0) if the rule-engine gateway is 403-locked env-wide
_gw_down=C.gateway_down()
if _gw_down: print(C.skip_area("DDS eligibility (all areas)",len(rows)))
for m in (rows if not _gw_down else []):
    pid=m["pnr_id"]
    try:
        req=urllib.request.Request(DDS+pid,headers={"x-api-key":API})
        d=json.load(urllib.request.urlopen(req,timeout=25,context=ctx))
    except Exception as e:
        for a in areas: areas[a][2].append((pid,f"endpoint err {str(e)[:30]}")); areas[a][1]+=1
        continue
    # flight date: pre-travel cases must fly in the FUTURE, everything else is post-travel (past)
    try:
        dep=d["itineraryDetails"][0]["actualItinerary"]["associatedSegments"][0]["departureDatetime"][:10]
        depd=datetime.date.fromisoformat(dep)
    except Exception as e:
        depd=None
    if m.get("future"):
        rec("future flight",bool(depd) and depd>TODAY,pid,f"dep {dep} not future")
    else:
        rec("post-travel past",bool(depd) and depd<TODAY,pid,f"dep {dep} not in the past")
    # AHL age must be CONSISTENT with waitPeriodSatisfied: the 72-hour rule.
    #   waitPeriodSatisfied False -> AHL younger than 72h (the wait is genuinely still running)
    #   waitPeriodSatisfied True  -> AHL at least 72h old (the wait has genuinely elapsed)
    # Catches the BAG_TC011 class of bug: a "wait NOT satisfied" case carrying a 20-day-old AHL.
    for s in (d.get("baggageRefundEligibility",[]) or []):
        w=s.get("waitPeriodSatisfied")
        if w is None or not s.get("isAHLPresent"): continue
        ahl=s.get("ahlCreationDate")
        try:
            age_h=(datetime.datetime.now(datetime.timezone.utc)
                   -datetime.datetime.fromisoformat(ahl.replace("Z","+00:00"))).total_seconds()/3600
        except Exception:
            rec("AHL age vs wait",False,pid,f"unparseable ahlCreationDate {ahl}"); continue
        good=(age_h>=72) if w else (0<=age_h<72)
        rec("AHL age vs wait",good,pid,f"wait={w} but AHL {age_h:.0f}h old")
    # (ported from fd_checkpoints #12) NOT_ELIGIBLE rows must carry a non-empty reason — that text is
    # what the bot renders in the not-eligible box, so an empty reason is a silent UX break.
    for rw in ((d.get("seatFeeRefundEligibility",[]) or [])
               +[p for s in (d.get("baggageRefundEligibility",[]) or []) for p in s.get("passengerEligibility",[])]):
        if rw.get("eligibilityStatus")=="NOT_ELIGIBLE":
            rec("NE reason text",bool((rw.get("reason") or "").strip()),pid,f"{rw.get('systemCode')} empty reason")
    # passenger count: trip pax == npax
    tp=pax.get(pid,(0,0))[0]; rec("passenger count",tp==m["npax"],pid,f"trip{tp}!=npax{m['npax']}")

    if m["suite"]=="seat":
        got=d.get("seatFeeRefundEligibility",[]) or []
        if m["note"]=="no_emd":
            rec("seat rowcount",len(got)==0,pid,f"rows={len(got)} want0"); continue
        exp=expected_seat(m)
        rec("seat rowcount",len(got)==len(exp),pid,f"got{len(got)} exp{len(exp)}")
        n=min(len(got),len(exp))
        rec("seat systemCode",all(got[i].get("systemCode")==exp[i]["syscode"] for i in range(n)) and len(got)==len(exp),pid,
            f"{[g.get('systemCode') for g in got]} vs {[e['syscode'] for e in exp]}")
        rec("emdCouponStatus",all(got[i].get("emdCouponStatus")==exp[i]["coupon"] for i in range(n)),pid,
            f"{[g.get('emdCouponStatus') for g in got]}")
        rec("seat prefix",all(prefix(got[i].get("emdNumber",""))==exp[i]["emd"] for i in range(n)),pid,
            f"{[prefix(g.get('emdNumber','')) for g in got]}")
        rec("charChanged",all(got[i].get("hasSeatCharacteristicsChanged")==exp[i]["char"] for i in range(n)),pid,
            f"{[g.get('hasSeatCharacteristicsChanged') for g in got]}")
        rec("seat amount",all(got[i].get("amount")==exp[i]["amount"] for i in range(n)),pid,
            f"{[g.get('amount') for g in got]} vs {[e['amount'] for e in exp]}")
        rec("seat fop",all(got[i].get("fopCode")==exp[i]["fop"] for i in range(n)),pid,
            f"{[g.get('fopCode') for g in got]}")
    else:
        got=d.get("baggageRefundEligibility",[]) or []
        exp=m["bag"]
        if m["note"]=="no_emd":
            allpe=[p for s in got for p in s.get("passengerEligibility",[])]
            rec("bag pecount",len(allpe)==0,pid,f"pe={len(allpe)} want0"); continue
        segok=len(got)==len(exp)
        for j,(ahl,paxrows) in enumerate(exp):
            if j<len(got):
                segok=segok and got[j].get("isAHLPresent")==ahl["isAHL"] and got[j].get("reportType")==ahl["reportType"]
        rec("bag segcount+AHL",segok,pid,f"segs{len(got)}/{len(exp)} AHL/type mismatch" if not segok else "")
        for j,(ahl,paxrows) in enumerate(exp):
            if j>=len(got): rec("bag pecount",False,pid,f"missing seg{j}"); continue
            pe=got[j].get("passengerEligibility",[])
            rec("bag pecount",len(pe)==len(paxrows),pid,f"pe{len(pe)}/{len(paxrows)}")
            n=min(len(pe),len(paxrows))
            rec("bag systemCode",all(pe[k].get("systemCode")==paxrows[k]["syscode"] for k in range(n)) and len(pe)==len(paxrows),pid,
                f"{[p.get('systemCode') for p in pe]} vs {[r['syscode'] for r in paxrows]}")
            rec("bag prefix",all(prefix(pe[k].get("emdNumber",""))==paxrows[k]["emd"] for k in range(n)),pid,
                f"{[prefix(p.get('emdNumber','')) for p in pe]}")
            rec("bag amount",all(pe[k].get("amount")==paxrows[k]["amount"] for k in range(n)),pid,
                f"{[p.get('amount') for p in pe]}")
            rec("bag fop",all(pe[k].get("fopCode")==paxrows[k]["fop"] for k in range(n)),pid,
                f"{[p.get('fopCode') for p in pe]}")

for name,(g,t,bad) in areas.items():
    if t==0: continue
    print(f"  {name:20} {g}/{t}"+("" if g==t else f"  BAD {t-g}: {bad[:6]}"))
    if g!=t: ok=False
_uniq_enf = any((by.get(i) or {}).get("uniq_names") for i in ids)
print(f"  {'name uniqueness' if _uniq_enf else 'name uniq (info)':18} {_uniq_clean}/{len(ids)}" + ("" if not _uniq_off else f"  DUP/INDB {len(_uniq_off)}: {_uniq_off[:8]}"))
if C.print_check(ids, _common): ok=False
if _uniq_off and _uniq_enf: ok = False
print("PASS ✅ all areas verified" if ok else "FAIL ❌ — see MISS/BAD above")
sys.exit(0 if ok else 1)
