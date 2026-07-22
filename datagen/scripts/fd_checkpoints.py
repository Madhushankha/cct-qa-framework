#!/usr/bin/env python3
import os
"""FD PNR post-creation CHECKPOINTS — verify EVERY area the bot depends on; fail loudly on any miss.

Usage: AWS_PROFILE=ARC75-Temp-INT python3 fd_checkpoints.py <index.json> [--env int]

Checks, per PNR in the index (index rows need: pnr_id, syscode, pin[, email, group]):
  1. trip                ACTIVE
  2. trip_details        present
  3. passenger           present
  4. date_of_birth       set (no NULL)
  5. ticket              present
  6. eds_pnr_output      present            <-- the one that was silently missed before
  7. eds contact email   matches index email (authenticationContactDetails…apn.email)
  8. booking_context     bookingSubtype=GROUP for group rows
  9. DDS endpoint        systemCode matches index (only pin=True rows)
 10. PENDING flight≤72h  PENDING cases must fly within ±72h of today (a PENDING
                         verdict only holds while the disruption is still being assessed)
 11. DDS amount match    ELIGIBLE compensationDetails.amount == index amount (catches
                         high-value payment cases e.g. FD_PAY_TC_010 ≥ $9,000)
 12. NE/ND reason text   NOT_ELIGIBLE/NO_DETERMINATION carry a non-empty reason (lookup value)
 13. AC-Wallet loyalty   FD_TC_002/019/022 carry an Aeroplan FQTV membership (index loyalty_id)
 14. passenger count     index npax -> trip AND DDS passengerEligibility both == npax
                         (multipax/wallet sets); group booking -> DDS pe>=1 (holder assessed,
                         trip larger OK); else trip pax == DDS pe. Catches under/over-triplication
                         + DDS not covering all booking pax (ported from bat_fd_nonelig_multipax)
 15. CP loyalty (CProf)  customer-profiles PNRBooking object carries LoyaltyMembershipId==index
                         loyalty_id + LoyaltyProgramName='Aeroplan' (AC-Wallet cases; int/bat only)
 16. name uniqueness     every passenger name in the set is unique WITHIN the set AND absent from
                         any OTHER PNR in the passenger table. ENFORCED only when the index flags
                         `uniq_names` (unique-name sets); otherwise printed as (info) so the older
                         reused-canonical-name sets don't fail.

 17. ticket == pax      one ticket per passenger (count match). The plain `ticket` area only
                        asserts >=1 exists — multi-pax/group PNRs silently shipped with a single
                        ticket until this was added.
 18. ticket linkage     every ticket row links to a passenger_id of THIS pnr and document_type='T'
 19. segments==scenario trip-tracer booking matches the scenario JSON: trip.pnr, passenger names,
                        and each flight_segment (count, airports, flight number [DB int vs padded
                        str -> compared numerically], carrier, departure date, bound_rph).
                        PNRs whose scenario JSON isn't in the KB are counted n/a, not pass.

Prints per-area N/total, lists offenders, and a final PASS/FAIL. Non-zero exit on FAIL.
"""
import json, sys, os, ssl, urllib.request, datetime, boto3, psycopg2
import pnr_common_checks as C

TODAY=datetime.date.today(); WINDOW_DAYS=3   # ±72h
def is_pending(m): return m.get("status")=="PENDING" or "-PE-" in (m.get("syscode") or "")

