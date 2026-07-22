#!/usr/bin/env python3
"""Two special fresh SOC UAT PNRs (per workbook prerequisites, tickets 014356):
  X1 SOC-UAT-027 SoC-APPR-EL-03  MULTI-PAX (2 ADT + 1 CHD), AC601 YYZ->YEG diverted
     back to origin (No Travel Return), 960 min, code 44 SAFETY, 12-24h entitlements.
  X2 SOC-UAT-030 SoC-APPR-EL-06  MULTI-SEGMENT (AC701 YYZ->YYC flown + AC702 YYC->YVR
     cancelled TECH), No Travel Incomplete, verdict on segment 2, 840 min.
Phases: gen | publish | finalize | edsinject | verify   (email/phone = lahiru)
"""
import json, os, sys, copy, argparse, ssl, uuid, urllib.request
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import int_fd_build as B
import crt_uniqnames as U

KB   = os.environ.get("CCTQA_DATAGEN_ROOT",
                      os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
FD=f"{KB}/scenarios/fd-sit"; DDST=f"{FD}/_dds-templates"
IDX=f"{FD}/_FD_SOCUAT_EXTRA_index.json"
BASE=f"{FD}/CPPCSP-2026-06-15.json"
LOOK={ }
for t in json.load(open(f"{KB}/scripts/_live_tables_cache.json")).get("tables",[]):
    if "Reason Codes" in t.get("name",""):
        for r in t.get("data",[]): LOOK[r.get("key") or r.get("code")]=r.get("value","")
EMAIL="lahiru.premathilake@aircanada.ca"; PHONE="+94712534323"
DOB_ADT="1986-04-23"; DOB_CHD="2016-04-23"; DATE="2026-06-20"

X1=dict(tc="SOC-UAT-027", req="SoC-APPR-EL-03", loc=None, npax=3,
        pax=[("MARC","TREMBLAY","ADT",DOB_ADT),("ISABELLE","TREMBLAY","ADT",DOB_ADT),
             ("NOAH","TREMBLAY","CHD",DOB_CHD)],
        title="APPR Eligible No Travel Return (safety 44) MULTI-PAX")
X2=dict(tc="SOC-UAT-030", req="SoC-APPR-EL-06", loc=None, npax=1,
        pax=[("LOUIS","FERLAND","ADT",DOB_ADT)],
        title="APPR Eligible No Travel Incomplete (TECH fallback) MULTI-SEGMENT")

ENT27=[("MEAL",60),("ACCOMMODATION",500),("TRANSPORTATION",200),("COMMUNICATION",30),("PARKING",50),("ESSENTIALS",30)]
ENT30=[("MEAL",60),("ACCOMMODATION",500),("TRANSPORTATION",200),("COMMUNICATION",30),("PARKING",50),("ESSENTIALS",30)]
CAT="DELAY_12_TO_LT_24_HOURS"

def pe_soc(pid,i,pax,status,code,cats,ptype):
    return dict(passengerId=f"{pid}-PT-{i}",passengerType=ptype,bookingClass=None,cabinClass="ECONOMY",
        eligibilityStatus=status,systemCode=code,reason=LOOK.get(code,code),
        expiryDate=("2027-12-31" if status=="ELIGIBLE" else ""),
        expenseCategories=[dict(type=t,region="CANADA",delayBand=CAT,currency="CAD",amount=a) for t,a in cats] if status=="ELIGIBLE" else [],
        failureReasons=None)

def pe_comp(pid,i,ptype,amount):
    return dict(passengerId=f"{pid}-PT-{i}",passengerType=ptype,eligibilityStatus="ELIGIBLE",
        systemCode=f"FD-APPR-EL-{amount}",reason=LOOK.get(f"FD-APPR-EL-{amount}","arrival delay within carrier control"),
        failureReasons=None,
        compensationDetails=dict(amount=amount,currency="CAD",delayBand="DELAY_9_HOURS_OR_MORE",expiryDate="2027-12-31"))

def seg_j(pid,n,carr,fno,o,d,dep,arr):
    return dict(segmentId=f"{pid}-ST-{n}",segmentStatus="HK",
        departureDatetime=dep,arrivalDatetime=arr,departureAirport=o,arrivalAirport=d,
        marketingFlightNumber=int(fno),marketingCarrierCode=carr,
        operatingFlightNumber=int(fno),operatingCarrierCode="AC",
        flightId=f"AC#{fno}#{DATE}#{o}")

def na(pid,reg,code,npax,ptypes):
    return dict(regime=reg,boundRph=1,passengerEligibility=[dict(passengerId=f"{pid}-PT-{i+1}",
        passengerType=ptypes[i],eligibilityStatus="NOT_ELIGIBLE",systemCode=code,
        reason=LOOK.get(code,"Regime not applicable"),failureReasons=None) for i in range(npax)])

def dds_x1(pid,loc):
    ptypes=["ADT","ADT","CHD"]
    s1=seg_j(pid,1,"AC","601","YYZ","YEG",f"{DATE}T12:00:00+00:00",f"{DATE}T16:00:00+00:00")
    comp=dict(regime="APPR",boundRph=1,
        mslFlight=dict(segmentId=f"{pid}-ST-1",carrierCode="AC",flightNumber="601",
            departureAirport="YYZ",arrivalAirport="YEG",isStarSegment=False,isOalSegment=False),
        disruptionType="INVOLUNTARY",delayMinutes=960,delayType="SAFETY",delayCode="44",
        customerFriendlyDisruptionReason="Your flight was disrupted for a reason required for safety.",
        disruptionReason="MECHANICAL",
        passengerEligibility=[pe_comp(pid,i+1,ptypes[i],1000) for i in range(3)])
    soc=[dict(regime="APPR",boundRph=1,segmentId=f"{pid}-ST-1",carrierCode="AC",flightNumber=601,
        departureAirport="YYZ",arrivalAirport="YEG",segmentStatus="HK",disruptionType="INVOLUNTARY",
        delayType="SAFETY",delayCode="44",disruptionReason="MECHANICAL",
        customerFriendlyDisruptionReason="Reasonable meal and hotel expenses are reimbursable.",
        delayMinutes=960,delayCategory=CAT,
        passengerEligibility=[pe_soc(pid,i+1,None,"ELIGIBLE","SoC-APPR-EL-03",ENT27,ptypes[i]) for i in range(3)])]
    return dict(eventMetadata=dict(trigger="DISRUPTION_DETECTION_SERVICE",timestamp=f"{DATE}T20:05:34.000Z"),
        pnrIdentifier=dict(pnrId=pid,pnr=loc),
        itineraryDetails=[dict(bound=1,boundRph=1,isOAL=False,
            promisedItinerary=dict(origin="YYZ",destination="YEG",associatedSegments=[s1]),
            actualItinerary=dict(origin="YYZ",destination="YEG",associatedSegments=[s1]))],
        compensationEligibility=[comp,na(pid,"EU","FD-EU-NA-01",3,ptypes),na(pid,"ASL","FD-ASL-NA-01",3,ptypes)],
        socFlightEligibility=soc,seatFeeRefundEligibility=[])

def dds_x2(pid,loc):
    s1=seg_j(pid,1,"AC","701","YYZ","YYC",f"{DATE}T11:00:00+00:00",f"{DATE}T15:00:00+00:00")
    s2=seg_j(pid,2,"AC","702","YYC","YVR",f"{DATE}T16:00:00+00:00",f"{DATE}T17:30:00+00:00")
    comp=dict(regime="APPR",boundRph=1,
        mslFlight=dict(segmentId=f"{pid}-ST-2",carrierCode="AC",flightNumber="702",
            departureAirport="YYC",arrivalAirport="YVR",isStarSegment=False,isOalSegment=False),
        disruptionType="INVOLUNTARY",delayMinutes=840,delayType="CONTROLLABLE",delayCode="TECH",
        customerFriendlyDisruptionReason="Your connecting flight was cancelled for a mechanical reason.",
        disruptionReason="MECHANICAL",
        passengerEligibility=[pe_comp(pid,1,"ADT",1000)])
    soc=[dict(regime="APPR",boundRph=1,segmentId=f"{pid}-ST-1",carrierCode="AC",flightNumber=701,
            departureAirport="YYZ",arrivalAirport="YYC",segmentStatus="HK",disruptionType="INVOLUNTARY",
            delayType="OTHER",delayCode="",disruptionReason="",customerFriendlyDisruptionReason="",
            delayMinutes=0,delayCategory="DELAY_LT_2_HOURS",
            passengerEligibility=[pe_soc(pid,1,None,"NOT_ELIGIBLE","SoC-APPR-NE-04",[],"ADT")]),
         dict(regime="APPR",boundRph=1,segmentId=f"{pid}-ST-2",carrierCode="AC",flightNumber=702,
            departureAirport="YYC",arrivalAirport="YVR",segmentStatus="HK",disruptionType="INVOLUNTARY",
            delayType="CONTROLLABLE",delayCode="TECH",disruptionReason="MECHANICAL",
            customerFriendlyDisruptionReason="Reasonable meal and hotel expenses are reimbursable.",
            delayMinutes=840,delayCategory=CAT,
            passengerEligibility=[pe_soc(pid,1,None,"ELIGIBLE","SoC-APPR-EL-06",ENT30,"ADT")])]
    return dict(eventMetadata=dict(trigger="DISRUPTION_DETECTION_SERVICE",timestamp=f"{DATE}T20:05:34.000Z"),
        pnrIdentifier=dict(pnrId=pid,pnr=loc),
        itineraryDetails=[dict(bound=1,boundRph=1,isOAL=False,
            promisedItinerary=dict(origin="YYZ",destination="YVR",associatedSegments=[s1,s2]),
            actualItinerary=dict(origin="YYZ",destination="YVR",associatedSegments=[s1,s2]))],
        compensationEligibility=[comp,na(pid,"EU","FD-EU-NA-01",1,["ADT"]),na(pid,"ASL","FD-ASL-NA-01",1,["ADT"])],
        socFlightEligibility=soc,seatFeeRefundEligibility=[])

def gen():
    import glob
    base=json.load(open(BASE)); taken=set()
    for f in glob.glob(f"{FD}/_FD_*index.json"):
        try:
            for e in json.load(open(f)):
                if e.get("pnr_id"): taken.add(e["pnr_id"][:6])
        except Exception: pass
    locs=B.gen_locators(2, 565656, taken)
    recs=[]
    UNIQ=os.environ.get("CRT_UNIQ_NAMES")=="1"       # opt-in unique passenger names
    urecs=[{"npax":len(X1["pax"])},{"npax":len(X2["pax"])}]   # X1 multi-pax (3), X2 single
    if UNIQ:
        _c=B.tt_conn()
        try: U.assign_names(urecs, lambda r:r["npax"], _c, seed=911004)
        finally: _c.close()
    for k,(x,segs) in enumerate([(X1,[("AC","601","YYZ","YEG","2026-06-20T08:00:00","2026-06-20T10:00:00","2026-06-20T12:00:00Z","2026-06-20T16:00:00Z")]),
                                 (X2,[("AC","701","YYZ","YYC","2026-06-20T07:00:00","2026-06-20T09:00:00","2026-06-20T11:00:00Z","2026-06-20T15:00:00Z"),
                                      ("AC","702","YYC","YVR","2026-06-20T10:00:00","2026-06-20T10:30:00","2026-06-20T16:00:00Z","2026-06-20T17:30:00Z")])]):
        loc=locs[k]; pid=f"{loc}-{DATE}"; x["loc"]=loc
        paxs=x["pax"]                                 # (first,last,type,dob) per passenger
        if UNIQ:
            pn=urecs[k]["pax_names"]
            paxs=[(pn[j][0],pn[j][1],t,db) for j,(fn,ln,t,db) in enumerate(x["pax"])]
        s=copy.deepcopy(base)
        s["scenario_id"]=pid; s["identity"]["pnr"]=loc; s["identity"]["booking_date"]=DATE
        s["title"]=f"{x['tc']} {x['req']}: {x['title']} [{loc}]"
        s["description"]=f"{x['tc']} | {x['req']} | {x['title']}"
        s["creation_comment"]=s["last_modification_comment"]=f"SIM-{x['tc']}-X-INT"
        s["ticketing"]["ticket_numbers"]=[f"014356{k+1:05d}{i+1:02d}"[:13] for i in range(len(x["pax"]))]
        s["classification"]=dict(primary_code=x["tc"],primary_name=f"SOC UAT extra {x['req']}",confidence="high")
        s["tags"]=["synthetic","soc-uat-extra"]
        s["passengers"]=[dict(type=t,first_name=fn,last_name=ln,gender="U",date_of_birth=db,
                              email=EMAIL,phone=PHONE) for fn,ln,t,db in paxs]
        s["segments"]=[dict(carrier=c,operating_carrier="AC",flight_number=f,operating_flight_number=f,
            origin=o,destination=d,dep_local=dl,arr_local=al,dep_utc=du,arr_utc=au,
            booking_datetime=None,aircraft="789",cabin="Y",status="HK",arrival_terminal="1")
            for c,f,o,d,dl,al,du,au in segs]
        s["expected_cascade"]["db_end_state"]["trip"].update(pnr=loc,pnr_id=pid)
        s["expected_cascade"]["db_end_state"]["passenger"]["rows"]=len(x["pax"])
        s["expected_cascade"]["db_end_state"]["flight_segment"]["rows"]=len(segs)
        json.dump(s,open(f"{B.SCENW}/{pid}.json","w"),indent=1)
        json.dump(s,open(f"{FD}/{pid}.json","w"),indent=1)
        d=(dds_x1 if k==0 else dds_x2)(pid,loc)
        json.dump(d,open(f"{B.DDSW}/{pid}.dds.json","w"),indent=1)
        json.dump(d,open(f"{DDST}/{pid}.dds.json","w"),indent=1)
        soc_legs=[dict(n=i+1,carrier="AC",flight=f"AC{sg[1]}",sector=f"{sg[2]}-{sg[3]}",
                       soc_status=e["passengerEligibility"][0]["eligibilityStatus"],
                       soc_code=e["passengerEligibility"][0]["systemCode"],role="X")
                  for i,(sg,e) in enumerate(zip(segs,d["socFlightEligibility"]))]
        recs.append(dict(tc=x["tc"]+"-X",req=x["req"],title=x["title"],loc=loc,pnr_id=pid,date=DATE,
            tickets=s["ticketing"]["ticket_numbers"],ticket=s["ticketing"]["ticket_numbers"][0],
            pax=", ".join(f"{fn} {ln}" for fn,ln,_,_ in paxs),npax=len(paxs),
            pax_detail=[dict(first=fn,last=ln,type=t,dob=db) for fn,ln,t,db in paxs],
            route="-".join([segs[0][2]]+[sg[3] for sg in segs]),legs=soc_legs,
            status="ELIGIBLE",syscode="FD-APPR-EL-1000",amount=1000,currency="CAD",
            email=EMAIL,phone=PHONE,pin=True,group=False))
        if UNIQ:
            recs[-1]["pax_names"]=urecs[k]["pax_names"]; recs[-1]["uniq_names"]=True
    json.dump(recs,open(IDX,"w"),indent=1)
    print(f"[gen] 2 -> {IDX}"); print(json.dumps([{k:r[k] for k in ('tc','loc','route','npax')} for r in recs],indent=1))

def load(): return json.load(open(IDX))

def publish(sl):
    for r in sl:
        ok,log=B.render_publish_one(r)
        print(f"  {r['tc']} {r['pnr_id']} {'OK' if ok else 'FAIL '+log[-160:]}")

def finalize(sl):
    ttc=B.tt_conn(); keys={}
    for r in sl:
        cur=ttc.cursor(); pid=r["pnr_id"]
        for i,(tk,pd) in enumerate(zip(r["tickets"],r["pax_detail"]),1):
            cur.execute("""insert into ticket (primary_document_number,pnr_id,passenger_id,ticket_id,document_numbers,issuance_local_date,document_type)
                values (%s,%s,%s,%s,ARRAY[%s],%s,'T') on conflict do nothing""",
                (tk,pid,f"{pid}-PT-{i}",f"{tk}-2026-06-01",tk,"2026-06-01"))
            cur.execute("update passenger set date_of_birth=%s where pnr_id=%s and passenger_id=%s",
                        (pd["dob"],pid,f"{pid}-PT-{i}"))
        ttc.commit()
        key=f"traces/DDS/{r['date']}/{pid}/response.json"
        B._sess.client("s3").put_object(Bucket=B.BAT["s3_bucket"],Key=key,
            Body=open(f"{B.DDSW}/{pid}.dds.json","rb").read(),ContentType="application/json")
        keys[pid]=key; print(f"  {pid} tickets({len(r['tickets'])})+DOB+S3 ok")
    ttc.close()
    print("[pin]",B.pin_all(sl,keys))

def edsinject(sl):
    ttc=B.tt_conn(); cur=ttc.cursor()
    BC=json.dumps({"bookingSource":"AC_VACATIONS","bookingType":"REVENUE","bookingSubtype":"REVENUE","gdsLocator":"AMADEUS"})
    for r in sl:
        pid=r["pnr_id"]
        cur.execute("SELECT count(*) FROM eds_pnr_output WHERE pnr_id=%s",(pid,))
        if cur.fetchone()[0]>0: print(f"  {pid} eds organic OK"); continue
        segs=[f"{pid}-ST-{i+1}" for i in range(len(r["legs"]))]
        bounds=[{"boundRph":1,"origin":r["route"].split("-")[0],"destination":r["route"].split("-")[-1],
          "boundOriginLocation":"OTHER","boundOriginCountry":"OTHER","regimes":["APPR"],
          "promisedSegments":segs,"actualSegments":segs,"originalSegments":segs,
          "promisedWindowStart":f"{r['date']}T00:00:00.000Z",
          "authenticationContactDetails":{"passengers":[{"passengerId":f"{pid}-PT-{i+1}",
            "contacts":{"apn":{"email":EMAIL,"phone":PHONE},"ctc":{"email":"","phone":""},"ape":{"email":"","phone":""}}}
            for i in range(r["npax"])]}}]
        cur.execute("""INSERT INTO eds_pnr_output (id,pnr_id,booking_context,bounds,changes,last_modified,received_at)
                       VALUES (%s,%s,%s,%s,%s,now(),now())""",
                    (str(uuid.uuid4()),pid,BC,json.dumps(bounds),"[]"))
        print(f"  {pid} eds injected")
    ttc.commit(); ttc.close()

def verify(sl):
    ctx=ssl.create_default_context(); ctx.check_hostname=False; ctx.verify_mode=ssl.CERT_NONE
    for r in sl:
        req=urllib.request.Request(B.BAT["endpoint"]+r["pnr_id"],headers={"x-api-key":B.BAT["api_key"]})
        d=json.load(urllib.request.urlopen(req,timeout=25,context=ctx))
        soc=d["socFlightEligibility"]
        pe_ok=all(len(e["passengerEligibility"])==r["npax"] for e in soc)
        codes=[e["passengerEligibility"][0]["systemCode"] for e in soc]
        exp=[l["soc_code"] for l in r["legs"]]
        comp_pe=len(d["compensationEligibility"][0]["passengerEligibility"])
        print(f"  {r['tc']} {r['pnr_id']} socsegs={len(soc)} codes={'OK' if codes==exp else codes} "
              f"soc_pax/seg={'OK' if pe_ok else 'BAD'} comp_pax={comp_pe}/{r['npax']}")

if __name__=="__main__":
    ap=argparse.ArgumentParser(); ap.add_argument("phase"); a=ap.parse_args()
    if a.phase=="gen": gen(); sys.exit()
    dict(publish=publish,finalize=finalize,edsinject=edsinject,verify=verify)[a.phase](load())
