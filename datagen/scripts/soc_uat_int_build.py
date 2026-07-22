#!/usr/bin/env python3
"""Build ONE live INT PNR per SOC_UAT.xlsx test case (84 cases, APPR/EU/ASL + overrides).

Semantics derive from the requirement code (SoC-{REG}-{EL|NE|ND|PE}-NN) + the LIVE
rule-engine reason lookup; routes/flights/delays/codes are parsed from the workbook
Prerequisites column where present, with regime-appropriate defaults.

Modeling rules (all proven on prior sets):
  booking      always AC-OPERATED; real MARKETING carrier (LH=Star, WS/UA=OAL)
  soc block    one socFlightEligibility entry per segment, regime per case;
               affected segment carries the case verdict (exact SoC code + live
               lookup reason); unaffected segments get SoC-{REG}-NE-04 @ 0 min
  comp block   primary regime entry mirroring the SOC class (EL w/ amount; NE/ND/PE
               w/ lookup reason, NO compensationDetails, failureReasons:null) + 2 NA stubs
  no-travel    booking/actual unchanged (HK) — verdict rides in DDS (200-set precedent);
               delayCategory NO_TRAVEL on the SOC entry
  employee     office_id suffix ES (AC) — lookup 'Employee Office ID Suffixes'
  exception    FQTV loyalty inject (Super Elite modeled via DDS EL-07 verdict)
  PE cases     flight date = yesterday (<72h);  outside-limitation = flight 2023
Phases: gen | publish | checkcascade | finalize | edsinject | verify
Email/phone: lahiru.premathilake@aircanada.ca / +94712534323 (per request).
"""
import json, os, sys, copy, re, argparse, ssl, uuid, datetime, urllib.request
import openpyxl

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import int_fd_build as B
import crt_uniqnames as U

