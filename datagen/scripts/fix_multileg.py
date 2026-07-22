#!/usr/bin/env python3
"""
Fix the multi-leg fidelity gap: cases whose spec describes a 2-leg journey but were
built single-leg. Rebuilds the booking (2 segments) + DDS itinerary (promised+actual,
correct final destination) + MSL leg, while PRESERVING each case's verdict
(status/systemCode/amount/regime) and contact (email/phone) from the existing files.
"""
import json
from datetime import datetime, timedelta
from pathlib import Path

FD = Path(__file__).resolve().parent.parent / "scenarios" / "fd-sit"
DDS = FD / "_dds-templates"
DATE = "2026-06-15"

# tc -> (legs=[(carrier,flt,origin,dest),...], msl_leg(1-based), delayMinutes)
CFG = {
 33: ([("AC","446","YUL","YYZ"),("AC","447","YYZ","YVR")],2,0),
 34: ([("AC","450","YUL","YYZ"),("AC","451","YYZ","YVR")],2,0),
 41: ([("AC","460","YUL","YYZ"),("AC","461","YYZ","YVR")],2,0),
 42: ([("AC","462","YUL","YYZ"),("AC","463","YYZ","YVR")],2,0),
 44: ([("AC","472","YUL","YYZ"),("AC","473","YYZ","YUL")],2,0),
 45: ([("AC","348","YUL","YYZ"),("AC","349","YYZ","YVR")],2,0),
 47: ([("AC","482","YUL","YYZ"),("AC","483","YYZ","YUL")],2,120),
 48: ([("AC","470","YUL","YYZ"),("AC","471","YYZ","YVR")],2,90),
 54: ([("AC","497","YUL","YYZ"),("WS","3456","YYZ","YVR")],2,300),
 55: ([("AC","870","YUL","FRA"),("LH","471","FRA","MUC")],2,240),
 56: ([("AC","500","YUL","YYZ"),("AC","501","YYZ","YEG")],2,0),
 59: ([("AC","848","YUL","LHR"),("BA","1234","LHR","EDI")],2,0),
 88: ([("AC","1802","PTP","YUL"),("AC","422","YUL","YYZ")],2,0),
 89: ([("AC","849","LHR","YYZ"),("AC","121","YYZ","YVR")],2,0),
 90: ([("AC","1802","PTP","YUL"),("AC","422","YUL","YYZ")],2,0),
 91: ([("AC","871","CDG","YYZ"),("AC","121","YYZ","YVR")],2,0),
 92: ([("AC","849","LHR","YYZ"),("AC","121","YYZ","YVR")],2,0),
 93: ([("AC","1802","PTP","YUL"),("AC","422","YUL","YYZ")],2,0),
 94: ([("AC","871","CDG","YYZ"),("AC","121","YYZ","YVR")],2,0),
 100:([("AC","870","YYZ","CDG"),("AC","871","CDG","YYZ")],2,0),
 101:([("AC","871","CDG","YYZ"),("AC","121","YYZ","YVR")],2,0),
 103:([("AC","871","CDG","YYZ"),("AC","121","YYZ","YVR")],2,120),
 104:([("AC","871","CDG","YYZ"),("AC","121","YYZ","YVR")],2,120),
 106:([("AC","871","CDG","YYZ"),("AC","121","YYZ","YVR")],2,0),
 107:([("AC","871","CDG","YYZ"),("AC","121","YYZ","YVR")],2,0),
 110:([("AC","871","CDG","YYZ"),("AC","121","YYZ","YVR")],1,210),
 111:([("AC","871","CDG","YYZ"),("AC","121","YYZ","YVR")],1,120),
 113:([("AC","849","LHR","YYZ"),("AC","121","YYZ","YEG")],2,0),
 115:([("AC","860","LHR","FRA"),("LH","500","FRA","MUC")],2,240),
 119:([("AC","410","YYZ","YUL"),("AC","84","YUL","TLV")],2,0),
 120:([("AC","410","YYZ","YUL"),("AC","84","YUL","TLV")],2,0),
 126:([("AC","873","YYZ","FRA"),("AC","9042","FRA","TLV")],2,0),
 127:([("AC","873","YYZ","FRA"),("AC","9042","FRA","TLV")],2,0),
 129:([("AC","873","YYZ","FRA"),("AC","9042","FRA","TLV")],2,120),
 130:([("AC","873","YYZ","FRA"),("AC","9042","FRA","TLV")],2,120),
 132:([("AC","873","YYZ","FRA"),("AC","9042","FRA","TLV")],2,0),
 133:([("AC","873","YYZ","FRA"),("AC","9042","FRA","TLV")],2,0),
 136:([("AC","873","YYZ","FRA"),("AC","9042","FRA","TLV")],1,210),
 137:([("AC","873","YYZ","FRA"),("AC","9042","FRA","TLV")],1,120),
 139:([("AC","84","TLV","YYZ"),("WS","3500","YYZ","YVR")],2,300),
 140:([("AC","9042","TLV","FRA"),("LH","500","FRA","MUC")],2,240),
 144:([("AC","873","YYZ","FRA"),("LH","694","FRA","TLV")],2,240),
 152:([("AC","870","CDG","YYZ"),("AC","9070","YYZ","TLV")],2,240),
 180:([("VR","1","YOW","YUL"),("AC","848","YUL","LHR")],2,0),
 181:([("BU","1","YOW","YUL"),("AC","870","YUL","CDG")],2,0),
 183:([("AC","501","YUL","MNL"),("PAL","102","MNL","CEB")],2,240),
 184:([("AC","501","YUL","MNL"),("PAL","207","MNL","CEB")],2,300),
}

