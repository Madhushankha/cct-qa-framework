#!/usr/bin/env python3
"""Build the ANCILLARY **SIT** test-data set in CRT — from `~/Downloads/SIT/ANC_Test_Execution 1.xlsx`
(suites Seat ANS / Bag ANB / Reusable GEN). This is a DIFFERENT suite from the 54-case
`Ancillaries - Seat Fees & Bag fees.xlsx` set built by anc_crt_build.py.

Reuses anc_crt_build for all plumbing (scenario render -> Kafka publish -> trip-tracer cascade ->
ticket/DOB -> seat/bag DDS to S3 -> execution_traces pin) and the validated systemCode taxonomy.
What is different here: the SIT sheet names EXACT record locators (RVR201, AC2097, WS6774, ...) and
EXACT passengers per case, so those are honoured rather than generated.

Names: the 7 case-specific pax named in the sheet (Reese Chandra, Dakota Moreau, Riley Chen,
Morgan Patel, Avery Santos, Jordan Kim, Quinn Torres) are each used ONCE and are absent from the
passenger table, so they are kept verbatim. The sheet's generic user "Sam Rivera" is already in the
DB 47x and repeats across ~13 cases, so each of those PNRs instead gets a unique DB-absent name from
crt_uniqnames (per the "unique + not in DB" rule); the report ships the case->locator->name mapping.

Usage: AWS_PROFILE=ac-cct-crt CRT_EMAIL=... CRT_PHONE=... python3 anc_sit_build.py <phase>
  phases: index | publish | checkcascade | finalize | verify
"""
import json, os, sys, argparse, datetime

os.environ.setdefault("CRT_EMAIL","lahiru@ae-qa1-aircanada.mailinator.com")
os.environ.setdefault("CRT_PHONE","+94712534323")
import anc_crt_build as A          # plumbing + CRT config + DDS taxonomy helpers
import crt_uniqnames as U

WORK=A.WORK
OUT=os.environ.get("ANC_SIT_OUT", f"{WORK}/_ANC_SIT_crt_index.json")
TPREFIX=os.environ.get("ANC_SIT_TPREFIX","014312")
PASSCODE="884213"                  # SIT entry passcode (the 54-case set uses 546879)

T=datetime.date.today()
def d(n): return (T+datetime.timedelta(days=n)).isoformat()
POST=d(-21)      # post-travel, comfortably >72h since arrival
PRE =d(+15)      # pre-travel, "before expected arrival (~15 days out)"
U72 =d(-1)       # flown yesterday -> arrival <72h ago
AHL_RECENT=f"{d(-1)}T10:00:00Z"    # <72h old
AHL_OLD   =f"{d(-21)}T10:00:00Z"   # >72h old

# routes (orig,dest,carrier,flightno)
YULYYZ=("YUL","YYZ","AC","4922"); YYZYVR=("YYZ","YVR","AC","0123")
YYCICN=("YYC","ICN","AC","2097"); YHZGRU=("YHZ","GRU","AC","1525")
YOWCDG=("YOW","CDG","AC","5221"); JFKBOS=("JFK","BOS","AC","3502")
YYCYQB=("YYC","YQB","AC","6162"); YYZLGA=("YYZ","LGA","AC","6774")   # AC-ify: OAL rides the EMD/DDS
ICNYEG=("ICN","YEG","AC","1838")
MULTI3=[("YUL","YYZ","AC","4922"),("YYZ","LHR","AC","0870")]          # YUL->YYZ->LHR
MSEG2 =[("YYZ","YUL","AC","4922"),("YUL","CDG","AC","0870")]          # seg1 elig / seg2 not

S_EL,S_NE,S_REF,S_VOID,S_OAL = A.S_EL,A.S_NE,A.S_REF,A.S_VOID,A.S_OAL
B_EL,B_NE,B_REF,B_VOID,B_OAL,B_NOREP = A.B_EL,A.B_NE,A.B_REF,A.B_VOID,A.B_OAL,A.B_NOREP
AHL=A.AHL

C=[]
def seat(tc,loc,name,rows,route=YULYYZ,npax=1,date=POST,pax=None,note="",ahl_date=None,future=False):
    C.append(dict(tc=tc,suite="seat",name=name,loc=loc,date=date,npax=npax,
                  route=[route] if isinstance(route,tuple) else route,
                  seat=rows,bag=None,pax_fixed=pax,note=note,future=future,ahl_date=ahl_date))
def bag(tc,loc,name,segs,route=YULYYZ,npax=1,date=POST,pax=None,note="",ahl_date=None,pin=True):
    C.append(dict(tc=tc,suite="bag",name=name,loc=loc,date=date,npax=npax,
                  route=[route] if isinstance(route,tuple) else route,
                  seat=None,bag=segs,pax_fixed=pax,note=note,future=False,ahl_date=ahl_date,pin=pin))