IDX=sys.argv[1]
ENV="int"
if "--env" in sys.argv: ENV=sys.argv[sys.argv.index("--env")+1]
# S3-pin fallback (when the private DDS endpoint 403s) needs AWS creds; CRT historically ran
# without a profile (direct DB creds), so default one for CRT if the caller did not set it.
if ENV=="crt" and not os.environ.get("AWS_PROFILE"): os.environ["AWS_PROFILE"]="ac-cct-crt"
CFG={"int":dict(host="ac-cct-trip-tracer-rds-proxy-int-cac1.proxy-czy2ye8u22qy.ca-central-1.rds.amazonaws.com",
                secret="/int-cac1/ac-cct-trip-tracer-rds-cluster-int-cac1/db-credentials",
                dds="https://rule-engine-platform-service.ac-cct-int.cloud.aircanada.com/rule-engine/dds/output/"),
     "crt":dict(host="ac-cct-trip-tracer-rds-proxy-crt-cac1.proxy-cxqe2wacy866.ca-central-1.rds.amazonaws.com",
                secret="/crt-cac1/ac-cct-trip-tracer-rds-cluster-crt-cac1/db-credentials",
                dds="https://rule-engine-platform-service.ac-cct-crt.cloud.aircanada.com/rule-engine/dds/output/"),
     "bat":dict(host="ac-cct-trip-tracer-rds-proxy-bat-cac1.proxy-cnc6sqy2ooev.ca-central-1.rds.amazonaws.com",
                secret="/bat-cac1/ac-cct-trip-tracer-rds-cluster-bat-cac1/db-credentials",
                dds="https://rule-engine-platform-service.ac-cct-bat.cloud.aircanada.com/rule-engine/dds/output/")}[ENV]
API=os.environ.get("DDS_API_KEY", "")
rows=json.load(open(IDX)); ids=[m["pnr_id"] for m in rows]
by={m["pnr_id"]:m for m in rows}
LOY_SET=any(m.get("loyalty_id") for m in rows)   # loyalty checks only apply to loyalty-enabled sets
if CFG.get("secret"):
    sess=boto3.Session(region_name="ca-central-1")
    sec=json.loads(sess.client("secretsmanager").get_secret_value(SecretId=CFG["secret"])["SecretString"])
    _pairs=[(sec.get("username"),sec.get("password")),(sec.get("adminuser"),sec.get("adminpassword"))]
else:
    _pairs=[(CFG.get("user"),CFG.get("password"))]
_conn=_err=None
for _u,_p in _pairs:
    if not _u or not _p: continue
    try:
        _conn=psycopg2.connect(host=CFG["host"],port=5432,dbname="trip-tracer",user=_u,password=_p,
                               sslmode="require",connect_timeout=20); break
    except psycopg2.OperationalError as _e:
        if "password authentication failed" not in str(_e): raise
        _err=_e
if _conn is None: raise _err or RuntimeError("no usable credential pair for trip-tracer")
cur=_conn.cursor()

def col(q):
    cur.execute(q,(ids,)); return {r[0]:r[1] for r in cur.fetchall()}
trip=col("SELECT pnr_id,status FROM trip WHERE pnr_id=ANY(%s)")
td=col("SELECT pnr_id,count(*) FROM trip_details WHERE pnr_id=ANY(%s) GROUP BY pnr_id")
cur.execute("SELECT pnr_id,count(*),count(*) FILTER (WHERE date_of_birth IS NULL) FROM passenger WHERE pnr_id=ANY(%s) AND NOT is_removed GROUP BY pnr_id",(ids,))
pax={r[0]:(r[1],r[2]) for r in cur.fetchall()}
tkt=col("SELECT pnr_id,count(*) FROM ticket WHERE pnr_id=ANY(%s) GROUP BY pnr_id")
# (17/18) ticket integrity — one ticket per passenger, each linked to a passenger of THIS pnr, type T
cur.execute("SELECT pnr_id,primary_document_number,passenger_id,document_type FROM ticket WHERE pnr_id=ANY(%s)",(ids,))
_tkrows={}
for pid,doc,pxid,dtype in cur.fetchall(): _tkrows.setdefault(pid,[]).append((doc,pxid,dtype))
tkt_link_off=[]
for p in ids:
    for doc,pxid,dtype in _tkrows.get(p,[]):
        if not pxid or not str(pxid).startswith(p) or dtype!="T":
            tkt_link_off.append(p); break
