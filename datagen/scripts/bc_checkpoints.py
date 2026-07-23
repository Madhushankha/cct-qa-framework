#!/usr/bin/env python3
"""BOOKING CHANGE PNR post-creation CHECKPOINTS (CRT) — Voluntary + Involuntary.

Two verification surfaces:

  A. trip-tracer cascade (BOTH flows) — everything Order Retrieve / GenUC-01 reads and the OTP
     is sent from:
       1  trip ACTIVE (exactly one ACTIVE trip per locator)
       2  trip_details present
       3  passenger count == design + DOB set + passenger_type (+ has_infant)
       4  ticket count == npax, 014 stock, coupons correlated to every segment, status matches
          design (OPEN_FOR_USE vs FLOWN), fare basis matches design (BASIC suffix / ECO)
       5  eds_pnr_output present + contact email == lahiru (OTP delivery)
       6  eds booking_context.bookingSource == designed channel
       7  flight_segment carriers (marketing+operating), bound_rph, segment count match design
       8  segment_status matches design (UN cancelled for INVOL originals, HK otherwise)
       9  departure_datetime in the designed window (VOL 72hr / INVOL future)
      10  SSRs present (blocking + persist + RQST seat)
      11  journey_updates CHECK_IN acceptance ACCEPTED iff a checked-in case
      12  baggage_updates seeded iff a checked-bag case (BAG_LOADED_ON_AIRCRAFT iff loaded)
      13  reserved locators genuinely absent
  B. LIVE voluntary eligibility endpoint (VOL cases only, trigger BOOKING_CHANGE) — rebuild each
     PNR's pnrData FROM THE DB, POST it, assert the VBC reason code + per-rule validationStatus +
     bookingSource echo.  INVOL is NOT rule-engine-eligible (endpoint returns 422) so it has no
     endpoint surface — it is verified entirely on the booking side.

Invoke: python3 bc_checkpoints.py [index.json]      (no AWS creds; WARP up).  Reuses the payload
builder from sc_crt_build and the VOL caller from bc_crt_build.
"""
import json, sys, datetime
import bc_crt_build as B
import crt_uniqnames as U
import pnr_common_checks as C

IDX = sys.argv[1] if len(sys.argv) > 1 else B.OUT
rows = json.load(open(IDX))
live = [r for r in rows if r["seed_pnr"]]
reserved = [r for r in rows if not r["seed_pnr"]]
ids = [r["pnr_id"] for r in live]
by = {r["pnr_id"]: r for r in live}
vol = [r for r in live if r["flow"] == "vol" and r["exp"] is not None]

conn = B.tt_conn(); cur = conn.cursor()
def q(sql, p): cur.execute(sql, p); return cur.fetchall()

trip = {r[0]: r[1] for r in q("select pnr_id,status from trip where pnr_id=any(%s)", (ids,))}
active = {r[0]: r[1] for r in q("select pnr,count(*) filter (where status='ACTIVE') from trip "
                                "where pnr=any(%s) group by pnr", ([r["pnr"] for r in live],))}
td = {r[0]: r[1] for r in q("select pnr_id,count(*) from trip_details where pnr_id=any(%s) group by 1", (ids,))}
paxrows = {}
for pid, ppid, pt, dob in q("select pnr_id,passenger_id,passenger_type,date_of_birth from passenger "
                            "where pnr_id=any(%s) and not is_removed order by passenger_id", (ids,)):
    paxrows.setdefault(pid, []).append((ppid, pt, dob))
hasinf = {r[0]: r[1] for r in q("select pnr_id,bool_or(has_infant) from passenger where pnr_id=any(%s) "
                                "and not is_removed group by 1", (ids,))}
tkt = {}
for pid, doc, coupons in q("select pnr_id,primary_document_number,coupons from ticket where pnr_id=any(%s)", (ids,)):
    tkt.setdefault(pid, []).append((doc, json.loads(coupons) if isinstance(coupons, str) else (coupons or [])))
