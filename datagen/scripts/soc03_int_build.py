#!/usr/bin/env python3
"""Build SoC-03 (Standards of Care multi-segment) test PNRs in INT.

One PNR per SoC-03 chart column (18 total): 2-seg / 3-seg AC-only, AC+Star,
AC+OAL, Star+Star, OAL+OAL, 3-seg mixed carriers. Booking segments are always
AC-OPERATED (non-AC operating carrier blocks the trip-tracer cascade) but carry
the real MARKETING carrier (LH = Star partner, WS = OAL) — probe-validated
2026-07-03 that non-AC marketing cascades fine. The per-segment SOC verdict
lives in the pinned DDS socFlightEligibility[] (one fully-shaped entry per leg).

SoC role encoding (from rule-engine rules.json + SOC_UAT.md + live RFEUXR shape):
  EL    ELIGIBLE        SoC-APPR-EL-01  controllable 64, 240m, expenseCategories
  NE2H  NOT_ELIGIBLE    SoC-APPR-NE-04  <2h delay (90m)
  NEWX  NOT_ELIGIBLE    SoC-APPR-NE-07  weather uncontrollable, code MATCH (single-factor)
  NEWP  NOT_ELIGIBLE    SoC-APPR-NE-07  weather uncontrollable, code PARTIAL/NO MATCH (multi-factor)
  STAR  NO_DETERMINATION SoC-APPR-ND-02 MSL on Star partner -> agent review
  OALM  NO_DETERMINATION SoC-APPR-ND-01 OAL leg in mixed itinerary -> redirect
  OALO  NOT_ELIGIBLE    SoC-APPR-NE-05  OAL-only itinerary -> redirect

Phases: gen | publish | checkcascade | finalize | verify | report
Usage: AWS_PROFILE not needed; uses int_fd_build session (ARC75-Temp-INT).
"""
import json, os, sys, copy, random, subprocess, argparse, ssl, urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import int_fd_build as B
import crt_uniqnames as U