# ---------------- SEAT (ANS) ----------------
seat("ANC-ANS-01-01","RVR201","Seat-refund intent recognised - self claimant",
     [[S_EL("Seat refund - eligible seat booking (intent entry)")]])
seat("ANC-ANS-02-01","VAC8YQ","ACV-booked PNR - contact ACV and end",
     [[S_NE("Seat Refund - ACV Booking -> Redirected to ACV")]],note="acv")
seat("ANC-ANS-03-01","NBK7TK","Non-ACV PNR - proceeds to journey selection",
     [[S_EL("Seat refund - non-ACV, proceeds to journey selection")]])
seat("ANC-ANS-04-01","MSG3YQ","Multi-segment journey - segment multi-select",
     [[S_EL("segment 1 ELIGIBLE")],[S_EL("segment 2 ELIGIBLE")]],route=MULTI3)
seat("ANC-ANS-04-02","MSG3YP","Multi-segment journey - PRE-travel variant",
     [[S_NE("Pre-travel multi-segment - before expected arrival")],
      [S_NE("Pre-travel multi-segment - before expected arrival")]],
     route=MULTI3,date=PRE,future=True,note="sheet reuses MSG3YQ; split so post- and pre-travel can coexist")
seat("ANC-ANS-05-01","SSG1ZP","Single-segment journey - skips segment selection",
     [[S_EL("Seat refund - single segment, skips segment selection")]])
seat("ANC-ANS-19-01","AC2097","Seat duplicate-claim check",
     [[S_NE("Seat Refund - Duplicate Claim Prevention (same PNR + segment + EMD)")]],
     route=YYCICN,pax=("REESE","CHANDRA"),note="dup")
seat("ANC-ANS-20-01","HOLD4U","Pax rebooked & holding ticket - not eligible",
     [[S_NE("Seat Refund - NOT Eligible - Pax Rebooked and Holding Ticket")]])
seat("ANC-ANS-06-01","PRE9TR","Mid-journey (arrival not passed) - live agent handoff",
     [[S_NE("Pre-Travel (Before Expected Arrival) - Live Agent Handoff")]],date=PRE,future=True)
seat("ANC-ANS-07-01","OVR72H","All segments past 72h - proceeds to EMD check",
     [[S_EL("All segments >72h since arrival - proceeds to EMD check")]])
seat("ANC-ANS-08-01","AC1525","Under 72h - 72h wait, email-confirm, queued",
     [[S_NE("Seat refund - segment <72h since arrival - 72h wait, queued")]],
     route=YHZGRU,date=U72,pax=("DAKOTA","MOREAU"),note="under72h")
seat("ANC-ANS-09-01","AC5221","EMD Refund (R) - already refunded",
     [[S_REF("Seat Refund - EMD Already Refunded (Status R)")]],route=YOWCDG,pax=("RILEY","CHEN"))
seat("ANC-ANS-10-01","AC3502","EMD Void (V) - voided before charge",
     [[S_VOID("Seat Refund - EMD Voided (Status V)")]],route=JFKBOS,pax=("MORGAN","PATEL"))
seat("ANC-ANS-11-01","EMD2SG","Multiple EMDs on a segment - manual handling",
     [[S_NE("Single Passenger - Multiple EMDs on Same Segment - Manual Handling"),
       S_NE("Second EMD on the same segment - manual handling")]],note="multi_emd_1pax")
seat("ANC-ANS-12-01","NOFEE7","No EMD found - no paid seat fee",[[]],note="no_emd")
seat("ANC-ANS-13-01","OPU014","Open/Used EMD - eligibility check fires",
     [[S_EL("Seat refund - EMD 014 Open/Used, eligibility check fires")]])
seat("ANC-ANS-14-01","AC6162","Eligible - refund processed within 30 business days",
     [[S_EL("Seat Refund - ELIGIBLE - refund processed within 30 business days")]],
     route=YYCYQB,pax=("AVERY","SANTOS"))
seat("ANC-ANS-15-01","WS6774","Not eligible - OAL (WestJet, EMD not 014)",
     [[S_OAL("Seat Refund - OAL operated (WestJet) - EMD not 014 - referred to OAL","838")]],
     route=YYZLGA,pax=("JORDAN","KIM"),note="oal")
seat("ANC-ANS-15-02","AC1838","Not eligible - INVOL, characteristics unchanged",
     [[S_NE("Seat Refund - INVOL seat change, characteristics unchanged - NOT eligible")]],
     route=ICNYEG,pax=("QUINN","TORRES"))