segs = {}
for pid, sid, mkt, op, brph, st in q("select pnr_id,segment_id,marketing_carrier_code,operating_carrier_code,"
                                      "bound_rph,segment_status from flight_segment where pnr_id=any(%s) "
                                      "and not is_removed order by segment_id", (ids,)):
    segs.setdefault(pid, []).append((sid, (mkt or "").strip(), (op or "").strip(), brph, (st or "").strip()))
segdep = {}
for pid, sid, dep in q("select pnr_id,segment_id,departure_datetime from flight_segment "
                       "where pnr_id=any(%s) and not is_removed order by segment_id", (ids,)):
    segdep.setdefault(pid, []).append(dep)
ssr = {}
for pid, code, pids in q("select pnr_id,code,passenger_id from special_service_request "
                         "where pnr_id=any(%s) and not is_removed", (ids,)):
    ssr.setdefault(pid, []).append(((code or "").strip(), (pids or [None])[0]))
ju = {}
for pid, et, data in q("select pnr_id,event_type,data from journey_updates where pnr_id=any(%s)", (ids,)):
    ju.setdefault(pid, []).append((et, json.loads(data) if isinstance(data, str) else data))
eds = {}
for pid, bc in q("select distinct on (pnr_id) pnr_id,booking_context from eds_pnr_output "
                 "where pnr_id=any(%s) order by pnr_id,received_at desc", (ids,)):
    eds[pid] = json.loads(bc) if isinstance(bc, str) and bc else bc
edsb = {}
for pid, bounds in q("select distinct on (pnr_id) pnr_id,bounds from eds_pnr_output "
                     "where pnr_id=any(%s) order by pnr_id,received_at desc", (ids,)):
    edsb[pid] = json.loads(bounds) if isinstance(bounds, str) and bounds else bounds
bag = {}
for pid, et in q("select pnr_id,event_type from baggage_updates where pnr_id=any(%s) and user_name='CCT-BC'", (ids,)):
    bag.setdefault(pid, set()).add(et)
resv = {r[0] for r in q("select pnr from trip where pnr=any(%s)", ([r["pnr"] for r in reserved],))}

# ---- A. booking-side checks -------------------------------------------------
def edsmail(pid):
    b = edsb.get(pid) or []
    try: return b[0]["authenticationContactDetails"]["passengers"][0]["contacts"]["apn"]["email"]
    except Exception: return None

VALID = ("OPEN_FOR_USE", "O", "OK", "A")
def coupon_ok(pid):
    r = by[pid]; nseg = len(r["segs"]); docs = tkt.get(pid, [])
    if len(docs) != r["npax"]: return False
    want_status = [B.COUPON_STATUS.get(s["coupon"], "OPEN_FOR_USE") for s in r["segs"]]
    fb_want = B.FARE_BASIS.get(r["fare"], B.FARE_BASIS["ECO"])[0]
    for doc, cps in docs:
        if not doc.startswith("014"): return False
        if len(cps) != nseg: return False
        got = [(c.get("status") or "").upper() for c in cps]
        if got != [s.upper() for s in want_status]: return False
        if any((c.get("fareBasisCode") or "") != fb_want for c in cps): return False
    return True

def dep_window_ok(pid):
    r = by[pid]
    if r["flow"] != "vol" or r["exp"] is None: return True     # INVOL / env: no strict window
    deps = segdep.get(pid) or []
    if not deps: return False
    now = datetime.datetime.now(datetime.timezone.utc)
    # selected bound's earliest UNFLOWN (OPEN) segment governs the 72hr rule
    unflown = [d for d, s in zip(deps, r["segs"]) if s["coupon"] == "OPEN"]
    ref = min(unflown) if unflown else min(deps)
    mins = (ref - now).total_seconds() / 60
    if r["exp"] == "VBC-NE-01": return not (0 < mins <= 4335)
    if r["exp"] in ("VBC-EL-01", "VBC-NE-07"): return 0 < mins <= 4335
    return True

