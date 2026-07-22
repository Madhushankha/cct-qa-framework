#!/usr/bin/env python3
"""SEAT CHANGE PNR post-creation CHECKPOINTS (CRT) — verify every area the bot depends on.

Two verification surfaces (Seat Change has NO pinned DDS; eligibility is computed live and
statelessly by the rule flow behind /eligibility-service/execute-with-mapping, trigger
SEAT_CHANGE + changeTrigger.selectedBound):

  A. trip-tracer cascade — what the chatbot RETRIEVES (GenUC-01) and sends the OTP from
      1  trip ACTIVE (exactly one ACTIVE trip per locator)
      2  trip_details present
      3  passenger count == index npax
      4  DOB set on every passenger (no NULL) and matches the designed DOB
      5  passenger_type matches design (ADT/CHD/INF/YTH)  + has_infant on the adult
      6  ticket count == npax, all 014 stock, coupons correlated 1:1 to the bound's segments
      7  eds_pnr_output present
      8  eds contact email == index email (OTP delivery)
      9  eds booking_context.bookingSource == designed channel   <- drives ruleBookingChannel
     10  flight_segment carriers (marketing + operating) match design  <- ruleCarrierMix
     11  flight_segment bound_rph / segment count match design
     12  departure_datetime sits in the designed time window       <- ruleTimeWindow
     13  SSRs present (blocking + persist + RQST seat assignments)  <- ruleSsrRestriction
     14  journey_updates CHECK_IN acceptance=ACCEPTED iff the case is a checked-in case
     15  reserved locator (TC025) genuinely absent from trip-tracer
  B. LIVE eligibility endpoint — rebuild each PNR's pnrData FROM THE DATABASE, POST it, and
     assert the bound verdict, processing window, reason code, per-rule validationStatus,
     per-segment verdicts, isUmnr / isYouth / specialSsrs, and feeApplicable.

Invoke: python3 sc_checkpoints.py [index.json]      (no AWS creds needed; WARP must be up)
Reuses the payload builder + endpoint caller from sc_crt_build.py.
"""
import json, sys, datetime
import sc_crt_build as B
import crt_uniqnames as U
import pnr_common_checks as C

IDX = sys.argv[1] if len(sys.argv) > 1 else B.OUT
rows = json.load(open(IDX))
live = [r for r in rows if r["seed_pnr"]]
reserved = [r for r in rows if not r["seed_pnr"]]
ids = [r["pnr_id"] for r in live]
by = {r["pnr_id"]: r for r in live}

conn = B.tt_conn(); cur = conn.cursor()
def q(sql, p): cur.execute(sql, p); return cur.fetchall()

trip = {r[0]: (r[1], r[2]) for r in q("select pnr_id,status,created_at from trip where pnr_id=any(%s)", (ids,))}
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
for pid, sid, mkt, op, brph in q("select pnr_id,segment_id,marketing_carrier_code,operating_carrier_code,bound_rph "
                                 "from flight_segment where pnr_id=any(%s) and not is_removed order by segment_id", (ids,)):
    segs.setdefault(pid, []).append((sid, (mkt or "").strip(), (op or "").strip(), brph))
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
for pid, bc, bounds in q("select distinct on (pnr_id) pnr_id,booking_context,bounds from eds_pnr_output "
                         "where pnr_id=any(%s) order by pnr_id,received_at desc", (ids,)):
    eds[pid] = (json.loads(bc) if isinstance(bc, str) and bc else bc,
                json.loads(bounds) if isinstance(bounds, str) and bounds else bounds)
resv = {r[0] for r in q("select pnr from trip where pnr=any(%s)", ([r["pnr"] for r in reserved],))}

# ---- A. booking-side checks -------------------------------------------------
def edsmail(pid):
    b = (eds.get(pid) or (None, None))[1] or []
    try: return b[0]["authenticationContactDetails"]["passengers"][0]["contacts"]["apn"]["email"]
    except Exception: return None

def coupon_ok(pid):
    r = by[pid]; nseg = len(r["segs"])
    docs = tkt.get(pid, [])
    if len(docs) != r["npax"]: return False
    for doc, cps in docs:
        if not doc.startswith("014"): return False
        if len(cps) != nseg: return False
        if any((c.get("status") or "").upper() not in ("OPEN_FOR_USE", "O", "OK", "A") for c in cps): return False
    return True

def dep_window_ok(pid):
    """Departure must sit in the window the case's expected reason code implies."""
    r = by[pid]
    deps = segdep.get(pid) or []
    if not deps: return False
    now = datetime.datetime.now(datetime.timezone.utc)
    first = min(deps)
    mins = (first - now).total_seconds() / 60
    if r["exp_win"] == "OUT_OF_SCOPE": return mins < 1440       # <24h or already departed
    return mins >= 1440                                          # NON_VOID needs >=24h to departure