seat("ANC-ANS-15-03","CAT09Z","Not eligible - catch-all (invol upgrade / no fee paid)",
     [[S_NE("Seat Refund - Catch-All Not Eligible (involuntary upgrade or no fee paid)")]])
seat("ANC-ANS-17-01","MSEG2D","Multi-segment eligibility - combined per segment",
     [[S_EL("segment 1 ELIGIBLE - seat characteristics changed")],
      [S_NE("segment 2 NOT ELIGIBLE - characteristics match")]],route=MSEG2)
seat("ANC-ANS-18-01","STAR7L","Not eligible - STAR partner (Lufthansa) then dispute",
     [[S_OAL("Seat Refund - STAR Alliance partner operated (Lufthansa) - referred to partner","016")]],
     route=("YYZ","FRA","AC","0870"),note="star")

# ---------------- BAG (ANB) ----------------
bag("ANC-ANB-01-01","BGA001","Bag-refund intent recognised - AHL on file",
    [(AHL(True,"AHL",True),[B_EL("Bag refund - AHL on file, intent recognised")])],ahl_date=AHL_OLD)
bag("ANC-ANB-02-01","BGACV1","Bag flow skips the ACV check (ACV-booked PNR)",
    [(AHL(True,"AHL",True),[B_EL("Bag refund - ACV-booked PNR; bag flow skips the ACV check")])],
    ahl_date=AHL_OLD,note="acv")
bag("ANC-ANB-03-01","BGNODP","No duplicate - proceeds to the AHL gate",
    [(AHL(True,"AHL",True),[B_EL("Bag refund - no prior submitted claim, proceeds to AHL gate")])],ahl_date=AHL_OLD)
bag("ANC-ANB-04-01","BGDUP1","Submitted duplicate by the user",
    [(AHL(True,"AHL",True),[B_NE("Bag Refund - Duplicate Claim Prevention (submitted by the same user)")])],
    ahl_date=AHL_OLD,note="dup")
bag("ANC-ANB-05-01","BGDUP2","Submitted duplicate by someone else - masked email",
    [(AHL(True,"AHL",True),[B_NE("Bag Refund - Duplicate claim opened by a different party (masked email / fraud option)")])],
    ahl_date=AHL_OLD,note="dup_other")
bag("ANC-ANB-06-01","BGMJ01","Multiple journeys - handled one by one",
    [(AHL(True,"AHL",True),[B_EL("Bag refund - journey 1 of a multi-journey PNR")]),
     (AHL(True,"AHL",True),[B_EL("Bag refund - journey 2 of a multi-journey PNR")])],
    route=MSEG2,ahl_date=AHL_OLD)
bag("ANC-ANB-07-01","BGU72H","AHL under 72h - auto-refund, emailed, end",
    [(AHL(True,"AHL",False),[B_NE("Bag Refund - AHL created <72h ago - auto-refund within 72h, notified by email")])],
    date=d(-2),ahl_date=AHL_RECENT,note="under72h")
bag("ANC-ANB-08-01","BGO72H","AHL over 72h - proceeds to DDS data check",
    [(AHL(True,"AHL",True),[B_EL("Bag Refund - AHL created >72h ago - proceeds to DDS eligibility check")])],ahl_date=AHL_OLD)
bag("ANC-ANB-09-01","BGNODD","No DDS data - report a delayed/damaged bag first",
    [(AHL(False,"NONE"),[])],note="no_dds",pin=False)     # NO DDS pin at all
bag("ANC-ANB-10-01","BGELG1","Eligible bag fee - proceeds to EMD refund-status",
    [(AHL(True,"AHL",True),[B_EL("Bag Refund - eligible bag fee, proceeds to EMD refund-status check")])],ahl_date=AHL_OLD)
bag("ANC-ANB-10-02","BGMIX1","Multiple bag fees - only the eligible ones carried forward",
    [(AHL(True,"AHL",True),[B_EL("Bag Refund - bag fee 1 ELIGIBLE (displayed)"),
                            B_NE("Bag Refund - bag fee 2 NOT eligible (not displayed)")])],
    npax=2,ahl_date=AHL_OLD)
bag("ANC-ANB-11-01","BGNEL1","Not eligible bag fee - reason code, end",
    [(AHL(True,"AHL",True),[B_NE("Bag Refund - NOT eligible, reason code served, end flow")])],ahl_date=AHL_OLD)
bag("ANC-ANB-12-01","BGREF1","Eligible EMD already refunded - end",
    [(AHL(True,"AHL",True),[B_REF("Bag Refund - EMD already Refunded / cover refund processed")])],ahl_date=AHL_OLD)
bag("ANC-ANB-13-01","BGUSD1","Eligible EMD not yet refunded - manual handling",
    [(AHL(True,"AHL",True),[B_EL("Bag Refund - EMD Used/Open, not yet refunded - manual handling")])],ahl_date=AHL_OLD)