# TC -> canonical pnr_id
tcmap={}
for f in ["_FD_TC30_index.json","_FD_TC31_60_index.json","_FD_TC61_90_index.json","_FD_TC91_120_index.json",
          "_FD_TC121_150_index.json","_FD_TC151_180_index.json","_FD_TC181_200_index.json"]:
    for e in json.load(open(FD/f)): tcmap[int(e["tc"].split("_")[-1])]=e["pnr_id"]


def hh(h, m=0): return datetime.fromisoformat(f"{DATE}T{h:02d}:00:00")+timedelta(minutes=m)


def fix(n):
    pid=tcmap[n]; loc=pid.split("-")[0]
    legs,msl,dmin=CFG[n]
    scen=json.load(open(FD/f"{pid}.json")); dds=json.load(open(DDS/f"{pid}.dds.json"))
    # --- booking: 2 segments ---
    bsegs=[]
    for i,(cc,flt,o,d) in enumerate(legs):
        dep=hh(10+5*i); arr=hh(12+5*i)
        bsegs.append({"carrier":cc,"operating_carrier":cc,"flight_number":flt,"operating_flight_number":flt,
                      "origin":o,"destination":d,
                      "dep_local":dep.strftime("%Y-%m-%dT%H:%M:%S"),"arr_local":arr.strftime("%Y-%m-%dT%H:%M:%S"),
                      "dep_utc":(dep+timedelta(hours=4)).strftime("%Y-%m-%dT%H:%M:%SZ"),
                      "arr_utc":(arr+timedelta(hours=4)).strftime("%Y-%m-%dT%H:%M:%SZ"),
                      "booking_datetime":None,"aircraft":"320","cabin":"Y","status":"HK","arrival_terminal":"1"})
    scen["segments"]=bsegs
    scen["expected_cascade"]["db_end_state"]["flight_segment"]["rows"]=len(bsegs)
    scen["last_modification_comment"]=f"SIM-FD_TC_{n:03d}-multileg-fix-INT"
    scen["creation_comment"]=f"SIM-FD_TC_{n:03d}-multileg-fix-INT"
    open(FD/f"{pid}.json","w").write(json.dumps(scen,indent=2)+"\n")
    # --- DDS itinerary: promised + actual = the 2 legs ---
    def dseg(i,cc,flt,o,d):
        dep=hh(10+5*i); arr=hh(12+5*i)
        return {"segmentId":f"{pid}-ST-{i+1}","segmentStatus":"HK",
                "departureDatetime":dep.strftime("%Y-%m-%dT%H:%M:00+00:00"),"arrivalDatetime":arr.strftime("%Y-%m-%dT%H:%M:00+00:00"),
                "departureAirport":o,"arrivalAirport":d,"marketingFlightNumber":int(flt) if flt.isdigit() else 0,
                "marketingCarrierCode":"AC","operatingFlightNumber":int(flt) if flt.isdigit() else 0,
                "operatingCarrierCode":cc,"flightId":f"{cc}#{flt}#{DATE}#{o}"}
    segs=[dseg(i,*l) for i,l in enumerate(legs)]
    it=dds["itineraryDetails"][0]
    o0=legs[0][2]; dN=legs[-1][3]
    it["promisedItinerary"]={"origin":o0,"destination":dN,"associatedSegments":segs}
    it["actualItinerary"]={"origin":o0,"destination":dN,"associatedSegments":[dict(s) for s in segs]}
    # --- MSL on the primary (first) regime block ---
    mcc,mflt,mo,md=legs[msl-1]
    ce=dds["compensationEligibility"][0]
    if "mslFlight" in ce:
        ce["mslFlight"]={"segmentId":f"{pid}-ST-{msl}","carrierCode":mcc,"flightNumber":mflt,"departureAirport":mo,
                         "arrivalAirport":md,"isStarSegment":(mcc=="LH"),"isOalSegment":(mcc!="AC")}
        ce["delayMinutes"]=dmin
    # SoC MSL too
    soc=dds["socFlightEligibility"][0]
    soc["segmentId"]=f"{pid}-ST-{msl}"; soc["flightNumber"]=int(mflt) if mflt.isdigit() else 0
    soc["departureAirport"]=mo; soc["arrivalAirport"]=md
    open(DDS/f"{pid}.dds.json","w").write(json.dumps(dds,indent=2)+"\n")
    return pid, loc, "-".join([legs[0][2]]+[l[3] for l in legs]), f"{mcc}{mflt}", msl


if __name__=="__main__":
    out=[]
    for n in sorted(CFG):
        pid,loc,route,mslf,msl=fix(n)
        out.append(pid); print(f"  FD_TC_{n:03d} {loc}  route {route:14} MSL=Leg{msl} {mslf}")
    json.dump(out, open(FD/"_FD_multileg_fix_pids.json","w"))
    print(f"\nfixed {len(out)} scenarios + DDS")