KB   = os.environ.get("CCTQA_DATAGEN_ROOT",
                      os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
FD   = f"{KB}/scenarios/fd-sit"
IDX  = f"{FD}/_FD_SOC03_int_index.json"
BASE = f"{FD}/CPPCSP-2026-06-15.json"
DATE = "2026-06-15"
TPREFIX = "014311"
EMAIL = "lahiru.premathilake@aircanada.ca"; PHONE = "+94712534323"; DOB = "1986-04-23"
SEED  = 30303

# ---- leg timetable (local times; UTC offsets: YYZ/YUL -4, FRA +2, LHR +1) ----
LEGS = {
 1: dict(origin="YYZ", destination="YUL", fno="123",
         dep_local="2026-06-15T10:00:00", arr_local="2026-06-15T11:30:00",
         dep_utc="2026-06-15T14:00:00Z",  arr_utc="2026-06-15T15:30:00Z"),
 2: dict(origin="YUL", destination="FRA", fno="456",
         dep_local="2026-06-15T15:00:00", arr_local="2026-06-16T04:30:00",
         dep_utc="2026-06-15T19:00:00Z",  arr_utc="2026-06-16T02:30:00Z"),
 3: dict(origin="FRA", destination="LHR", fno="789",
         dep_local="2026-06-16T08:00:00", arr_local="2026-06-16T09:00:00",
         dep_utc="2026-06-16T06:00:00Z",  arr_utc="2026-06-16T08:00:00Z"),
}

EXP_CATS = [
 dict(type="MEAL",          region="CANADA", delayBand="DELAY_2_TO_LT_6_HOURS", currency="CAD", amount=45),
 dict(type="ACCOMMODATION", region="CANADA", delayBand="DELAY_2_TO_LT_6_HOURS", currency="CAD", amount=200),
 dict(type="TRANSPORTATION",region="CANADA", delayBand="DELAY_2_TO_LT_6_HOURS", currency="CAD", amount=60),
]

SOC_ROLES = {
 "EL":   dict(status="ELIGIBLE", code="SoC-APPR-EL-01",
              reason="Controllable disruption — meals and accommodation reimbursable",
              dtyp="CONTROLLABLE", dcode="64", dreason="MECHANICAL",
              friendly="Reasonable meal and hotel expenses are reimbursable.",
              mins=240, cat="DELAY_2_TO_LT_6_HOURS", expiry="2027-12-31", cats=EXP_CATS),
 "NE2H": dict(status="NOT_ELIGIBLE", code="SoC-APPR-NE-04",
              reason="Transit delay below 2-hour threshold",
              dtyp="CONTROLLABLE", dcode="41", dreason="OTHER",
              friendly="Your flight was delayed by less than 2 hours.",
              mins=90, cat="DELAY_LT_2_HOURS", expiry="", cats=[]),
 "NEWX": dict(status="NOT_ELIGIBLE", code="SoC-APPR-NE-07",
              reason="Delay >=2h outside carrier control (weather) — disruption code MATCH",
              dtyp="UNCONTROLLABLE", dcode="77", dreason="WEATHER",
              friendly=("The primary reason was severe weather conditions. Weather and other "
                        "factors outside the airline's control aren't covered under the APPR "
                        "compensation regulations."),
              mins=240, cat="DELAY_2_TO_LT_6_HOURS", expiry="", cats=[]),
 "NEWP": dict(status="NOT_ELIGIBLE", code="SoC-APPR-NE-07",
              reason="Delay >=2h outside carrier control (weather) — disruption code PARTIAL/NO MATCH",
              dtyp="UNCONTROLLABLE", dcode="77", dreason="WEATHER",
              friendly=("There were multiple factors that contributed to the delay, including "
                        "weather and staffing issues. However, we can confirm that the primary "
                        "reason was due to severe weather conditions."),
              mins=240, cat="DELAY_2_TO_LT_6_HOURS", expiry="", cats=[]),
 "STAR": dict(status="NO_DETERMINATION", code="SoC-APPR-ND-02",
              reason="MSL on Star Alliance partner — forwarded to agent for review",
              dtyp="OTHER", dcode="", dreason="", friendly="",
              mins=0, cat="DELAY_LT_2_HOURS", expiry="", cats=[]),
 "OALM": dict(status="NO_DETERMINATION", code="SoC-APPR-ND-01",
              reason="Segment operated by OAL — redirect to operating carrier",
              dtyp="OTHER", dcode="", dreason="", friendly="",
              mins=0, cat="DELAY_LT_2_HOURS", expiry="", cats=[]),
 "OALO": dict(status="NOT_ELIGIBLE", code="SoC-APPR-NE-05",
              reason="OAL-only itinerary — no AC involvement",
              dtyp="OTHER", dcode="", dreason="", friendly="",
              mins=0, cat="DELAY_LT_2_HOURS", expiry="", cats=[]),
}
CARRIER = {"AC": "AC", "ST": "LH", "OA": "WS"}   # role prefix -> marketing carrier

# variant: (id, chart, title, [(carrier_role, soc_role), ...], comp)
VARIANTS = [
 ("SOC03-01","SoC-03b","2seg AC: EL + NE(<2h)",                    [("AC","EL"),("AC","NE2H")],                "EL1"),
 ("SOC03-02","SoC-03b","2seg AC: EL + NE(weather, code MATCH)",    [("AC","EL"),("AC","NEWX")],                "EL1"),
 ("SOC03-03","SoC-03b","2seg AC: EL + NE(weather, PARTIAL/NO MATCH)",[("AC","EL"),("AC","NEWP")],              "EL1"),
 ("SOC03-04","SoC-03b","2seg AC: NE(<2h) + NE(weather PARTIAL)",   [("AC","NE2H"),("AC","NEWP")],              "NEW2"),
 ("SOC03-05","SoC-03b+","3seg AC: EL + EL + EL",                   [("AC","EL"),("AC","EL"),("AC","EL")],      "EL1"),
 ("SOC03-06","SoC-03b+","3seg AC: EL + EL + NE(<2h)",              [("AC","EL"),("AC","EL"),("AC","NE2H")],    "EL1"),
 ("SOC03-07","SoC-03b+","3seg AC: EL + NE(<2h) + NE(weather MATCH)",[("AC","EL"),("AC","NE2H"),("AC","NEWX")], "EL1"),
 ("SOC03-08","SoC-03b+","3seg AC: EL + NE(<2h) + NE(weather PARTIAL)",[("AC","EL"),("AC","NE2H"),("AC","NEWP")],"EL1"),
 ("SOC03-09","SoC-03c","2seg: AC EL + Star(LH)",                   [("AC","EL"),("ST","STAR")],                "EL1"),
 ("SOC03-10","SoC-03c","2seg: AC NE(<2h) + Star(LH)",              [("AC","NE2H"),("ST","STAR")],              "NE1"),
 ("SOC03-11","SoC-03d","2seg: AC EL + OAL(WS)",                    [("AC","EL"),("OA","OALM")],                "EL1"),
 ("SOC03-12","SoC-03d","2seg: AC NE(<2h) + OAL(WS)",               [("AC","NE2H"),("OA","OALM")],              "NE1"),
 ("SOC03-13","SoC-03e","2seg: Star + Star (both LH)",              [("ST","STAR"),("ST","STAR")],              "NDS1"),
 ("SOC03-14","SoC-03g","2seg: OAL + OAL (both WS)",                [("OA","OALO"),("OA","OALO")],              "NEO1"),
 ("SOC03-15","SoC-03h","3seg: AC EL + Star + OAL",                 [("AC","EL"),("ST","STAR"),("OA","OALM")],  "EL1"),
 ("SOC03-16","SoC-03h","3seg: AC NE(<2h) + Star + OAL",            [("AC","NE2H"),("ST","STAR"),("OA","OALM")],"NE1"),
 ("SOC03-17","SoC-03h","3seg: AC EL + AC NE(<2h) + Star",          [("AC","EL"),("AC","NE2H"),("ST","STAR")],  "EL1"),
 ("SOC03-18","SoC-03h","3seg: Star + Star + OAL",                  [("ST","STAR"),("ST","STAR"),("OA","OALM")],"NDS1"),
]
PAX = ["GABRIELLE ROY","ETIENNE MERCIER","CLARA FONTAINE","MATHIS BEAULIEU","JULIETTE LAVOIE",
 "FELIX GAGNON","ROSALIE COTE","THOMAS BERGERON","AMELIE GIRARD","OLIVIER MORIN","CHLOE LEBLANC",
 "SAMUEL FORTIN","EMMA TREMBLAY","WILLIAM BOUCHARD","LEA PELLETIER","NICOLAS GAUTHIER",
 "SOPHIA BELANGER","ANTOINE CARON"]

def shift(iso, mins):
    import datetime
    if iso.endswith("Z"):
        d = datetime.datetime.strptime(iso, "%Y-%m-%dT%H:%M:%SZ")
        return (d + datetime.timedelta(minutes=mins)).strftime("%Y-%m-%dT%H:%M:%SZ")
    d = datetime.datetime.strptime(iso, "%Y-%m-%dT%H:%M:%S")
    return (d + datetime.timedelta(minutes=mins)).strftime("%Y-%m-%dT%H:%M:%S")

def seg_json(pid, i, leg, carrier, mins, actual=False):
    dep, arr = leg["dep_utc"], leg["arr_utc"]
    if actual and mins:
        dep, arr = shift(dep, mins), shift(arr, mins)
    return dict(segmentId=f"{pid}-ST-{i}", segmentStatus="HK",
        departureDatetime=dep.replace("Z","+00:00"), arrivalDatetime=arr.replace("Z","+00:00"),
        departureAirport=leg["origin"], arrivalAirport=leg["destination"],
        marketingFlightNumber=int(leg["fno"]), marketingCarrierCode=carrier,
        operatingFlightNumber=int(leg["fno"]), operatingCarrierCode="AC",
        flightId=f"AC#{leg['fno']}#{DATE}#{leg['origin']}")

def comp_block(pid, comp, legs):
    """comp: EL1 / NE1 / NEW2 / NDS1 / NEO1 — verdict + which leg is MSL."""
    kind, msl_i = {"EL1":("EL",None), "NE1":("NE2H",None), "NEW2":("NEWP",2),
                   "NDS1":("STAR",1), "NEO1":("OALO",1)}[comp]
    if msl_i is None:
        msl_i = next(i for i,(c,r) in enumerate(legs,1) if r==kind) if any(r==kind for c,r in legs) else 1
    car, role = legs[msl_i-1]
    leg = LEGS[msl_i]; R = SOC_ROLES[role]
    m = dict(segmentId=f"{pid}-ST-{msl_i}", carrierCode=CARRIER[car], flightNumber=leg["fno"],
             departureAirport=leg["origin"], arrivalAirport=leg["destination"],
             isStarSegment=(car=="ST"), isOalSegment=(car=="OA"))
    pax = dict(passengerId=f"{pid}-PT-1", passengerType="ADT")
    if comp=="EL1":
        pax.update(eligibilityStatus="ELIGIBLE", systemCode="FD-APPR-EL-400",
                   reason="arrival delay within carrier control",
                   compensationDetails=dict(amount=400,currency="CAD",
                        delayBand="DELAY_3_TO_LT_6_HOURS", expiryDate="2027-06-15"))
        head=dict(disruptionType="INVOLUNTARY", delayMinutes=240, delayType="CONTROLLABLE",
                  delayCode="64", disruptionReason="MECHANICAL",
                  customerFriendlyDisruptionReason="Your flight arrived more than 3 hours late due to a reason within Air Canada's control.")
    elif comp=="NE1":
        pax.update(eligibilityStatus="NOT_ELIGIBLE", systemCode="FD-APPR-NE-26",
                   reason="arrival delay below 3 hours",
                   compensationDetails=dict(amount=0,currency="CAD",delayBand="NOT_APPLICABLE"))
        head=dict(disruptionType="INVOLUNTARY", delayMinutes=90, delayType="CONTROLLABLE",
                  delayCode="41", disruptionReason="OTHER",
                  customerFriendlyDisruptionReason="Your flight was disrupted.")
    elif comp=="NEW2":
        pax.update(eligibilityStatus="NOT_ELIGIBLE", systemCode="FD-APPR-NE-08",
                   reason="uncontrollable disruption (weather)",
                   compensationDetails=dict(amount=0,currency="CAD",delayBand="NOT_APPLICABLE"))
        head=dict(disruptionType="INVOLUNTARY", delayMinutes=240, delayType="UNCONTROLLABLE",
                  delayCode="WEAT", disruptionReason="WEATHER",
                  customerFriendlyDisruptionReason="Your flight was disrupted by weather.")
    elif comp=="NDS1":
        pax.update(eligibilityStatus="NO_DETERMINATION", systemCode="FD-APPR-ND-02",
                   compensationDetails=dict(amount=0,currency="CAD",delayBand="NOT_APPLICABLE"))
        head=dict(disruptionType="INVOLUNTARY", delayMinutes=240, delayType="OTHER",
                  delayCode="OAL", disruptionReason="MECHANICAL",
                  customerFriendlyDisruptionReason="Your flight was disrupted.")
    else:  # NEO1
        pax.update(eligibilityStatus="NOT_ELIGIBLE", systemCode="FD-APPR-NE-05",
                   reason="All-OAL itinerary — no AC involvement",
                   compensationDetails=dict(amount=0,currency="CAD",delayBand="NOT_APPLICABLE"))
        head=dict(disruptionType="INVOLUNTARY", delayMinutes=240, delayType="OTHER",
                  delayCode="OAL", disruptionReason="MECHANICAL",
                  customerFriendlyDisruptionReason="Your flight was disrupted.")
    out=dict(regime="APPR", boundRph=1, mslFlight=m, **head, passengerEligibility=[pax])
    return out

def dds_json(pid, loc, legs, comp):
    segsP=[seg_json(pid,i,LEGS[i],CARRIER[c],0,False) for i,(c,r) in enumerate(legs,1)]
    segsA=[seg_json(pid,i,LEGS[i],CARRIER[c],SOC_ROLES[r]["mins"],True) for i,(c,r) in enumerate(legs,1)]
    soc=[]
    for i,(c,r) in enumerate(legs,1):
        R=SOC_ROLES[r]; leg=LEGS[i]
        soc.append(dict(regime="APPR", boundRph=1, segmentId=f"{pid}-ST-{i}",
            carrierCode=CARRIER[c], flightNumber=int(leg["fno"]),
            departureAirport=leg["origin"], arrivalAirport=leg["destination"],
            segmentStatus="HK", disruptionType="INVOLUNTARY",
            delayType=R["dtyp"], delayCode=R["dcode"], disruptionReason=R["dreason"],
            customerFriendlyDisruptionReason=R["friendly"],
            delayMinutes=R["mins"], delayCategory=R["cat"],
            passengerEligibility=[dict(passengerId=f"{pid}-PT-1", passengerType="ADT",
                bookingClass=None, cabinClass="ECONOMY",
                eligibilityStatus=R["status"], systemCode=R["code"], reason=R["reason"],
                expiryDate=R["expiry"], expenseCategories=R["cats"])]))
    na=lambda reg,code:dict(regime=reg,boundRph=1,passengerEligibility=[dict(
        passengerId=f"{pid}-PT-1",passengerType="ADT",eligibilityStatus="NOT_ELIGIBLE",
        systemCode=code,compensationDetails=dict(amount=0,currency="CAD",delayBand="NOT_APPLICABLE"))])
    return dict(
        eventMetadata=dict(trigger="DISRUPTION_DETECTION_SERVICE", timestamp=f"{DATE}T09:05:34.000Z"),
        pnrIdentifier=dict(pnrId=pid, pnr=loc),
        itineraryDetails=[dict(bound=1, boundRph=1, isOAL=all(c!="AC" for c,_ in legs),
            promisedItinerary=dict(origin=legs and LEGS[1]["origin"], destination=LEGS[len(legs)]["destination"], associatedSegments=segsP),
            actualItinerary=dict(origin=LEGS[1]["origin"], destination=LEGS[len(legs)]["destination"], associatedSegments=segsA))],
        compensationEligibility=[comp_block(pid,comp,legs), na("EU","FD-EU-NA-01"), na("ASL","FD-ASL-NA-01")],
        socFlightEligibility=soc,
        seatFeeRefundEligibility=[])

def gen():
    base=json.load(open(BASE))
    taken=set()
    import glob
    for f in glob.glob(f"{FD}/_FD_*index.json"):
        try:
            for e in json.load(open(f)):
                if e.get("pnr_id"): taken.add(e["pnr_id"][:6])
        except Exception: pass
    locs=B.gen_locators(len(VARIANTS), SEED, taken)
    recs=[]
    UNIQ=os.environ.get("CRT_UNIQ_NAMES")=="1"       # opt-in unique passenger names
    urecs=[{"npax":1} for _ in VARIANTS]             # SoC-03 PNRs are single-passenger
    if UNIQ:
        _c=B.tt_conn()
        try: U.assign_names(urecs, lambda r:r["npax"], _c, seed=911001)
        finally: _c.close()
    for i,((vid,chart,title,legs,comp),name) in enumerate(zip(VARIANTS,PAX)):
        loc=locs[i]; pid=f"{loc}-{DATE}"
        fn,ln=name.split(" ",1)
        if UNIQ:
            name=urecs[i]["pax"]; fn,ln=urecs[i]["pax_names"][0]
        s=copy.deepcopy(base)
        s["scenario_id"]=pid; s["identity"]["pnr"]=loc; s["identity"]["booking_date"]=DATE
        s["title"]=f"{vid} {chart}: {title} - {name} [{loc}]"
        s["description"]=f"{vid} | {chart} | {title}"
        s["creation_comment"]=s["last_modification_comment"]=f"SIM-{vid}-INT"
        s["ticketing"]["ticket_numbers"]=[f"{TPREFIX}{i+1:06d}1"[:13]]
        s["classification"]=dict(primary_code=vid, primary_name=f"SoC-03 {chart} INT", confidence="high")
        s["tags"]=["synthetic","soc03",chart.lower().replace("+","x")]
        s["passengers"]=[dict(type="ADT",first_name=fn,last_name=ln,gender="U",
            date_of_birth=DOB,email=EMAIL,phone=PHONE)]
        segs=[]
        for j,(c,r) in enumerate(legs,1):
            leg=LEGS[j]
            segs.append(dict(carrier=CARRIER[c], operating_carrier="AC",
                flight_number=leg["fno"], operating_flight_number=leg["fno"],
                origin=leg["origin"], destination=leg["destination"],
                dep_local=leg["dep_local"], arr_local=leg["arr_local"],
                dep_utc=leg["dep_utc"], arr_utc=leg["arr_utc"],
                booking_datetime=None, aircraft="320", cabin="Y", status="HK",
                arrival_terminal="1"))
        s["segments"]=segs
        s["expected_cascade"]["db_end_state"]["trip"].update(pnr=loc,pnr_id=pid)
        s["expected_cascade"]["db_end_state"]["flight_segment"]["rows"]=len(segs)
        json.dump(s, open(f"{B.SCENW}/{pid}.json","w"), indent=1)
        json.dump(s, open(f"{FD}/{pid}.json","w"), indent=1)
        d=dds_json(pid,loc,legs,comp)
        json.dump(d, open(f"{B.DDSW}/{pid}.dds.json","w"), indent=1)
        json.dump(d, open(f"{FD}/_dds-templates/{pid}.dds.json","w"), indent=1)
        route="-".join([LEGS[1]["origin"]]+[LEGS[j]["destination"] for j in range(1,len(legs)+1)])
        comp0=d["compensationEligibility"][0]["passengerEligibility"][0]
        recs.append(dict(tc=vid, chart=chart, title=title, loc=loc, pnr_id=pid, date=DATE,
            ticket=s["ticketing"]["ticket_numbers"][0], pax=name, route=route,
            legs=[dict(n=j+0, carrier=CARRIER[c], flight=f"{CARRIER[c]}{LEGS[j]['fno']}",
                       sector=f"{LEGS[j]['origin']}-{LEGS[j]['destination']}",
                       soc_status=SOC_ROLES[r]["status"], soc_code=SOC_ROLES[r]["code"], role=r)
                  for j,(c,r) in enumerate(legs,1)],
            status=comp0["eligibilityStatus"], syscode=comp0["systemCode"],
            amount=comp0.get("compensationDetails",{}).get("amount",0), currency="CAD",
            email=EMAIL, phone=PHONE, pin=True, group=False))
        if UNIQ:
            recs[-1]["pax_names"]=urecs[i]["pax_names"]; recs[-1]["uniq_names"]=True
    json.dump(recs, open(IDX,"w"), indent=1)
    print(f"[gen] {len(recs)} scenarios+DDS written; index -> {IDX}")

def load(): return json.load(open(IDX))

def publish(sl):
    ok=0
    for i,r in enumerate(sl):
        good,log=B.render_publish_one(r)
        ok+=good; print(f"  [{i}] {r['pnr_id']} {'OK' if good else 'FAIL '+log[-160:]}",flush=True)
    print(f"[publish] {ok}/{len(sl)}")

def finalize(sl):
    ttc=B.tt_conn(); keys={}
    for r in sl:
        cur=ttc.cursor(); pid=r["pnr_id"]; tk=r["ticket"]
        cur.execute("""insert into ticket
            (primary_document_number,pnr_id,passenger_id,ticket_id,document_numbers,issuance_local_date,document_type)
            values (%s,%s,%s,%s,ARRAY[%s],%s,'T') on conflict do nothing""",
            (tk,pid,f"{pid}-PT-1",f"{tk}-2026-06-01",tk,"2026-06-01"))
        cur.execute("update passenger set date_of_birth=%s where pnr_id=%s",(DOB,pid))
        ttc.commit()
        key=f"traces/DDS/{r['date']}/{pid}/response.json"
        body=open(f"{B.DDSW}/{pid}.dds.json","rb").read()
        B._sess.client("s3").put_object(Bucket=B.BAT["s3_bucket"],Key=key,Body=body,ContentType="application/json")
        keys[pid]=key; print(f"  {pid} ticket+DOB+S3 ok",flush=True)
    ttc.close()
    n=B.pin_all(sl,keys)
    print(f"[finalize] done; pinned {n}")

def verify(sl):
    ctx=ssl.create_default_context(); ctx.check_hostname=False; ctx.verify_mode=ssl.CERT_NONE
    ok=0
    for r in sl:
        req=urllib.request.Request(B.BAT["endpoint"]+r["pnr_id"],headers={"x-api-key":B.BAT["api_key"]})
        try:
            d=json.load(urllib.request.urlopen(req,timeout=25,context=ctx))
        except Exception as e:
            print(f"  {r['tc']} {r['pnr_id']} FETCH FAIL {e}"); continue
        soc=d.get("socFlightEligibility",[])
        exp=r["legs"]; bad=[]
        if len(soc)!=len(exp): bad.append(f"soc segs {len(soc)}!={len(exp)}")
        for e_,s_ in zip(exp,soc):
            pe=s_["passengerEligibility"][0]
            if pe["systemCode"]!=e_["soc_code"]: bad.append(f"seg{e_['n']} {pe['systemCode']}!={e_['soc_code']}")
            if s_["carrierCode"]!=e_["carrier"]: bad.append(f"seg{e_['n']} carrier {s_['carrierCode']}!={e_['carrier']}")
        comp0=d["compensationEligibility"][0]["passengerEligibility"][0]
        if comp0["systemCode"]!=r["syscode"]: bad.append(f"comp {comp0['systemCode']}!={r['syscode']}")
        if bad: print(f"  {r['tc']} {r['pnr_id']} BAD: {bad}")
        else: ok+=1; print(f"  {r['tc']} {r['pnr_id']} OK ({len(exp)} segs)")
    print(f"[verify] {ok}/{len(sl)} fully match")

def checkcascade(sl):
    ttc=B.tt_conn(); cur=ttc.cursor()
    pids=[r["pnr_id"] for r in sl]
    cur.execute("select pnr_id,count(*) from flight_segment where pnr_id=any(%s) group by pnr_id",(pids,))
    seg={a:b for a,b in cur.fetchall()}
    cur.execute("select pnr_id,count(*) from eds_pnr_output where pnr_id=any(%s) group by pnr_id",(pids,))
    eds={a:b for a,b in cur.fetchall()}
    for r in sl:
        want=len(r["legs"])
        print(f"  {r['tc']} {r['pnr_id']} segs={seg.get(r['pnr_id'],0)}/{want} eds={eds.get(r['pnr_id'],0)}")
    ttc.close()

if __name__=="__main__":
    ap=argparse.ArgumentParser(); ap.add_argument("phase")
    ap.add_argument("--start",type=int,default=0); ap.add_argument("--end",type=int,default=99)
    a=ap.parse_args()
    if a.phase=="gen": gen(); sys.exit()
    sl=load()[a.start:a.end]
    dict(publish=publish, finalize=finalize, verify=verify, checkcascade=checkcascade)[a.phase](sl)