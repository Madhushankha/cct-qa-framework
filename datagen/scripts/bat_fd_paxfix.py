#!/usr/bin/env python3
"""Make the DDS passengerEligibility count match the booking passenger count for the
multi-pax / group cases (FD_TC_011 = 3 pax, FD_TC_012 = 12 pax). The 239 build clones each
case's single-pax canonical DDS, so the group/multi-pax bookings (which DO cascade N passengers)
end up with only 1 passengerEligibility -> checkpoint 14 (trip pax == DDS pax == expected) fails.
This regenerates the cloned DDS with N passengerEligibility (PT-1..N) in every compensationEligibility
AND socFlightEligibility, re-PUTs S3 at the existing key, and records npax in the index.
Usage: paxfix.py <set_index.json>"""
import sys, json, os
sys.path.insert(0,f"{KB}/scripts")
import bat_fd_build as bf
NPAX={"FD_TC_011":3,"FD_TC_012":12}
idxf=sys.argv[1]; idx=json.load(open(idxf))
for r in idx:
    n=NPAX.get(r["tc"])
    if not n: continue
    pid=r["pnr_id"]; p=f"{bf.DDSW}/{pid}.dds.json"
    if not os.path.exists(p): bf.clone_one(r,"paxfix")
    d=json.load(open(p))
    def mult(container):
        pe0=container["passengerEligibility"][0]
        container["passengerEligibility"]=[dict(json.loads(json.dumps(pe0)),passengerId=f"{pid}-PT-{k}") for k in range(1,n+1)]
    for ce in d.get("compensationEligibility",[]): mult(ce)
    for soc in d.get("socFlightEligibility",[]): mult(soc)
    json.dump(d, open(p,"w"), indent=1)
    key=f"traces/DDS/{r['date']}/{pid}/response.json"
    bf._sess.client("s3").put_object(Bucket=bf.BAT["s3_bucket"],Key=key,Body=open(p,"rb").read(),ContentType="application/json")
    r["npax"]=n
    print(f"  {r['tc']} {pid}: DDS passengerEligibility -> {n} pax, S3 re-PUT, npax={n}")
json.dump(idx, open(idxf,"w"), indent=1)
print("PAXFIX_DONE ->",idxf)
