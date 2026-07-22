import boto3, json, time
cp=boto3.Session(profile_name="cce-developer-int",region_name="ca-central-1").client("customer-profiles")
DOM="ac-cct-int"
FD=f"{KB}/scenarios/fd-sit"
recs=[]
for f in ("_FD_WALLET6_lahiru_set45_index.json","_FD_WALLET30_lahiru_index.json"):
    recs+= [r for r in json.load(open(f"{FD}/{f}")) if r["wallet"]]
print(f"{len(recs)} wallet PNRs to fix")
_objcache={}
def profile_objects(prid):
    if prid not in _objcache:
        out=[]; tok=None
        while True:
            kw=dict(DomainName=DOM,ObjectTypeName="PNRBooking",ProfileId=prid,MaxResults=100)
            if tok: kw["NextToken"]=tok
            r=cp.list_profile_objects(**kw)
            out+=r["Items"]; tok=r.get("NextToken")
            if not tok: break
        _objcache[prid]=out
    return _objcache[prid]
fixed=0; miss=[]
for rec in recs:
    pid=rec["pnr_id"]; mems=rec["memberships"]; done={}
    profs=cp.search_profiles(DomainName=DOM,KeyName="PNRId",Values=[pid],MaxResults=20)["Items"]
    for pr in profs:
        for o in profile_objects(pr["ProfileId"]):
            b=json.loads(o["Object"])
            if b.get("PNRId")!=pid or b["TravelerId"] in done: continue
            n=int(b["TravelerId"].rsplit("-PT-",1)[1])
            if n>len(mems): continue
            if b.get("LoyaltyMembershipId")==mems[n-1]: done[b["TravelerId"]]="already"; continue
            b["LoyaltyMembershipId"]=mems[n-1]; b["LoyaltyProgramName"]="Aeroplan"
            cp.put_profile_object(DomainName=DOM,ObjectTypeName="PNRBooking",Object=json.dumps(b))
            done[b["TravelerId"]]=mems[n-1]; fixed+=1
    if len(done)!=rec["npax"]:
        miss.append((pid,rec["npax"],dict(done)))
    print(f"  {pid}: {len(done)}/{rec['npax']} travelers -> {done}",flush=True)
print(f"\nput {fixed} objects; incomplete: {len(miss)}")
for m in miss: print("  MISS",m)
# ---- verify pass (fresh reads, no cache) ----
print("\nVERIFY after 10s...")
time.sleep(10); _objcache.clear(); bad=[]
for rec in recs:
    pid=rec["pnr_id"]; mems=rec["memberships"]; got={}
    for pr in cp.search_profiles(DomainName=DOM,KeyName="PNRId",Values=[pid],MaxResults=20)["Items"]:
        for o in profile_objects(pr["ProfileId"]):
            b=json.loads(o["Object"])
            if b.get("PNRId")==pid: got[b["TravelerId"]]=b.get("LoyaltyMembershipId")
    exp={f"{pid}-PT-{n}":mems[n-1] for n in range(1,rec["npax"]+1)}
    ok = all(got.get(k)==v for k,v in exp.items())
    if not ok: bad.append((pid,exp,got))
    print(f"  {pid}: {'OK' if ok else 'BAD '+str(got)}",flush=True)
print(f"\nCP LOYALTY FIX {'PASS' if not bad else 'FAIL'} — {len(recs)-len(bad)}/{len(recs)} wallet PNRs correct")