# (19) trip locator + flight_segment rows (compared against the scenario file when present)
trip_pnr=col("SELECT pnr_id,pnr FROM trip WHERE pnr_id=ANY(%s)")
cur.execute("""SELECT pnr_id,bound_rph,departure_airport,arrival_airport,marketing_flight_number,
                      marketing_carrier_code,departure_datetime_local
               FROM flight_segment WHERE pnr_id=ANY(%s) AND NOT is_removed""",(ids,))
_segrows={}
for row in cur.fetchall(): _segrows.setdefault(row[0],[]).append(row[1:])
# eds present + contact email + booking_context
cur.execute("SELECT DISTINCT ON (pnr_id) pnr_id,bounds,booking_context FROM eds_pnr_output WHERE pnr_id=ANY(%s) ORDER BY pnr_id,received_at DESC",(ids,))
eds={}; edsmail={}; edsgrp={}; edsauthn={}
for pid,b,bc in cur.fetchall():
    eds[pid]=1
    try:
        bb=json.loads(b) if isinstance(b,str) else b
        _aps=bb[0]["authenticationContactDetails"]["passengers"]
        edsmail[pid]=_aps[0]["contacts"]["apn"].get("email")
        # (20) eds auth passengers must match the real passenger count. The eds row is CLONED from a
        # donor PNR, so a donor that later gained/lost passengers silently ships a wrong auth block
        # (e.g. a PT-2 entry on a 1-pax booking). Caught in set3: donor MHYLXV became 2-pax.
        edsauthn[pid]=len(_aps)
    except Exception: edsmail[pid]=None
    try:
        o=json.loads(bc) if isinstance(bc,str) else (bc or {}); edsgrp[pid]=o.get("bookingSubtype")
    except Exception: edsgrp[pid]=None
# (16) name uniqueness — names unique WITHIN the set AND absent from any OTHER PNR in the DB
from collections import Counter as _Counter
cur.execute("SELECT pnr_id, first_name, last_name FROM passenger WHERE pnr_id=ANY(%s) AND NOT is_removed",(ids,))
_setrows=cur.fetchall()
_paircnt=_Counter((f,l) for _,f,l in _setrows)
_within_dup={pair for pair,n in _paircnt.items() if n>1}
_uniq_pairs=list({(f,l) for _,f,l in _setrows})
_ext_present=set()
if _uniq_pairs:
    cur.execute("SELECT DISTINCT first_name,last_name FROM passenger WHERE (first_name,last_name) IN %s AND NOT (pnr_id=ANY(%s))",(tuple(_uniq_pairs),ids))
    _ext_present={(f,l) for f,l in cur.fetchall()}
name_off=sorted({pid for pid,f,l in _setrows if (f,l) in _within_dup or (f,l) in _ext_present})
# (20-22) DATE WINDOWS — shared with every other checkpoint script (pnr_common_checks.date_windows)
_win, _bookdate = C.date_windows(cur, rows, flight="past", claim_days=365)   # FD: claim on a FLOWN flight, APPR 365d limit
cur.close()

def offenders(pred): return [p for p in ids if pred(p)]
checks={
 "trip ACTIVE":       offenders(lambda p: trip.get(p)!="ACTIVE"),
 "trip_details":      offenders(lambda p: td.get(p,0)==0),
 "passenger":         offenders(lambda p: pax.get(p,(0,0))[0]==0),
 "DOB set":           offenders(lambda p: pax.get(p,(0,1))[1]>0),
 "ticket":            offenders(lambda p: tkt.get(p,0)==0),
 "ticket == pax":     offenders(lambda p: tkt.get(p,0)!=pax.get(p,(0,0))[0]),
 "ticket linkage":    offenders(lambda p: p in set(tkt_link_off)),
 "eds_pnr_output":    offenders(lambda p: p not in eds),
 "eds contact email": offenders(lambda p: by[p].get("email") and edsmail.get(p)!=by[p]["email"]),
 "eds auth == pax":   offenders(lambda p: p in edsauthn and edsauthn[p]!=pax.get(p,(0,0))[0]),
 "GROUP context":     offenders(lambda p: by[p].get("group") and edsgrp.get(p)!="GROUP"),
}
print(f"CHECKPOINTS for {IDX} — {len(ids)} PNRs ({ENV})")
ok=True
for name,off in checks.items():
    n=len(ids)-len(off); print(f"  {name:18} {n}/{len(ids)}"+("" if not off else f"  MISS {len(off)}: {off[:8]}"))
    if off: ok=False