def carriers_ok(pid):
    r = by[pid]
    got = [(s[1], s[2]) for s in segs.get(pid, [])]
    return got == [(s["mkt"], s["op"]) for s in r["segs"]]

def status_ok(pid):
    r = by[pid]
    got = [s[4] for s in segs.get(pid, [])]
    return got == [s["status"] for s in r["segs"]]

def bounds_ok(pid):
    r = by[pid]
    return [s[3] for s in segs.get(pid, [])] == [s["bound"] for s in r["segs"]]

def ssrs_ok(pid):
    r = by[pid]; want = set()
    for k, p in enumerate(r["paxs"]):
        for c in p["ssr"]: want.add((c, f"{pid}-PT-{k+1}"))
    if r["seat"]: want.add(("RQST", f"{pid}-PT-1"))
    return want.issubset(set(ssr.get(pid, [])))

def checkin_ok(pid):
    r = by[pid]
    accepted = any(et == "CHECK_IN" and any(ld.get("acceptance", {}).get("status") == "ACCEPTED"
                                            for ld in (d.get("segment", {}).get("legDeliveries") or []))
                   for et, d in ju.get(pid, []))
    return accepted == bool(r["checkin"])

def bag_ok(pid):
    r = by[pid]; got = bag.get(pid, set())
    if not r["bag"]: return len(got) == 0
    if r["bag"] == "loaded": return "BAG_LOADED_ON_AIRCRAFT" in got
    return "BAG_ACCEPTED" in got and "BAG_LOADED_ON_AIRCRAFT" not in got   # notloaded

def ptypes_ok(pid):
    r = by[pid]
    got = [p[1] for p in paxrows.get(pid, [])]
    if got != [p["ptype"] for p in r["paxs"]]: return False
    if any(p["ptype"] == "INF" for p in r["paxs"]) and not hasinf.get(pid): return False
    return True

def dob_ok(pid):
    r = by[pid]
    got = [p[2].isoformat() if p[2] else None for p in paxrows.get(pid, [])]
    return got == [p["dob"] for p in r["paxs"]]

def off(pred): return [by[p]["pnr"] for p in ids if pred(p)]
A = {
 "trip ACTIVE (1/loc)":  off(lambda p: trip.get(p) != "ACTIVE" or active.get(by[p]["pnr"], 0) != 1),
 "trip_details":         off(lambda p: td.get(p, 0) == 0),
 "passenger==npax":      off(lambda p: len(paxrows.get(p, [])) != by[p]["npax"]),
 "DOB set + matches":    off(lambda p: not dob_ok(p)),
 "passenger_type/inf":   off(lambda p: not ptypes_ok(p)),
 "ticket/coupon/fare":   off(lambda p: not coupon_ok(p)),
 "eds_pnr_output":       off(lambda p: p not in eds),
 "eds contact email":    off(lambda p: edsmail(p) != by[p]["email"]),
 "eds bookingSource":    off(lambda p: (eds.get(p) or {}).get("bookingSource") != by[p]["src"]),
 "segment carriers":     off(lambda p: not carriers_ok(p)),
 "segment status":       off(lambda p: not status_ok(p)),
 "segment count/bounds": off(lambda p: not bounds_ok(p)),
 "departure window":     off(lambda p: not dep_window_ok(p)),
 "SSRs + RQST seat":     off(lambda p: not ssrs_ok(p)),
 "CHECK_IN acceptance":  off(lambda p: not checkin_ok(p)),
 "baggage_updates":      off(lambda p: not bag_ok(p)),
}
print(f"BOOKING CHANGE CHECKPOINTS — {IDX}")
print(f"  {len(ids)} seeded ({sum(1 for r in live if r['flow']=='vol')} VOL + "
      f"{sum(1 for r in live if r['flow']=='invol')} INVOL) + {len(reserved)} reserved (CRT)")
ok = True
print("--- A. trip-tracer cascade (Order Retrieve / GenUC-01 / OTP / rule inputs) ---")
for name, o in A.items():
    print(f"  {name:22} {len(ids)-len(o)}/{len(ids)}" + ("" if not o else f"   MISS {len(o)}: {o[:6]}"))
    if o: ok = False
