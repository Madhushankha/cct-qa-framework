#!/usr/bin/env python3
"""Inject Aeroplan loyalty (loyaltyRequests FQTV) into AC-Wallet cases FD_TC_002/019/022 so the
Aeroplan->AC-Wallet payout path resolves. Fresh locator (loyalty=a re-publish; Altea PNRs are
locator-keyed so reuse drops eds), same date, republish->cascade->finalize->pin->verify, update
index in place. Usage: bat_fd_walletfix.py <set_index.json>"""
import sys, json, time, ssl, urllib.request, glob
sys.path.insert(0,f"{KB}/scripts")
import bat_fd_build as bf
WALLET=["FD_TC_002","FD_TC_019","FD_TC_022"]
idxf=sys.argv[1]; idx=json.load(open(idxf)); pos={r["tc"]:i for i,r in enumerate(idx)}
taken=set()
for f in glob.glob(f"{bf.FD}/_FD_*_bat_index.json"):
    for e in json.load(open(f)):
        if e.get("pnr_id"): taken.add(e["pnr_id"][:6])
locs=bf.gen_locators(len(WALLET), 920920, taken); jobs=[]
for k,tc in enumerate(WALLET):
    e=dict(idx[pos[tc]]); loc=locs[k]; date=e["date"]; num=int(tc.split("_")[-1])
    e["loc"]=loc; e["pnr_id"]=f"{loc}-{date}"; e["ticket"]=f"{e['ticket'][:6]}7{num:05d}"
    e["loyalty_id"]=f"9152{num:05d}"; e["cp_account"]=e["loyalty_id"]
    e.setdefault("forced",False); e.setdefault("oal",False); e.setdefault("pax_set",None); e.setdefault("sit",None)
    jobs.append((pos[tc],tc,e))
for _,tc,e in jobs: bf.clone_one(e, "walletfix"); print(f"  clone {tc} -> {e['pnr_id']} loyalty {e['loyalty_id']}")
for _,tc,e in jobs:
    ok,log=bf.render_publish_one(e); print(f"  publish {e['pnr_id']} {'OK' if ok else 'FAIL '+log[-100:]}")
print("waiting 55s..."); time.sleep(55)
ttc=bf.tt_conn(); have=bf.cascaded(ttc,[e["pnr_id"] for _,_,e in jobs]); print("  cascaded:",len(have),"/",len(jobs))
keys={}
for _,tc,e in jobs: keys[e["pnr_id"]]=bf.finalize_one(e,ttc,e); print(f"  finalize {e['pnr_id']}")
bf.pin_all([e for _,_,e in jobs], keys); ttc.close(); time.sleep(4)
ctx=ssl.create_default_context(); ctx.check_hostname=False; ctx.verify_mode=ssl.CERT_NONE
for _,tc,e in jobs:
    b=json.load(urllib.request.urlopen(urllib.request.Request(bf.BAT["endpoint"]+e["pnr_id"],headers={"x-api-key":bf.BAT["api_key"]}),context=ctx,timeout=20))
    pe=b["compensationEligibility"][0]["passengerEligibility"][0]
    loy=f'"number":"{e["loyalty_id"]}"' in open(f"{bf.NDJW}/{e['loc']}.ndjson").read()
    print(f"  verify {tc} {e['pnr_id']}: {pe['eligibilityStatus']}/{pe['systemCode']} loyalty_in_pnr={loy}")
for p,tc,e in jobs: idx[p]=e
json.dump(idx, open(idxf,"w"), indent=1); print("WALLETFIX_DONE ->",idxf)