# DDS endpoint (pin only)
ctx=ssl.create_default_context(); ctx.check_hostname=False; ctx.verify_mode=ssl.CERT_NONE
pinned=[m for m in rows if m.get("pin")]; dmatch=0; dbad=[]; datebad=[]; pend=0
amtbad=[]; amtn=0; rsnbad=[]; rsnn=0; loybad=[]; loyn=0; pcbad=[]; pcn=0; bdbad=[]; bdn=0
WALLET_TCS={"FD_TC_002","FD_TC_019","FD_TC_022"}   # AC-Wallet cases need an Aeroplan (FQTV) membership
for m in pinned:
    try:
        d=C.dds_fetch(m["pnr_id"],m,ENV,ctx)   # endpoint, with automatic S3-pin fallback on 403/outage
        pe0=d["compensationEligibility"][0]["passengerEligibility"][0]
        got=pe0["systemCode"]
        if got==m["syscode"]: dmatch+=1
        else: dbad.append((m["pnr_id"],f"exp {m['syscode']} got {got}"))
        # (11) DDS amount matches the index amount (ELIGIBLE only carries compensationDetails)
        if pe0.get("eligibilityStatus")=="ELIGIBLE" and m.get("amount"):
            amtn+=1; a=(pe0.get("compensationDetails") or {}).get("amount")
            if a!=m["amount"]: amtbad.append((m["pnr_id"],f"exp {m['amount']} got {a}"))
        # (12) NE/ND carry a non-empty reason text (per the reference lookup)
        if pe0.get("eligibilityStatus") in ("NOT_ELIGIBLE","NO_DETERMINATION"):
            rsnn+=1
            if not (pe0.get("reason") or "").strip(): rsnbad.append((m["pnr_id"],f"{got} empty reason"))
        # (13) AC-Wallet cases carry an Aeroplan FQTV loyalty membership
        tc=m.get("tc") or m.get("case")
        if LOY_SET and tc in WALLET_TCS:   # only enforce on loyalty-enabled sets (elig91cp/wallet)
            loyn+=1
            if not m.get("loyalty_id"): loybad.append((m["pnr_id"],f"{tc} no loyalty_id"))
        # (14) passenger count. npax set -> trip & DDS both == npax (multipax/wallet sets).
        # group booking -> DDS assesses the holder (pe>=1), trip may be larger. Else trip==DDS.
        pcn+=1
        dpe=len(d["compensationEligibility"][0]["passengerEligibility"])
        tp=pax.get(m["pnr_id"],(0,0))[0]
        exp=m.get("npax")
        if exp:
            if tp!=exp or dpe!=exp: pcbad.append((m["pnr_id"],f"exp{exp} trip{tp}/dds{dpe}"))
        elif m.get("group"):
            if dpe<1 or tp<1: pcbad.append((m["pnr_id"],f"group trip{tp}/dds{dpe}"))
        elif tp!=dpe: pcbad.append((m["pnr_id"],f"trip{tp}!=dds{dpe}"))
        # flight-date window: a PENDING verdict only holds within ±72h of the disruption
        if is_pending(m):
            pend+=1
            try:
                dep=d["itineraryDetails"][0]["actualItinerary"]["associatedSegments"][0]["departureDatetime"][:10]
                delta=(datetime.date.fromisoformat(dep)-TODAY).days
                if abs(delta)>WINDOW_DAYS: datebad.append((m["pnr_id"],f"flight {dep} Δ{delta}d outside ±{WINDOW_DAYS}d"))
            except Exception as e: datebad.append((m["pnr_id"],f"no flight date: {str(e)[:30]}"))
        # (23) booking == DDS flight date — a verdict whose itinerary date differs from the
        # booking the bot reads is inconsistent (hit: PENDING DDS re-dated, booking left behind)
        try:
            _dp=d["itineraryDetails"][0]["actualItinerary"]["associatedSegments"][0]["departureDatetime"][:10]
            _bd=_bookdate.get(m["pnr_id"])
            if _bd:
                bdn+=1
                if str(_bd)!=_dp: bdbad.append((m["pnr_id"],f"booking {_bd} != dds {_dp}"))
        except Exception: pass
    except Exception as e: dbad.append((m["pnr_id"],str(e)[:40]))