KB   = os.environ.get("CCTQA_DATAGEN_ROOT",
                      os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
FD=f"{KB}/scenarios/fd-sit"; DDST=f"{FD}/_dds-templates"
XLSX="/Users/chathuranga/Downloads/SOC_UAT.xlsx"
LIVE=f"{KB}/scripts/_live_tables_cache.json"   # durable cache of GET /rule-engine/reference/tables
BASE=f"{FD}/CPPCSP-2026-06-15.json"
EMAIL="lahiru.premathilake@aircanada.ca"; PHONE="+94712534323"; DOB="1986-04-23"
# --tag selects the set: "" = original SOCUAT84 (tickets 014350); A..E = clone sets
SET_TAGS={"":("014350",848484), "A":("014351",848485), "B":("014352",848486),
          "C":("014353",848487), "D":("014354",848488), "E":("014355",848489)}
TAG=""; TPREFIX="014350"; SEED=848484
IDX=f"{FD}/_FD_SOCUAT84_int_index.json"
def set_tag(tag):
    global TAG,TPREFIX,SEED,IDX
    TAG=tag; TPREFIX,SEED=SET_TAGS[tag]
    IDX=f"{FD}/_FD_SOCUAT84{tag}_int_index.json"
DATE="2026-06-20"; DATE_PE=(datetime.date.today()-datetime.timedelta(days=1)).isoformat()  # PE = flight yesterday (<72h)
DATE_OLD="2023-06-20"

# ---- live lookups -----------------------------------------------------------
_lt=json.load(open(LIVE)); _tabs=_lt.get("tables",_lt)
LOOK={}   # code -> reason value (both FD- and SoC- families)
for t in _tabs:
    if "Reason Codes" in t.get("name",""):
        for r in t.get("data",t.get("rows",[])):
            k=r.get("key") or r.get("code"); v=r.get("value","")
            if k: LOOK[k]=v
def soc_reason(code): return LOOK.get(code, code)
def fd_match(reg, soc_code):
    """closest FD comp code for a SoC verdict: same reason value, else family default."""
    val=LOOK.get(soc_code,"")
    st=re.search(r"-(NE|ND|PE)-",soc_code).group(1)
    for k,v in LOOK.items():
        if k.startswith(f"FD-{reg}-{st}-") and v==val: return k
    if st=="ND":
        if "OAL" in val and "Disruption" in val: return f"FD-{reg}-ND-01"
        if "STAR" in val: return f"FD-{reg}-ND-02"
        return f"FD-{reg}-ND-04"
    if st=="PE": return f"FD-{reg}-PE-01"
    # keyword-overlap fallback across the FD-{reg}-NE family (avoids the wrong
    # 'Employee booking' default for delay/weather/territorial cases)
    vt=set(re.findall(r"[a-z]+", val.lower()))
    best,score=None,0
    for k,v in LOOK.items():
        if not k.startswith(f"FD-{reg}-NE-"): continue
        s=len(vt & set(re.findall(r"[a-z]+", v.lower())))
        if s>score: best,score=k,s
    return best if best and score>=2 else f"FD-{reg}-ND-04"

# ---- workbook ----------------------------------------------------------------
# v2 workbook "SOC_UAT (1).xlsx" (2026-07-13) inserts a TestData_Test Case ID column
# and renumbers Test Case ID sequentially; the SoC-* requirement moved to col 3.
# Autodetect layout; prefer the v2 file when present. v2 drops old 018/019/090 (81 cases).
XLSX_V2="/Users/chathuranga/Downloads/SOC_UAT (1).xlsx"
if os.path.exists(XLSX_V2): XLSX=XLSX_V2
wb=openpyxl.load_workbook(XLSX, read_only=True, data_only=True)
rows=list(wb["Test Cases"].iter_rows(values_only=True))
_hdr=[str(h or "") for h in rows[0]]
CASES=[]
V2=_hdr[0].startswith("TestData_")
for r in rows[1:]:
    if not r[0]: continue
    if V2:
        CASES.append(dict(id=str(r[1]).strip(), old_id=str(r[0]).strip(),
                          req=str(r[2] or "").strip(), name=str(r[3] or "").strip(),
                          pre=str(r[6] or "").strip()))
    else:
        CASES.append(dict(id=str(r[0]).strip(), old_id=str(r[0]).strip(),
                          req=str(r[1] or "").strip(),
                          name=str(r[2] or "").strip(), pre=str(r[5] or "").strip()))

FLIGHT_RE=re.compile(r"\b([A-Z]{2})\s?(\d{2,4})\s+([A-Z]{3})\s*(?:→|->)\s*([A-Z]{3})")
DELAY_RE=re.compile(r"Delay(?:\s*Length)?:?\s*(\d+)\s*min", re.I)
CODE_RE=re.compile(r"delay code:?\s*(\d+)", re.I)

STAR_CARR={"LH","LX","OS","SN","TP","TG","NH","UA"}  # UA is Star but treated OAL in AC UAT sheets
DEF_ROUTE={"APPR":("AC","301","YYZ","YVR"), "EU":("AC","848","LHR","YYZ"), "ASL":("AC","085","TLV","YYZ")}

def regime(req):
    m=re.match(r"SoC-(APPR|EU|ASL)",req); return m.group(1) if m else "APPR"
def status(req):
    m=re.search(r"-(EL|NE|ND|PE)-",req); return m.group(1) if m else "EL"   # overrides -> EL

def derive(c):
    """case -> config dict"""
    req=c["req"]; reg=regime(req); st=status(req)
    is_override=req.startswith("SoC-Override")
    soc_code=req if not is_override else "SoC-APPR-EL-08"
    val=soc_reason(soc_code) if not is_override else soc_reason("SoC-APPR-EL-08")
    pre=c["pre"]
    # route/flight from prereq (first flight token) else default
    m=FLIGHT_RE.search(pre)
    carr,fno,orig,dest = m.groups() if m else DEF_ROUTE[reg]
    # regime sanity: EU must start in EU/UK unless testing 'did not start in EU/UK'
    if reg=="EU" and "did not start" in val.lower(): carr,fno,orig,dest=("AC","849","YYZ","LHR")
    if reg=="ASL" and "did not start in israel" in val.lower(): carr,fno,orig,dest=("AC","084","YYZ","TLV")
    if reg=="ASL" and "did not end in israel" in val.lower():  carr,fno,orig,dest=("AC","085","TLV","FRA")
    dm=DELAY_RE.search(pre); delay=int(dm.group(1)) if dm else None
    cm=CODE_RE.search(pre);  code=cm.group(1) if cm else None
    v=val.lower()
    notravel="no travel" in v or "cancelled" in v
    if "below 2 hours" in v: delay=delay or 90
    elif "below 3 hours" in v: delay=delay or 150
    elif notravel: delay=0
    else: delay=delay if delay is not None else 420
    # controllability / code (rule tables: 64/42 controllable, 77 uncontrollable, 41 safety)
    if "outside carrier control" in v: dtyp,dcode,dreas="UNCONTROLLABLE",(code if code in("71","77","72") else "77"),"WEATHER"
    elif "safety" in v: dtyp,dcode,dreas="SAFETY","41","MECHANICAL"
    else: dtyp,dcode,dreas="CONTROLLABLE",(code if code in("64","42") else "64"),"MECHANICAL"
    # employee/exception/OAL/STAR
    emp_ac = "employee booking ac" in v; emp_oal="employee booking oal" in v
    exc    = "special customer" in v
    is_star= "disruption on star" in v            # NOT plain "star" — matches "did not START in EU"
    is_oal = "disruption on oal" in v or "oal itinerary" in v or "all oal" in v or "oal data" in v or emp_oal
    if is_star and carr=="AC": carr="LH"; fno="470"
    elif is_oal and carr=="AC": carr="WS"          # keep workbook-parsed carriers (UA/LH/WS)
    # dates
    date=DATE
    if st=="PE": date=DATE_PE
    if "outside limitation" in v: date=DATE_OLD
    # delay category
    if notravel: cat="NO_TRAVEL"
    elif delay<120: cat="DELAY_LT_2_HOURS"
    elif delay<360: cat="DELAY_2_TO_LT_6_HOURS"
    elif delay<720: cat="DELAY_6_TO_LT_12_HOURS"
    else: cat="DELAY_12_TO_LT_24_HOURS"
    # currency by regime (UK origin -> GBP)
    curr={"APPR":"CAD","EU":("GBP" if orig in("LHR","LGW","MAN") else "EUR"),"ASL":"ILS"}[reg]
    region={"APPR":"CANADA","EU":"EU","ASL":"ISRAEL"}[reg]
    # comp mirror
    if st=="EL" or is_override:
        if reg=="APPR": amt=400 if delay<360 else (700 if delay<540 else 1000); fdc=f"FD-APPR-EL-{amt}"
        elif reg=="EU": amt=520 if curr=="GBP" else 600; fdc="FD-EU-EL-01"
        else: amt=3670; fdc="FD-ASL-EL-01"
        comp=dict(code=fdc, status="ELIGIBLE", amount=amt, currency=curr)
    else:
        comp=dict(code=fd_match(reg,soc_code), status={"NE":"NOT_ELIGIBLE","ND":"NO_DETERMINATION","PE":"PENDING"}[st],
                  amount=0, currency=curr)
    ent=[]
    if st=="EL" or is_override:
        limited = "required for safety" in v and "within" in v and delay<360   # EL-09 style
        ent=[("MEAL",30),("COMMUNICATION",30)] if limited else \
            [("MEAL",30),("ACCOMMODATION",500),("TRANSPORTATION",200),("COMMUNICATION",30),("PARKING",50),("ESSENTIALS",30)]
    return dict(reg=reg, st=st, soc_code=soc_code, soc_val=soc_reason(soc_code),
                carr=carr, fno=fno, orig=orig, dest=dest, delay=delay, dtyp=dtyp, dcode=dcode,
                dreas=dreas, cat=cat, date=date, comp=comp, ent=ent, curr=curr, region=region,
                emp=emp_ac, emp_oal=emp_oal, exc=exc, star=is_star,
                oal=(carr not in("AC","LH") ), notravel=notravel, override=is_override)

PAXF=["GABRIELLE","ETIENNE","CLARA","MATHIS","JULIETTE","FELIX","ROSALIE","THOMAS","AMELIE","OLIVIER",
      "CHLOE","SAMUEL","EMMA","WILLIAM","LEA","NICOLAS","SOPHIA","ANTOINE","CAMILLE","HUGO","MAEVA",
      "RAPHAEL","ZOE","LUCAS","ELODIE","GABRIEL","MARILOU","XAVIER","OCEANE","JULIEN"]
PAXL=["ROY","MERCIER","FONTAINE","BEAULIEU","LAVOIE","GAGNON","COTE","BERGERON","GIRARD","MORIN",
      "LEBLANC","FORTIN","TREMBLAY","BOUCHARD","PELLETIER","GAUTHIER","BELANGER","CARON","DUBE",
      "LANDRY","POIRIER","THIBAULT","CLOUTIER","NADEAU","LEFEBVRE","BOIVIN","PARADIS","SIMARD"]

def paxname(i): return f"{PAXF[i%len(PAXF)]} {PAXL[(i//len(PAXF)+i)%len(PAXL)]}"

def times(date):
    return (f"{date}T10:00:00", f"{date}T14:00:00", f"{date}T14:00:00Z", f"{date}T18:00:00Z")

def gen():
    base=json.load(open(BASE))
    import glob, random
    taken=set()
    for f in glob.glob(f"{FD}/_FD_*index.json"):
        try:
            for e in json.load(open(f)):
                if e.get("pnr_id"): taken.add(e["pnr_id"][:6])
        except Exception: pass
    locs=B.gen_locators(len(CASES), SEED, taken)
    recs=[]
    UNIQ=os.environ.get("CRT_UNIQ_NAMES")=="1"       # opt-in unique passenger names
    urecs=[{"npax":1} for _ in CASES]                # one passenger per SOC-UAT PNR
    if UNIQ:
        _c=B.tt_conn()
        try: U.assign_names(urecs, lambda r:r["npax"], _c, seed=911002)
        finally: _c.close()
    for i,c in enumerate(CASES):
        cfg=derive(c); loc=locs[i]; pid=f"{loc}-{cfg['date']}"; name=paxname(i)
        fn,ln=name.split(" ",1)
        if UNIQ:
            name=urecs[i]["pax"]; fn,ln=urecs[i]["pax_names"][0]
        dep_l,arr_l,dep_u,arr_u=times(cfg["date"])
        s=copy.deepcopy(base)
        s["scenario_id"]=pid; s["identity"]["pnr"]=loc; s["identity"]["booking_date"]=cfg["date"]
        s["title"]=f"{c['id']} {c['req']}: {c['name'][:60]} - {name} [{loc}]"
        s["description"]=f"{c['id']} | {c['req']} | {cfg['soc_val']}"
        s["creation_comment"]=s["last_modification_comment"]=f"SIM-{c['id']}-INT"
        s["ticketing"]["ticket_numbers"]=[f"{TPREFIX}{i+1:06d}1"[:13]]
        s["classification"]=dict(primary_code=c["id"], primary_name=f"SOC UAT {c['req']}", confidence="high")
        s["tags"]=["synthetic","soc-uat",cfg["reg"].lower(),cfg["st"].lower()]
        s["passengers"]=[dict(type="ADT",first_name=fn,last_name=ln,gender="U",
                              date_of_birth=DOB,email=EMAIL,phone=PHONE)]
        if cfg["emp"]:
            s["point_of_sale"]=dict(s["point_of_sale"]); s["point_of_sale"]["office_id"]="YULAC01ES"
        s["segments"]=[dict(carrier=cfg["carr"], operating_carrier="AC",
            flight_number=cfg["fno"], operating_flight_number=cfg["fno"],
            origin=cfg["orig"], destination=cfg["dest"],
            dep_local=dep_l, arr_local=arr_l, dep_utc=dep_u, arr_utc=arr_u,
            booking_datetime=None, aircraft="789", cabin="Y", status="HK", arrival_terminal="1")]
        if cfg["exc"]:
            loy=[{"type":"loyaltyRequest","id":f"{pid}-OT-300","code":"FQTV",
                  "serviceProvider":{"code":"AC"},
                  "membership":{"number":f"9161{i+1:05d}","membershipType":"INDIVIDUAL"},
                  "status":"HK",
                  "traveler":{"type":"stakeholder","id":f"{pid}-PT-1","ref":"processedPnr.travelers"}}]
            ev=next((t for t in s.get("timeline",[]) if t.get("version")==1),None)
            if ev is not None: ev.setdefault("overrides",{})["/loyaltyRequests"]=loy
        s["expected_cascade"]["db_end_state"]["trip"].update(pnr=loc,pnr_id=pid)
        s["expected_cascade"]["db_end_state"]["flight_segment"]["rows"]=1
        json.dump(s,open(f"{B.SCENW}/{pid}.json","w"),indent=1)
        json.dump(s,open(f"{FD}/{pid}.json","w"),indent=1)
        d=dds(pid,loc,cfg)
        json.dump(d,open(f"{B.DDSW}/{pid}.dds.json","w"),indent=1)
        json.dump(d,open(f"{DDST}/{pid}.dds.json","w"),indent=1)
        recs.append(dict(tc=c["id"], req=c["req"], title=c["name"], loc=loc, pnr_id=pid, date=cfg["date"],
            ticket=s["ticketing"]["ticket_numbers"][0], pax=name, route=f"{cfg['orig']}-{cfg['dest']}",
            flight=f"{cfg['carr']}{cfg['fno']}", regime=cfg["reg"], soc_status_class=cfg["st"],
            legs=[dict(n=1, carrier=cfg["carr"], flight=f"{cfg['carr']}{cfg['fno']}",
                       sector=f"{cfg['orig']}-{cfg['dest']}",
                       soc_status={"EL":"ELIGIBLE","NE":"NOT_ELIGIBLE","ND":"NO_DETERMINATION","PE":"PENDING"}[cfg["st"]],
                       soc_code=cfg["soc_code"], role=cfg["st"])],
            status=cfg["comp"]["status"], syscode=cfg["comp"]["code"],
            amount=cfg["comp"]["amount"], currency=cfg["comp"]["currency"],
            delay=cfg["delay"], dcode=cfg["dcode"], dtyp=cfg["dtyp"], cat=cfg["cat"],
            emp=cfg["emp"], exc=cfg["exc"], override=cfg["override"],
            email=EMAIL, phone=PHONE, pin=True, group=False,
            claim_exempt=bool(cfg["date"]<"2024-01-01")))   # outside-limitation cases fly OLD by design
        if UNIQ:
            recs[-1]["pax_names"]=urecs[i]["pax_names"]; recs[-1]["uniq_names"]=True
    json.dump(recs,open(IDX,"w"),indent=1)
    print(f"[gen] {len(recs)} scenarios+DDS -> {IDX}")

def dds(pid,loc,cfg):
    dep=f"{cfg['date']}T14:00:00+00:00"; arr=f"{cfg['date']}T18:00:00+00:00"
    def seg(actual=False):
        d2,a2=dep,arr
        if actual and cfg["delay"] and not cfg["notravel"]:
            dt=datetime.datetime.fromisoformat(dep)+datetime.timedelta(minutes=cfg["delay"])
            at=datetime.datetime.fromisoformat(arr)+datetime.timedelta(minutes=cfg["delay"])
            d2,a2=dt.isoformat(),at.isoformat()
        return dict(segmentId=f"{pid}-ST-1",segmentStatus="HK",
            departureDatetime=d2,arrivalDatetime=a2,
            departureAirport=cfg["orig"],arrivalAirport=cfg["dest"],
            marketingFlightNumber=int(cfg["fno"]),marketingCarrierCode=cfg["carr"],
            operatingFlightNumber=int(cfg["fno"]),operatingCarrierCode="AC",
            flightId=f"AC#{cfg['fno']}#{cfg['date']}#{cfg['orig']}")
    st=cfg["st"]; socstat={"EL":"ELIGIBLE","NE":"NOT_ELIGIBLE","ND":"NO_DETERMINATION","PE":"PENDING"}[st]
    cats=[dict(type=t,region=cfg["region"],delayBand=cfg["cat"],currency=cfg["curr"],amount=a) for t,a in cfg["ent"]]
    friendly={"EL":"Reasonable meal and hotel expenses are reimbursable.",
              "NE":("The delay was caused by factors outside the airline's control and is not covered."
                    if cfg["dtyp"]=="UNCONTROLLABLE" else "Based on the applicable regulations, this disruption is not eligible for expense reimbursement."),
              "ND":"","PE":""}[st]
    soc=[dict(regime=cfg["reg"],boundRph=1,segmentId=f"{pid}-ST-1",
        carrierCode=cfg["carr"],flightNumber=int(cfg["fno"]),
        departureAirport=cfg["orig"],arrivalAirport=cfg["dest"],segmentStatus="HK",
        disruptionType="INVOLUNTARY",delayType=cfg["dtyp"],delayCode=cfg["dcode"],
        disruptionReason=cfg["dreas"],customerFriendlyDisruptionReason=friendly,
        delayMinutes=cfg["delay"],delayCategory=cfg["cat"],
        passengerEligibility=[dict(passengerId=f"{pid}-PT-1",passengerType="ADT",
            bookingClass=None,cabinClass="ECONOMY",eligibilityStatus=socstat,
            systemCode=cfg["soc_code"],reason=cfg["soc_val"],
            expiryDate=("2027-12-31" if st=="EL" else ""),expenseCategories=cats,
            failureReasons=None)])]
    msl=dict(segmentId=f"{pid}-ST-1",carrierCode=cfg["carr"],flightNumber=cfg["fno"],
             departureAirport=cfg["orig"],arrivalAirport=cfg["dest"],
             isStarSegment=bool(cfg["star"]),isOalSegment=bool(cfg["oal"]))
    cpe=dict(passengerId=f"{pid}-PT-1",passengerType="ADT",
             eligibilityStatus=cfg["comp"]["status"],systemCode=cfg["comp"]["code"],
             reason=LOOK.get(cfg["comp"]["code"], cfg["soc_val"]),failureReasons=None)
    if cfg["comp"]["status"]=="ELIGIBLE":
        band={"CAD":"DELAY_3_TO_LT_6_HOURS" if cfg["comp"]["amount"]==400 else ("DELAY_6_TO_LT_9_HOURS" if cfg["comp"]["amount"]==700 else "DELAY_9_HOURS_OR_MORE"),
              "EUR":"DELAY_4_HOURS_OR_MORE","GBP":"DELAY_4_HOURS_OR_MORE","ILS":"DELAY_8_HOURS_OR_MORE"}[cfg["comp"]["currency"]]
        cpe["compensationDetails"]=dict(amount=cfg["comp"]["amount"],currency=cfg["comp"]["currency"],
                                        delayBand=band,expiryDate="2027-12-31")
    comp=dict(regime=cfg["reg"],boundRph=1,mslFlight=msl,disruptionType="INVOLUNTARY",
              delayMinutes=cfg["delay"],delayType=cfg["dtyp"],delayCode=cfg["dcode"],
              customerFriendlyDisruptionReason=friendly or "Your flight was disrupted.",
              disruptionReason=cfg["dreas"],passengerEligibility=[cpe])
    def na(r2,code):
        return dict(regime=r2,boundRph=1,passengerEligibility=[dict(passengerId=f"{pid}-PT-1",
            passengerType="ADT",eligibilityStatus="NOT_ELIGIBLE",systemCode=code,
            reason=LOOK.get(code,"Regime not applicable"),failureReasons=None)])
    others=[r2 for r2 in("APPR","EU","ASL") if r2!=cfg["reg"]]
    return dict(
        eventMetadata=dict(trigger="DISRUPTION_DETECTION_SERVICE",timestamp=f"{cfg['date']}T20:05:34.000Z"),
        pnrIdentifier=dict(pnrId=pid,pnr=loc),
        itineraryDetails=[dict(bound=1,boundRph=1,isOAL=(cfg["carr"] not in("AC",)),
            promisedItinerary=dict(origin=cfg["orig"],destination=cfg["dest"],associatedSegments=[seg(False)]),
            actualItinerary=dict(origin=cfg["orig"],destination=cfg["dest"],associatedSegments=[seg(True)]))],
        compensationEligibility=[comp]+[na(r2,f"FD-{r2}-NA-01") for r2 in others],
        socFlightEligibility=soc, seatFeeRefundEligibility=[])

def load(): return json.load(open(IDX))

def publish(sl):
    ok=0
    for i,r in enumerate(sl):
        good,log=B.render_publish_one(r)
        ok+=good; print(f"  [{i}] {r['tc']} {r['pnr_id']} {'OK' if good else 'FAIL '+log[-140:]}",flush=True)
    print(f"[publish] {ok}/{len(sl)}")

def checkcascade(sl):
    ttc=B.tt_conn(); cur=ttc.cursor(); pids=[r["pnr_id"] for r in sl]
    cur.execute("select pnr_id from trip where pnr_id=any(%s)",(pids,)); have={x[0] for x in cur.fetchall()}
    cur.execute("select pnr_id,count(*) from eds_pnr_output where pnr_id=any(%s) group by pnr_id",(pids,))
    eds={a:b for a,b in cur.fetchall()}; ttc.close()
    miss=[p for p in pids if p not in have]
    print(f"[cascade] trips {len(have)}/{len(pids)} | eds {len(eds)} | missing trips: {miss[:6]}")

def finalize(sl):
    ttc=B.tt_conn(); keys={}
    for r in sl:
        cur=ttc.cursor(); pid=r["pnr_id"]; tk=r["ticket"]
        iss=min(r["date"],"2026-06-01") if r["date"]<"2026-01-01" else "2026-06-01"
        cur.execute("""insert into ticket (primary_document_number,pnr_id,passenger_id,ticket_id,document_numbers,issuance_local_date,document_type)
            values (%s,%s,%s,%s,ARRAY[%s],%s,'T') on conflict do nothing""",
            (tk,pid,f"{pid}-PT-1",f"{tk}-{iss}",tk,iss))
        cur.execute("update passenger set date_of_birth=%s where pnr_id=%s",(DOB,pid))
        ttc.commit()
        key=f"traces/DDS/{r['date']}/{pid}/response.json"
        B._sess.client("s3").put_object(Bucket=B.BAT["s3_bucket"],Key=key,
            Body=open(f"{B.DDSW}/{pid}.dds.json","rb").read(),ContentType="application/json")
        keys[pid]=key
    ttc.close(); print(f"[finalize] tickets/DOB/S3 done for {len(keys)}")
    n=B.pin_all([r for r in sl if r["pnr_id"] in keys],keys)
    print(f"[finalize] pinned {n}")

def edsinject(sl):
    ttc=B.tt_conn(); cur=ttc.cursor()
    BC=json.dumps({"bookingSource":"AC_VACATIONS","bookingType":"REVENUE","bookingSubtype":"REVENUE","gdsLocator":"AMADEUS"})
    done=0
    for r in sl:
        pid=r["pnr_id"]
        cur.execute("SELECT count(*) FROM eds_pnr_output WHERE pnr_id=%s",(pid,))
        if cur.fetchone()[0]>0: continue
        segs=[f"{pid}-ST-1"]
        bounds=[{"boundRph":1,"origin":r["route"].split("-")[0],"destination":r["route"].split("-")[-1],
          "boundOriginLocation":"OTHER","boundOriginCountry":"OTHER","regimes":[r["regime"]],
          "promisedSegments":segs,"actualSegments":segs,"originalSegments":segs,
          "promisedWindowStart":f"{r['date']}T00:00:00.000Z",
          "authenticationContactDetails":{"passengers":[{"passengerId":f"{pid}-PT-1",
            "contacts":{"apn":{"email":r["email"],"phone":r["phone"]},
                        "ctc":{"email":"","phone":""},"ape":{"email":"","phone":""}}}]}}]
        cur.execute("""INSERT INTO eds_pnr_output (id,pnr_id,booking_context,bounds,changes,last_modified,received_at)
                       VALUES (%s,%s,%s,%s,%s,now(),now())""",
                    (str(uuid.uuid4()),pid,BC,json.dumps(bounds),"[]"))
        done+=1
    ttc.commit(); ttc.close(); print(f"[edsinject] injected {done}")

def verify(sl):
    ctx=ssl.create_default_context(); ctx.check_hostname=False; ctx.verify_mode=ssl.CERT_NONE
    ok=0; bad=[]
    for r in sl:
        try:
            req=urllib.request.Request(B.BAT["endpoint"]+r["pnr_id"],headers={"x-api-key":B.BAT["api_key"]})
            d=json.load(urllib.request.urlopen(req,timeout=25,context=ctx))
            soc=d["socFlightEligibility"][0]; pe=soc["passengerEligibility"][0]
            comp=d["compensationEligibility"][0]["passengerEligibility"][0]
            errs=[]
            if pe["systemCode"]!=r["legs"][0]["soc_code"]: errs.append(f"soc {pe['systemCode']}")
            if soc["regime"]!=r["regime"]: errs.append(f"regime {soc['regime']}")
            if soc["carrierCode"]!=r["legs"][0]["carrier"]: errs.append(f"carr {soc['carrierCode']}")
            if comp["systemCode"]!=r["syscode"]: errs.append(f"comp {comp['systemCode']}")
            if errs: bad.append((r["tc"],errs))
            else: ok+=1
        except Exception as e: bad.append((r["tc"],str(e)[:60]))
    for b in bad: print("  BAD",b)
    print(f"[verify] {ok}/{len(sl)}")

if __name__=="__main__":
    ap=argparse.ArgumentParser(); ap.add_argument("phase")
    ap.add_argument("--start",type=int,default=0); ap.add_argument("--end",type=int,default=999)
    ap.add_argument("--tag",default="",choices=list(SET_TAGS))
    a=ap.parse_args()
    set_tag(a.tag)
    if a.phase=="gen": gen(); sys.exit()
    sl=load()[a.start:a.end]
    dict(publish=publish,checkcascade=checkcascade,finalize=finalize,edsinject=edsinject,verify=verify)[a.phase](sl)
