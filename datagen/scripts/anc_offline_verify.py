#!/usr/bin/env python3
import os
"""Ancillaries OFFLINE DDS verifier — validates the SEEDED seat/bag eligibility straight from the
pinned S3 response.json (via execution_traces.response_s3_key), bypassing the live rule-engine
gateway. Use when anc_checkpoints reports the gateway 403/unreachable: the booking-side areas still
verify live against trip-tracer, and THIS proves the eligibility data is correct + the pin actually
resolves to the right S3 object. Runs the same DDS field checks the live checkpoint runs.

Usage: AWS_PROFILE=ac-cct-crt python3 anc_offline_verify.py <index.json>
"""
import json, sys, datetime
import boto3, psycopg2

IDX=sys.argv[1]
rows=json.load(open(IDX)); ids=[m["pnr_id"] for m in rows]; by={m["pnr_id"]:m for m in rows}
RE=dict(host="ac-cct-rule-engine-crt-cac1-rds-cluster-instance1.cxqe2wacy866.ca-central-1.rds.amazonaws.com",
        db="postgres",user="dbadmin",password=os.environ.get("CCT_RULEENGINE_PASSWORD", ""))
BUCKET="cct-ask-ac-crt-logs"; CORR="qa-anc-crt"
TODAY=datetime.date.today()
s3=boto3.client("s3")

# latest pinned response_s3_key per entity (mirrors the endpoint's ORDER BY processed_at DESC)
c=psycopg2.connect(host=RE["host"],dbname=RE["db"],user=RE["user"],password=RE["password"],connect_timeout=20)
cur=c.cursor()
cur.execute("""select distinct on (entity_id) entity_id, response_s3_key
               from execution_traces where service_type='DDS' and correlation_id=%s and entity_id=any(%s)
               order by entity_id, processed_at desc""",(CORR,ids))
key_of=dict(cur.fetchall()); c.close()

def prefix(e): return e[:3]
areas={k:[0,0,[]] for k in
       ["pin present","seat rowcount","seat systemCode","emdCouponStatus","seat prefix","charChanged",
        "seat amount","seat fop","bag segcount+AHL","bag pecount","bag systemCode","bag prefix","bag amount",
        "bag fop","NE reason text","AHL age vs wait"]}
def rec(a,good,pid,msg=""):
    x=areas[a]; x[1]+=1
    if good: x[0]+=1
    else: x[2].append((pid,msg))

def expected_seat(m): return [sp for seg in m["seat"] for sp in seg]

for m in rows:
    pid=m["pnr_id"]
    # some cases deliberately have NO DDS pin (e.g. ANC-ANB-09 "no DDS eligibility data") — skip them
    if m.get("pin") is False: continue
    key=key_of.get(pid)
    rec("pin present",bool(key),pid,"no execution_traces pin")
    if not key: continue
    try: d=json.loads(s3.get_object(Bucket=BUCKET,Key=key)["Body"].read())
    except Exception as e: rec("pin present",False,pid,f"S3 fetch {str(e)[:30]}"); continue
    if m["suite"]=="seat":
        got=d.get("seatFeeRefundEligibility",[]) or []
        if m["note"]=="no_emd": rec("seat rowcount",len(got)==0,pid,f"rows={len(got)} want0"); continue
        exp=expected_seat(m); n=min(len(got),len(exp))
        rec("seat rowcount",len(got)==len(exp),pid,f"got{len(got)} exp{len(exp)}")
        rec("seat systemCode",len(got)==len(exp) and all(got[i]["systemCode"]==exp[i]["syscode"] for i in range(n)),pid)
        rec("emdCouponStatus",all(got[i]["emdCouponStatus"]==exp[i]["coupon"] for i in range(n)),pid)
        rec("seat prefix",all(prefix(got[i]["emdNumber"])==exp[i]["emd"] for i in range(n)),pid)
        rec("charChanged",all(got[i]["hasSeatCharacteristicsChanged"]==exp[i]["char"] for i in range(n)),pid)
        rec("seat amount",all(got[i]["amount"]==exp[i]["amount"] for i in range(n)),pid)
        rec("seat fop",all(got[i]["fopCode"]==exp[i]["fop"] for i in range(n)),pid)
        for rw in got:
            if rw["eligibilityStatus"]=="NOT_ELIGIBLE": rec("NE reason text",bool((rw.get("reason") or "").strip()),pid)
    else:
        got=d.get("baggageRefundEligibility",[]) or []; exp=m["bag"]
        if m["note"]=="no_emd":
            rec("bag pecount",sum(len(s.get("passengerEligibility",[])) for s in got)==0,pid); continue
        segok=len(got)==len(exp)
        for j,(ahl,pr) in enumerate(exp):
            if j<len(got): segok=segok and got[j]["isAHLPresent"]==ahl["isAHL"] and got[j]["reportType"]==ahl["reportType"]
        rec("bag segcount+AHL",segok,pid)
        for j,(ahl,pr) in enumerate(exp):
            if j>=len(got): rec("bag pecount",False,pid,f"missing seg{j}"); continue
            pe=got[j].get("passengerEligibility",[]); n=min(len(pe),len(pr))
            rec("bag pecount",len(pe)==len(pr),pid)
            rec("bag systemCode",len(pe)==len(pr) and all(pe[k]["systemCode"]==pr[k]["syscode"] for k in range(n)),pid)
            rec("bag prefix",all(prefix(pe[k]["emdNumber"])==pr[k]["emd"] for k in range(n)),pid)
            rec("bag amount",all(pe[k]["amount"]==pr[k]["amount"] for k in range(n)),pid)
            rec("bag fop",all(pe[k]["fopCode"]==pr[k]["fop"] for k in range(n)),pid)
            for rw in pe:
                if rw["eligibilityStatus"]=="NOT_ELIGIBLE": rec("NE reason text",bool((rw.get("reason") or "").strip()),pid)
            w=got[j].get("waitPeriodSatisfied")
            if w is not None and got[j].get("isAHLPresent"):
                try:
                    age_h=(datetime.datetime.now(datetime.timezone.utc)-datetime.datetime.fromisoformat(
                           got[j]["ahlCreationDate"].replace("Z","+00:00"))).total_seconds()/3600
                    rec("AHL age vs wait",(age_h>=72) if w else (0<=age_h<72),pid,f"wait={w} AHL {age_h:.0f}h")
                except Exception: rec("AHL age vs wait",False,pid,"bad ahlCreationDate")

print(f"ANC OFFLINE DDS VERIFY (from pinned S3) — {IDX}\n  {len(ids)} PNRs")
ok=True
for name,(g,t,bad) in areas.items():
    if t==0: continue
    print(f"  {name:20} {g}/{t}"+("" if g==t else f"  BAD {t-g}: {bad[:6]}"))
    if g!=t: ok=False
print("PASS ✅ seeded eligibility data verified from S3" if ok else "FAIL ❌")
sys.exit(0 if ok else 1)