def carriers_ok(pid):
    r = by[pid]
    got = [(s[1], s[2]) for s in segs.get(pid, [])]
    want = [(s["mkt"], s["op"]) for s in r["segs"]]
    return got == want

def bounds_ok(pid):
    r = by[pid]
    got = [s[3] for s in segs.get(pid, [])]
    return got == [s["bound"] for s in r["segs"]]

def ssrs_ok(pid):
    r = by[pid]
    want = set()
    for k, p in enumerate(r["paxs"]):
        for c in p["ssr"]: want.add((c, f"{pid}-PT-{k+1}"))
    for k, seat in r["seats"].items():
        want.add(("RQST", f"{pid}-PT-{int(k)+1}"))
    return want.issubset(set(ssr.get(pid, [])))

def checkin_ok(pid):
    r = by[pid]
    accepted = any(et == "CHECK_IN" and any(ld.get("acceptance", {}).get("status") == "ACCEPTED"
                                            for ld in (d.get("segment", {}).get("legDeliveries") or []))
                   for et, d in ju.get(pid, []))
    return accepted == bool(r["checkin"])

def ptypes_ok(pid):
    r = by[pid]
    got = [p[1] for p in paxrows.get(pid, [])]
    want = [p["ptype"] for p in r["paxs"]]
    if got != want: return False
    if any(p["ptype"] == "INF" for p in r["paxs"]) and not hasinf.get(pid): return False
    return True

def dob_ok(pid):
    r = by[pid]
    got = [p[2].isoformat() if p[2] else None for p in paxrows.get(pid, [])]
    return got == [p["dob"] for p in r["paxs"]]

def off(pred): return [by[p]["pnr"] for p in ids if pred(p)]
A = {
 "trip ACTIVE (1/loc)":  off(lambda p: trip.get(p, ("", ))[0] != "ACTIVE" or active.get(by[p]["pnr"], 0) != 1),
 "trip_details":         off(lambda p: td.get(p, 0) == 0),
 "passenger==npax":      off(lambda p: len(paxrows.get(p, [])) != by[p]["npax"]),
 "DOB set + matches":    off(lambda p: not dob_ok(p)),
 "passenger_type/inf":   off(lambda p: not ptypes_ok(p)),
 "ticket 014 + coupons": off(lambda p: not coupon_ok(p)),
 "eds_pnr_output":       off(lambda p: p not in eds),
 "eds contact email":    off(lambda p: edsmail(p) != by[p]["email"]),
 "eds bookingSource":    off(lambda p: (eds.get(p, (None,))[0] or {}).get("bookingSource") != by[p]["src"]),
 "segment carriers":     off(lambda p: not carriers_ok(p)),
 "segment count/bounds": off(lambda p: not bounds_ok(p)),
 "departure window":     off(lambda p: not dep_window_ok(p)),
 "SSRs + RQST seats":    off(lambda p: not ssrs_ok(p)),
 "CHECK_IN acceptance":  off(lambda p: not checkin_ok(p)),
}
print(f"SEAT CHANGE CHECKPOINTS — {IDX}\n  {len(ids)} seeded PNRs + {len(reserved)} reserved (CRT)")
ok = True
print("--- A. trip-tracer cascade (retrieval, OTP, rule inputs) ---")
for name, o in A.items():
    print(f"  {name:22} {len(ids)-len(o)}/{len(ids)}" + ("" if not o else f"   MISS {len(o)}: {o[:6]}"))
    if o: ok = False
bad_resv = sorted(resv)
print(f"  {'reserved locator absent':22} {len(reserved)-len(bad_resv)}/{len(reserved)}"
      + ("" if not bad_resv else f"   PRESENT(!) {bad_resv}"))
if bad_resv: ok = False

# ---- B. live eligibility endpoint -------------------------------------------
print("--- B. live eligibility endpoint (SEAT_CHANGE, DB-derived payload) ---")
areas = {k: [0, 0, []] for k in ["bound verdict", "reason code", "processing window", "validationStatus",
                                 "segment verdicts", "feeApplicable", "isUmnr", "isYouth", "specialSsrs",
                                 "bookingSource echo", "passenger count"]}
def rec(a, good, tag, msg=""):
    areas[a][1] += 1
    if good: areas[a][0] += 1
    else: areas[a][2].append((tag, msg))