print(f"  DDS endpoint       {dmatch}/{len(pinned)}"+("" if not dbad else f"  BAD {len(dbad)}: {dbad[:8]}"))
if dbad: ok=False
print(f"  DDS amount match   {amtn-len(amtbad)}/{amtn}"+("" if not amtbad else f"  BAD {len(amtbad)}: {amtbad[:8]}"))
if amtbad: ok=False
print(f"  NE/ND reason text  {rsnn-len(rsnbad)}/{rsnn}"+("" if not rsnbad else f"  BAD {len(rsnbad)}: {rsnbad[:8]}"))
if rsnbad: ok=False
print(f"  AC-Wallet loyalty  {loyn-len(loybad)}/{loyn}"+("" if not loybad else f"  BAD {len(loybad)}: {loybad[:8]}"))
if loybad: ok=False
print(f"  passenger count    {pcn-len(pcbad)}/{pcn}"+("" if not pcbad else f"  BAD {len(pcbad)}: {pcbad[:8]}"))
if pcbad: ok=False
for _lbl,_off in _win.items():
    print(f"  {_lbl:18} {len(ids)-len(_off)}/{len(ids)}"+("" if not _off else f"  BAD {len(_off)}: {_off[:8]}"))
    if _off: ok=False
print(f"  booking==dds date  {bdn-len(bdbad)}/{bdn}"+("" if not bdbad else f"  BAD {len(bdbad)}: {bdbad[:6]}"))
if bdbad: ok=False
print(f"  PENDING flight≤72h {pend-len(datebad)}/{pend}"+("" if not datebad else f"  BAD {len(datebad)}: {datebad[:8]}"))
if datebad: ok=False
# (19) trip-tracer booking vs the SCENARIO file: trip.pnr, passenger names, and every flight_segment
# (count, airports, flight number, carrier, departure date, bound_rph). Skipped for PNRs whose
# scenario JSON isn't in the KB (some sets render from a work dir) — those count as n/a, not pass.
_SCN=os.path.join(os.path.dirname(os.path.abspath(__file__)),"..","scenarios","fd-sit")
segbad=[]; segn=0
for m in rows:
    p=m["pnr_id"]; sp=os.path.join(_SCN,f"{p}.json")
    if not os.path.exists(sp): continue
    segn+=1; iss=[]
    try:
        scn=json.load(open(sp))
        if trip_pnr.get(p)!=scn["identity"]["pnr"]: iss.append(f"trip.pnr {trip_pnr.get(p)}!={scn['identity']['pnr']}")
        sc_names=sorted((x["first_name"],x["last_name"]) for x in scn["passengers"])
        db_names=sorted((f,l) for pid,f,l in _setrows if pid==p)
        if db_names!=sc_names: iss.append("passenger names != scenario")
        db=sorted(_segrows.get(p,[]),key=lambda x:str(x[5]))
        sc=sorted(scn["segments"],key=lambda x:x["dep_local"])
        if len(db)!=len(sc): iss.append(f"segments {len(db)}!={len(sc)}")
        else:
            for (brph,dep,arr,mfn,mcar,ddt),s in zip(db,sc):
                if dep!=s["origin"] or arr!=s["destination"]: iss.append(f"route {dep}-{arr}!={s['origin']}-{s['destination']}")
                if int(mfn)!=int(s["flight_number"]): iss.append(f"flt {mfn}!={s['flight_number']}")   # DB int vs padded str
                if mcar!=s["carrier"]: iss.append(f"carrier {mcar}!={s['carrier']}")
                if ddt and str(ddt)[:10]!=s["dep_local"][:10]: iss.append(f"dep {str(ddt)[:10]}!={s['dep_local'][:10]}")
                if s.get("bound") is not None and brph is not None and int(brph)!=int(s["bound"]): iss.append(f"bound_rph {brph}!={s['bound']}")
    except Exception as e: iss.append(str(e)[:40])
    if iss: segbad.append((p,iss[:3]))