bad_resv = sorted(resv)
print(f"  {'reserved locator absent':22} {len(reserved)-len(bad_resv)}/{len(reserved)}"
      + ("" if not bad_resv else f"   PRESENT(!) {bad_resv}"))
if bad_resv: ok = False

# ---- B. live VOL eligibility endpoint ---------------------------------------
print("--- B. live voluntary eligibility endpoint (BOOKING_CHANGE, DB-derived payload) ---")
FAILRULE = {"VBC-NE-01": "rule72hrWindow", "VBC-NE-02": "ruleCheckInBag", "VBC-NE-03": "ruleBookingSource",
            "VBC-NE-04": "ruleFareEligibility", "VBC-NE-05": "ruleSsrRestriction", "VBC-NE-06": "ruleTicketStatus",
            "VBC-NE-07": "ruleCheckinStatus", "VBC-NE-08": "ruleEUpgrade"}
areas = {k: [0, 0, []] for k in ["reason code", "validationStatus", "bookingSource echo"]}
def rec(a, good, tag, msg=""):
    areas[a][1] += 1
    if good: areas[a][0] += 1
    else: areas[a][2].append((tag, msg))
# Live VOL eligibility when the compute endpoint is reachable; otherwise validate with the offline
# rule-replica (bc_offline_verify) against the live DB data — a real PASS/FAIL, never a bare SKIP.
_elig_live = C.eligibility_live_ok("crt")
if not _elig_live:
    passed, tail = C.run_offline_eligibility("bc_offline_verify.py", IDX)
    for ln in tail: print("   ", ln)
    print(f"  VOL eligibility (offline rule-replica) {'PASS' if passed else 'FAIL'}")
    if not passed: ok = False
for r in (vol if _elig_live else []):
    tag = f"{r['tc']}/{r['pnr']}"
    g = B.vol_eligibility(r, conn)
    if "err" in g:
        for a in areas: areas[a][1] += 1; areas[a][2].append((tag, g["err"]))
        continue
    rec("reason code", g["reason"] == r["exp"], tag, f"got {g['reason']} want {r['exp']}")
    val = g["val"]
    if r["exp"] == "VBC-EL-01":
        okv = all(v in ("pass", "not_applicable") for v in val.values())
    else:
        okv = val.get(FAILRULE.get(r["exp"])) == "fail"
    rec("validationStatus", okv, tag, json.dumps(val))
    rec("bookingSource echo", g["bookingSource"] is not None, tag, f"got {g['bookingSource']}")
for name, (good, tot, bad) in areas.items():
    if tot == 0: continue
    print(f"  {name:22} {good}/{tot}" + ("" if good == tot else f"   BAD {tot-good}: {bad[:5]}"))
    if good != tot: ok = False
_uniq_clean, _uniq_off = U.name_uniqueness(cur, ids)
# shared: ticket linkage + eds auth == pax + DATE WINDOWS.
# Booking Change acts BEFORE travel -> flight="future" (the OPPOSITE of FD's flight="past").
# Mid-journey / both-flown rows carry flight_expect="past" and override it per-PNR.
# claim_days is meaningless here (there is no claim-filing limit on a booking change) -> None.
_common = C.collect(cur, ids, live, flight="future")
_uniq_enf = any((by.get(i) or {}).get("uniq_names") for i in ids)
print(f"  {'name uniqueness' if _uniq_enf else 'name uniq (info)':18} {_uniq_clean}/{len(ids)}" + ("" if not _uniq_off else f"  DUP/INDB {len(_uniq_off)}: {_uniq_off[:8]}"))
if C.print_check(ids, _common): ok=False
if _uniq_off and _uniq_enf: ok = False
conn.close()
print("PASS ✅ all areas verified" if ok else "FAIL ❌ — see MISS/BAD above")
sys.exit(0 if ok else 1)
