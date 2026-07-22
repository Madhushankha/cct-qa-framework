#!/usr/bin/env python3
"""CP (Customer Profiles) loyalty write — ported from INT int_cp_wallet_loyalty_fix.py.
After walletfix injects loyaltyRequests into the PNR, the bot's CP lookup also needs the
Aeroplan membership written onto the customer-profiles PNRBooking object. This writes
LoyaltyMembershipId + LoyaltyProgramName='Aeroplan' into the BAT CP domain (ac-cct-bat) for
every index entry that carries a loyalty_id (the AC-Wallet cases FD_TC_002/019/022), per traveler.
Idempotent (skips objects already set) + verify pass. Usage: bat_fd_cpfix.py <set_index.json>"""
import sys, json, time, boto3
DOM="ac-cct-bat"
cp=boto3.Session(profile_name="CCE-Developer-BAT",region_name="ca-central-1").client("customer-profiles")
idxf=sys.argv[1]; idx=json.load(open(idxf))
recs=[r for r in idx if r.get("loyalty_id")]
print(f"{len(recs)} CP-loyalty PNRs to write (entries with loyalty_id): {[r['tc'] for r in recs]}")
_objcache={}
def profile_objects(prid):
    if prid not in _objcache:
        out=[]; tok=None
        while True:
            kw=dict(DomainName=DOM,ObjectTypeName="PNRBooking",ProfileId=prid,MaxResults=100)
            if tok: kw["NextToken"]=tok
            r=cp.list_profile_objects(**kw); out+=r["Items"]; tok=r.get("NextToken")
            if not tok: break
        _objcache[prid]=out
    return _objcache[prid]
fixed=0; miss=[]
for rec in recs:
    pid=rec["pnr_id"]; mem=rec["loyalty_id"]; npax=rec.get("npax") or 1; done={}
    profs=cp.search_profiles(DomainName=DOM,KeyName="PNRId",Values=[pid],MaxResults=20)["Items"]
    for pr in profs:
        for o in profile_objects(pr["ProfileId"]):
            b=json.loads(o["Object"])
            if b.get("PNRId")!=pid or b["TravelerId"] in done: continue
            if b.get("LoyaltyMembershipId")==mem and b.get("LoyaltyProgramName")=="Aeroplan":
                done[b["TravelerId"]]="already"; continue
            b["LoyaltyMembershipId"]=mem; b["LoyaltyProgramName"]="Aeroplan"
            cp.put_profile_object(DomainName=DOM,ObjectTypeName="PNRBooking",Object=json.dumps(b))
            done[b["TravelerId"]]=mem; fixed+=1
    if len(done)<npax: miss.append((pid,npax,dict(done)))
    print(f"  {pid} ({rec['tc']}): {len(done)}/{npax} travelers -> {done}",flush=True)
print(f"\nput {fixed} objects; incomplete: {len(miss)}")
for m in miss: print("  MISS",m)
print("\nVERIFY after 10s...")
time.sleep(10); _objcache.clear(); bad=[]
for rec in recs:
    pid=rec["pnr_id"]; mem=rec["loyalty_id"]; got={}
    for pr in cp.search_profiles(DomainName=DOM,KeyName="PNRId",Values=[pid],MaxResults=20)["Items"]:
        for o in profile_objects(pr["ProfileId"]):
            b=json.loads(o["Object"])
            if b.get("PNRId")==pid: got[b["TravelerId"]]=(b.get("LoyaltyMembershipId"),b.get("LoyaltyProgramName"))
    ok = any(v==(mem,"Aeroplan") for v in got.values())
    if not ok: bad.append((pid,mem,got))
    print(f"  {pid} ({rec['tc']}): {'OK' if ok else 'BAD '+str(got)}",flush=True)
print(f"\nCP LOYALTY WRITE {'PASS' if not bad else 'FAIL'} — {len(recs)-len(bad)}/{len(recs)} wallet PNRs have CP LoyaltyMembershipId")