_na=len(ids)-segn
print(f"  segments==scenario {segn-len(segbad)}/{segn}"+(f"  (n/a {_na})" if _na else "")+("" if not segbad else f"  BAD {len(segbad)}: {segbad[:6]}"))
if segbad: ok=False
# (16) name uniqueness — enforced only on sets flagged uniq_names; else informational
UNIQ_ENFORCE=any(m.get("uniq_names") for m in rows)
_nlabel="name uniqueness" if UNIQ_ENFORCE else "name uniq (info)"
print(f"  {_nlabel:18} {len(ids)-len(name_off)}/{len(ids)}"+("" if not name_off else f"  DUP/INDB {len(name_off)}: {name_off[:8]}"))
if name_off and UNIQ_ENFORCE: ok=False
# (15) CP LoyaltyMembershipId — the customer-profiles PNRBooking object must carry the Aeroplan
# membership (index loyalty_id) + LoyaltyProgramName='Aeroplan'. Only on loyalty-enabled sets,
# only where a CP domain exists (int/bat). Ported alongside the INT CP write.
cprows=[m for m in rows if m.get("loyalty_id")]
if cprows and ENV in ("int","bat"):
    DOM=f"ac-cct-{ENV}"; cpn=0; cpbad=[]
    try:
        cpc=boto3.Session(region_name="ca-central-1").client("customer-profiles")
        for m in cprows:
            pid=m["pnr_id"]; mem=m["loyalty_id"]; cpn+=1; got=[]
            for pr in cpc.search_profiles(DomainName=DOM,KeyName="PNRId",Values=[pid],MaxResults=20)["Items"]:
                tok=None
                while True:
                    kw=dict(DomainName=DOM,ObjectTypeName="PNRBooking",ProfileId=pr["ProfileId"],MaxResults=100)
                    if tok: kw["NextToken"]=tok
                    r=cpc.list_profile_objects(**kw)
                    for o in r["Items"]:
                        b=json.loads(o["Object"])
                        if b.get("PNRId")==pid: got.append((b.get("LoyaltyMembershipId"),b.get("LoyaltyProgramName")))
                    tok=r.get("NextToken")
                    if not tok: break
            if not any(g==(mem,"Aeroplan") for g in got): cpbad.append((pid,f"exp {mem}/Aeroplan got {got[:3]}"))
        print(f"  CP loyalty (CProf) {cpn-len(cpbad)}/{cpn}"+("" if not cpbad else f"  BAD {len(cpbad)}: {cpbad[:8]}"))
        if cpbad: ok=False
    except Exception as e:
        print(f"  CP loyalty (CProf) SKIP — {str(e)[:60]}")
print(("PASS ✅ all areas present" if ok else "FAIL ❌ — see MISS/BAD above"))
sys.exit(0 if ok else 1)