# ---------------- Reusable (GEN) ----------------
# Most GEN cases are harness/session driven (service outage API, guest session, OTP hold, 3rd-party
# claimant) and need no dedicated PNR. GEN-05 does: two same-name pax + a valid 014 ticket.
seat("ANC-GEN-05-01","GEN05C","Name collision - 13-digit 014 ticket disambiguates",
     [[S_EL("Name collision - passenger 1 (same name)"),
       S_EL("Name collision - passenger 2 (same name)")]],npax=2,note="name_collision")

def build_index():
    conn=A.tt_conn()
    try:
        # unique DB-absent names for every pax that the sheet does NOT name explicitly
        need=[c for c in C if not c.get("pax_fixed")]
        total=sum(c["npax"] for c in need)
        # name_collision case deliberately needs the SAME name twice (that is the test) -> 1 name
        pool=U.fresh_pool(conn,total+4,seed=880013)
    finally: conn.close()
    k=0; recs=[]
    for i,c in enumerate(C):
        if c.get("pax_fixed"):
            names=[list(c["pax_fixed"])]
            while len(names)<c["npax"]: names.append(list(pool[k])); k+=1
        elif c["note"]=="name_collision":
            n=list(pool[k]); k+=1
            names=[list(n) for _ in range(c["npax"])]      # SAME name twice, by design
        else:
            names=[list(pool[k+j]) for j in range(c["npax"])]; k+=c["npax"]
        r=dict(tc=c["tc"],suite=c["suite"],name=c["name"],loc=c["loc"],
               pnr_id=f"{c['loc']}-{c['date']}",date=c["date"],npax=c["npax"],route=c["route"],
               future=c.get("future",False),note=c.get("note",""),pax_names=names,
               seat=c.get("seat"),bag=c.get("bag"),ticket=f"{TPREFIX}{i+1:06d}",
               email=A.EMAIL,phone=A.PHONE,passcode=PASSCODE,
               pin=c.get("pin",True),uniq_names=(c["note"]!="name_collision"))
        if c.get("ahl_date"): r["ahl_date"]=c["ahl_date"]
        recs.append(r)
    json.dump(recs,open(OUT,"w"),indent=1)
    ns=sum(1 for r in recs if r["suite"]=="seat")
    print(f"[index] {len(recs)} SIT PNRs ({ns} seat + {len(recs)-ns} bag) -> {OUT}")
    return recs

def load(): return json.load(open(OUT))

def main():
    ap=argparse.ArgumentParser(); ap.add_argument("phase")
    ap.add_argument("--start",type=int,default=0); ap.add_argument("--end",type=int,default=10**9)
    a=ap.parse_args()
    if a.phase=="index": build_index(); return
    recs=load(); sl=recs[a.start:a.end]
    if a.phase=="publish":
        ok=0
        for i,r in enumerate(sl):
            good,log=A.render_publish_one(r); ok+=good
            print(f"  [{a.start+i}] {r['pnr_id']} {r['tc']} {'OK' if good else 'FAIL '+log[-160:]}",flush=True)
        print(f"[publish] {ok}/{len(sl)} produced")
    elif a.phase=="checkcascade":
        c=A.tt_conn(); have=A.cascaded(c,[r["pnr_id"] for r in sl]); c.close()
        miss=[r["pnr_id"] for r in sl if r["pnr_id"] not in have]
        print(f"[cascade] {len(have)}/{len(sl)} present; missing={miss}")
    elif a.phase=="finalize":
        c=A.tt_conn(); keys={}
        for i,r in enumerate(sl):
            try:
                k=A.finalize_one(r,c)
                if r.get("pin",True): keys[r["pnr_id"]]=k
                print(f"  [{a.start+i}] {r['pnr_id']} {r['tc']} finalized{'' if r.get('pin',True) else ' (no DDS pin by design)'}",flush=True)
            except Exception as e:
                # ROLLBACK or the aborted transaction poisons every later record on this shared conn
                try: c.rollback()
                except Exception: pass
                print(f"  [{a.start+i}] {r['pnr_id']} ERR {e}",flush=True)
        c.close()
        n=A.pin_all([r for r in sl if r["pnr_id"] in keys],keys)
        print(f"[finalize] tickets/DOB/S3 done; pinned {n} DDS rows")
    elif a.phase=="verify":
        res=[A.verify_one(r) for r in sl if r.get("pin",True)]
        ok=sum(1 for x in res if x["ok"])
        for x in res:
            if not x["ok"]: print("  FAIL",x)
        print(f"[verify] {ok}/{len(res)} match expected systemCodes")
    else: print("unknown phase"); sys.exit(2)

if __name__=="__main__": main()