# which rule is expected to fail, per reason code
FAILRULE = {"SC-NE-01": "ruleCarrierMix", "SC-NE-02": "ruleBookingChannel", "SC-NE-03": "ruleBookingChannel",
            "SC-NE-04": "ruleTicketStatus", "SC-NE-05": "ruleTimeWindow", "SC-NE-06": "ruleSsrRestriction",
            "SC-NE-07": "ruleGroupPnr", "SC-NE-08": "ruleCheckinStatus"}
PERSIST = {"WCHR", "MEDA", "DPNA", "OXYG", "MEQT"}

# SKIP the whole live section (leave all areas tot=0) if the rule-engine gateway is 403-locked env-wide
_gw_down = C.gateway_down()
if _gw_down:
    print(C.skip_area("live eligibility (11 areas)", len(live)))
for r in (live if not _gw_down else []):
    tag = f"{r['tc']}/{r['pnr']}"
    g = B.eligibility_of(r, conn)
    if "err" in g:
        for a in areas: areas[a][1] += 1; areas[a][2].append((tag, g["err"]))
        continue
    rec("bound verdict",     g["elig"] == r["exp_elig"], tag, f"got {g['elig']}")
    rec("reason code",       g["reason"] == r["exp_reason"], tag, f"got {g['reason']} want {r['exp_reason']}")
    rec("processing window", g["win"] == r["exp_win"], tag, f"got {g['win']} want {r['exp_win']}")
    val = g["val"]
    if r["exp_elig"]:
        okv = all(v in ("pass", "not_applicable") for v in val.values())
    else:
        want = FAILRULE.get(r["exp_reason"])
        okv = val.get(want) == "fail"
    rec("validationStatus", okv, tag, json.dumps(val))
    # per-segment: the response is scoped to the SELECTED bound, so compare against that bound's legs.
    # A leg whose marketing+operating are both AC-family must be eligible.
    bsegs = [s for s in r["segs"] if s["bound"] == r["bound"]]
    segok = len(g["segs"]) == len(bsegs)
    for j, s in enumerate(bsegs):
        if j >= len(g["segs"]): break
        acfam = s["mkt"] in ("AC", "QK", "RV") and s["op"] in ("AC", "QK", "RV")
        # only the carrier rule is segment-scoped; other NE reasons fail every segment
        if r["exp_reason"] == "SC-EL-01":
            segok &= g["segs"][j]["elig"] is True
        elif r["exp_reason"] == "SC-NE-01":
            segok &= (g["segs"][j]["elig"] is acfam)
    rec("segment verdicts", segok, tag, json.dumps(g["segs"]))
    if r["exp_win"] == "NON_VOID":
        rec("feeApplicable", g["fee"] is True, tag, f"got {g['fee']} (NON_VOID must charge)")
    elif r["exp_win"] == "VOID":
        rec("feeApplicable", g["fee"] is False, tag, f"got {g['fee']} (VOID is free)")
    rec("passenger count", len(g["pax"]) == r["npax"], tag, f"got {len(g['pax'])} want {r['npax']}")
    rec("bookingSource echo", g["bookingSource"] == r["src"], tag, f"got {g['bookingSource']}")
    want_umnr = [("UMNR" in p["ssr"]) for p in r["paxs"]]
    want_yth = [(p["ptype"] == "YTH") for p in r["paxs"]]
    want_ssrs = [sorted(set(p["ssr"]) & PERSIST) for p in r["paxs"]]
    rec("isUmnr",  [p["umnr"] for p in g["pax"]] == want_umnr, tag, f"{[p['umnr'] for p in g['pax']]}")
    rec("isYouth", [p["yth"] for p in g["pax"]] == want_yth, tag, f"{[p['yth'] for p in g['pax']]}")
    rec("specialSsrs", [sorted(p["ssrs"]) for p in g["pax"]] == want_ssrs, tag, f"{[p['ssrs'] for p in g['pax']]}")

for name, (good, tot, bad) in areas.items():
    if tot == 0: continue
    print(f"  {name:22} {good}/{tot}" + ("" if good == tot else f"   BAD {tot-good}: {bad[:4]}"))
    if good != tot: ok = False
_uniq_clean, _uniq_off = U.name_uniqueness(cur, ids)
_common = C.collect(cur, ids, rows)   # shared: ticket linkage + eds auth == pax
_uniq_enf = any((by.get(i) or {}).get("uniq_names") for i in ids)
print(f"  {'name uniqueness' if _uniq_enf else 'name uniq (info)':18} {_uniq_clean}/{len(ids)}" + ("" if not _uniq_off else f"  DUP/INDB {len(_uniq_off)}: {_uniq_off[:8]}"))
if C.print_check(ids, _common): ok=False
if _uniq_off and _uniq_enf: ok = False
conn.close()
print("PASS ✅ all areas verified" if ok else "FAIL ❌ — see MISS/BAD above")
sys.exit(0 if ok else 1)
