"""Patient CP loyalty reconciler for today's wallet sets (set6/7/8 + setB + setC).
Every 5 min: verify all wallet travelers' PNRBooking.LoyaltyMembershipId; re-seed any
reverted/missing. Success = 2 consecutive clean rounds (nothing to re-seed, all visible).
Hard stop after 2h."""
import boto3, json, time, sys
cp=boto3.Session(profile_name="cce-developer-int",region_name="ca-central-1").client("customer-profiles")
DOM="ac-cct-int"
FD=f"{KB}/scenarios/fd-sit"
recs=[]
for f in ("_FD_WALLET9_lahiru_set678_index.json","_FD_WALLET30B_lahiru_index.json","_FD_WALLET30C_lahiru_index.json"):
    recs+=[r for r in json.load(open(f"{FD}/{f}")) if r["wallet"]]
print(f"reconciling {len(recs)} wallet PNRs ({sum(r['npax'] for r in recs)} travelers)",flush=True)
def objs(prid):
    out=[]; tok=None
    while True:
        kw=dict(DomainName=DOM,ObjectTypeName="PNRBooking",ProfileId=prid,MaxResults=100)
        if tok: kw["NextToken"]=tok
        r=cp.list_profile_objects(**kw); out+=r["Items"]; tok=r.get("NextToken")
        if not tok: break
    return out
clean=0; t0=time.time()
rnd=0
while time.time()-t0 < 7200:
    rnd+=1; cache={}; put=0; missing=0
    for rec in recs:
        pid=rec["pnr_id"]; mems=rec["memberships"]; seen={}
        for pr in cp.search_profiles(DomainName=DOM,KeyName="PNRId",Values=[pid],MaxResults=20)["Items"]:
            if pr["ProfileId"] not in cache: cache[pr["ProfileId"]]=objs(pr["ProfileId"])
            for o in cache[pr["ProfileId"]]:
                b=json.loads(o["Object"])
                if b.get("PNRId")!=pid or b["TravelerId"] in seen: continue
                n=int(b["TravelerId"].rsplit("-PT-",1)[1])
                if n>len(mems): continue
                if b.get("LoyaltyMembershipId")!=mems[n-1]:
                    b["LoyaltyMembershipId"]=mems[n-1]; b["LoyaltyProgramName"]="Aeroplan"
                    cp.put_profile_object(DomainName=DOM,ObjectTypeName="PNRBooking",Object=json.dumps(b))
                    put+=1
                seen[b["TravelerId"]]=1
        missing+=max(0,rec["npax"]-len(seen))
    stat="CLEAN" if (put==0 and missing==0) else f"re-put {put}, objects-missing {missing}"
    print(f"round {rnd} ({int(time.time()-t0)}s): {stat}",flush=True)
    clean = clean+1 if (put==0 and missing==0) else 0
    if clean>=2:
        print("RECONCILED — stable across 2 consecutive rounds. CP SEED FINAL PASS",flush=True); sys.exit(0)
    time.sleep(300)
print("TIMEOUT after 2h — still churning; needs investigation",flush=True); sys.exit(1)
