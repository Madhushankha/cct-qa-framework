#!/usr/bin/env python3
"""Give FD_PAY_TC_010 (High Value >=$9,000 CAD payment case) a high-value amount so it exercises
BSM high-value routing. Regenerates its DDS (amount 9500), overwrites the S3 object at its key,
updates the index amount. Usage: bat_fd_paytc010.py <set_index.json>"""
import sys, json, os
sys.path.insert(0,f"{KB}/scripts")
import bat_fd_build as bf
HIGH=9500
idxf=sys.argv[1]; idx=json.load(open(idxf))
r=next(x for x in idx if x["tc"]=="FD_PAY_TC_010"); pid=r["pnr_id"]
p=f"{bf.DDSW}/{pid}.dds.json"
if not os.path.exists(p): bf.clone_one(r, "payfix")
d=json.load(open(p)); n=0
for ce in d.get("compensationEligibility",[]):
    for pe in ce.get("passengerEligibility",[]):
        cd=pe.get("compensationDetails")
        if cd and cd.get("amount"): cd["amount"]=HIGH; cd["currency"]="CAD"; n+=1
for soc in d.get("socFlightEligibility",[]):
    for pe in soc.get("passengerEligibility",[]):
        cd=pe.get("compensationDetails")
        if cd and cd.get("amount"): cd["amount"]=HIGH
json.dump(d, open(p,"w"), indent=1)
key=f"traces/DDS/{r['date']}/{pid}/response.json"
bf._sess.client("s3").put_object(Bucket=bf.BAT["s3_bucket"],Key=key,Body=open(p,"rb").read(),ContentType="application/json")
r["amount"]=HIGH; r["currency"]="CAD"; json.dump(idx, open(idxf,"w"), indent=1)
print(f"FD_PAY_TC_010 {pid}: amount={HIGH} CAD ({n} entries), S3 re-PUT, index updated -> {idxf}")
