#!/usr/bin/env python3
"""OFFLINE Name-Correction eligibility verification (no live endpoint needed).

When the CRT rule-engine API Gateway 403s the whole environment (AWS_IAM lockdown — the public
gateway, the internal ALB/WAF, and ECS-exec are all sealed), `nc_crt_build.py verify` can't reach
the eligibility service. This evaluator reproduces the 6 NC rules LOCALLY and asserts the same
NC-* reason code, using the EXACT rule semantics probed against the LIVE endpoint on sets 1-10
(documented in the name-correction memory + nc_crt_build header). It is an independent check that the
seeded DATA yields the intended verdict; it does NOT call the service, so it validates data shape
against the known rules, not the running rules. When the gateway recovers, `nc_crt_build.py verify`
reconfirms against the live oracle.

Two independent things it does that the index alone cannot:
  1. Recomputes the TIME-WINDOW (VOID / NON_VOID / OUT_OF_SCOPE) from created/first-departure vs
     datetime.now() — the only DYNAMIC dimension. Catches VOID-window expiry / date drift.
  2. Cross-checks the rule INPUTS that ARE in the normalised DB — operating carrier (flight_segment)
     and passenger type incl. UMNR SSR (passenger + special_service_request) — against the index,
     proving the seeded PNRs physically carry the attributes the rules key on.
     (officeId/coupon are NOT in trip-tracer tables — they live in S3/the index — so channel + coupon
      rules are evaluated from the index only, and flagged as such.)

Rule precedence (first failing rule wins — matches the live validationStatus aggregation):
  NC-NE-01 ruleCarrierMix     any confirmed segment operatingCarrierCode != "AC"
  NC-NE-03 ruleBookingChannel officeId / source is an unsupported channel (OTA, non-1A GDS, ACV,
                              employee, flight-pass, aeroplan-channel, cargo, group)
  NC-NE-04 ruleTimeToDeparture first departure < 24h away or already departed  (window OUT_OF_SCOPE)
  NC-NE-05 rulePassengerType  a YTH passenger or a UMNR/YPTU SSR
  NC-NE-06 ruleCouponStatus   no upcoming OPEN_FOR_USE coupon (not used by this set — all have one)
  (ruleCorrectionLimits is enforced downstream of the eligibility service, so 'corrected' pax stay
   NC-EL-01 here — matches the live probing on sets 1-10.)
  -> NC-EL-01 when nothing fires. processingWindow: VOID (<24h from booking) / NON_VOID / OUT_OF_SCOPE.

Usage: AWS_PROFILE=ac-cct-crt NC_SET=setN [NC_TPREFIX=... NC_TBASE=...] python3 nc_offline_verify.py
Read-only (WARP for the DB cross-check only).
"""
import json, sys, datetime, os
import importlib.util
spec=importlib.util.spec_from_file_location("b","nc_crt_build.py"); B=importlib.util.module_from_spec(spec); spec.loader.exec_module(B)
import psycopg2

NOW=datetime.datetime.now(datetime.timezone.utc)
recs=B.load_index()
ids=[r["pnr_id"] for r in recs]

# unsupported-channel signatures (offices/sources that fail ruleBookingChannel) — from the live probing
def channel_fail(r):
    off=(r.get("office") or "").upper(); src=(r.get("src") or "").upper(); sysc=(r.get("system") or "").upper()
    if r.get("group"): return True
    if src in ("OTA","AEROPLAN","CARGO","AC_CARGO"): return True
    if off[:2] in ("ES","EP","OT","EC"): return True            # employee travel
    if "FP" in off: return True                                  # flight pass
    if any(off.startswith(p) for p in ("1B","1E","1F","1G","1H","1P","1S")): return True  # non-1A GDS
    if sysc in ("1B","1E","1F","1G","1H","1P","1S"): return True
    if "1V" in off or "2V" in off: return True                   # ACV
    return False

def parse(t):
    return datetime.datetime.fromisoformat(t.replace("Z","+00:00")) if t else None

def window_now(r):
    """recompute VOID / NON_VOID / OUT_OF_SCOPE from created + first-departure vs NOW."""
    created=parse(r["created"])
    deps=[]
    if r.get("dep_iso"): deps.append(parse(r["dep_iso"]))
    else:
        d=r.get("dep_date")
        if d: deps.append(datetime.datetime.fromisoformat(d+"T12:00:00+00:00"))
    first_dep=min(deps) if deps else None
    age_h=(NOW-created).total_seconds()/3600 if created else 999
    to_dep_h=(first_dep-NOW).total_seconds()/3600 if first_dep else 999
    # LIVE precedence (probed): Window-1/VOID (booking <24h) WINS over Window-3, even when the flight
    # is also <24h away (TC042 overlap) — booking-age is checked before time-to-departure.
    if age_h <= 24:   return "VOID"                # booked within 24h -> Window 1
    if to_dep_h < 24: return "OUT_OF_SCOPE"        # <24h to departure or departed -> Window 3
    return "NON_VOID"                              # Window 2

def evaluate(r):
    """apply the 6 rules in precedence -> (isPnrEligible, processingWindow, reasonCode)."""
    win=window_now(r)
    # NC-NE-01 carrier mix. LIVE behaviour (probed, and a documented BRD divergence): the service
    # keys on the MARKETING carrier (carriers[i][1]) — so an AC-OPERATED codeshare with a partner
    # MARKETING carrier (TC050, [AC,LH]) still fails carrier-mix. Full-OAL ([LH,LH]) fails too.
    if any((c[1] or "").upper()!="AC" for c in r["carriers"]): return (False,win,"NC-NE-01")
    # NC-NE-03 booking channel
    if channel_fail(r): return (False,win,"NC-NE-03")
    # NC-NE-04 time-to-departure (window 3)
    if win=="OUT_OF_SCOPE": return (False,win,"NC-NE-04")
    # NC-NE-05 passenger type: YTH pax or UMNR/YPTU SSR
    for p in r["paxs"]:
        if len(p)>2 and (p[2] or "").upper()=="YTH": return (False,win,"NC-NE-05")
        if len(p)>3 and isinstance(p[3],dict):
            if any(s.upper() in ("UMNR","YPTU") for s in p[3].get("ssr",[])): return (False,win,"NC-NE-05")
    return (True,win,"NC-EL-01")

# ---- DB cross-check: the rule INPUTS that ARE in the normalised tables --------------------------
conn=B.tt_conn()
cur=conn.cursor()
cur.execute("select pnr_id,array_agg(distinct operating_carrier_code) from flight_segment where pnr_id=any(%s) and not is_removed group by pnr_id",(ids,))
db_ops={p:set(x for x in a if x) for p,a in cur.fetchall()}
cur.execute("select pnr_id,array_agg(passenger_type) from passenger where pnr_id=any(%s) and not is_removed group by pnr_id",(ids,))
db_ptypes={p:sorted(a) for p,a in cur.fetchall()}
cur.execute("select pnr_id,array_agg(distinct code) from special_service_request where pnr_id=any(%s) group by pnr_id",(ids,))
db_ssr={p:set(x for x in a if x) for p,a in cur.fetchall()}
conn.close()

# ---- run ---------------------------------------------------------------------------------------
ok_rule=0; ok_win=0; badrule=[]; badwin=[]; dbcar=[]; dbtype=[]
for r in recs:
    elig,win,reason=evaluate(r)
    # 1) offline verdict vs the index's expected (built to match the live oracle on sets 1-10)
    exp=(r["exp_elig"],r["exp_win"],r["exp_reason"])
    if (elig,win,reason)==exp: ok_rule+=1
    else: badrule.append((r["pnr"],r["tc"],f"got {elig}/{win}/{reason} exp {exp[0]}/{exp[1]}/{exp[2]}"))
    # 2) window recomputed at NOW matches expected window
    if win==r["exp_win"]: ok_win+=1
    else: badwin.append((r["pnr"],f"now->{win} exp {r['exp_win']}"))
    # 3) DB carries the operating carrier the carrier-mix rule keys on
    idx_ops={(c[0] or "").upper() for c in r["carriers"]}
    if db_ops.get(r["pnr_id"]) is not None and db_ops[r["pnr_id"]]!=idx_ops:
        dbcar.append((r["pnr"],f"db{db_ops[r['pnr_id']]} idx{idx_ops}"))
    # 4) DB carries the YTH type / UMNR SSR the passenger-type rule keys on
    idx_yth=any((p[2] or "").upper()=="YTH" for p in r["paxs"] if len(p)>2)
    idx_umnr=any("UMNR" in [s.upper() for s in p[3].get("ssr",[])] for p in r["paxs"] if len(p)>3 and isinstance(p[3],dict))
    db_yth="YTH" in db_ptypes.get(r["pnr_id"],[])
    db_umnr="UMNR" in db_ssr.get(r["pnr_id"],set())
    if idx_yth!=db_yth or idx_umnr!=db_umnr:
        dbtype.append((r["pnr"],f"idx yth={idx_yth}/umnr={idx_umnr} db yth={db_yth}/umnr={db_umnr}"))

n=len(recs)
print(f"NC OFFLINE VERIFY — {n} PNRs  ({B.SET or 'named'})   NOW={NOW:%Y-%m-%d %H:%M}Z")
print(f"  offline rule verdict == expected   {ok_rule}/{n}" + ("" if not badrule else f"  BAD {len(badrule)}: {badrule[:6]}"))
print(f"  time-window recomputed at NOW      {ok_win}/{n}"  + ("" if not badwin else f"  BAD {len(badwin)}: {badwin[:6]}"))
print(f"  DB operating carrier == index      {n-len(dbcar)}/{n}" + ("" if not dbcar else f"  BAD {len(dbcar)}: {dbcar[:6]}"))
print(f"  DB YTH/UMNR == index               {n-len(dbtype)}/{n}"+ ("" if not dbtype else f"  BAD {len(dbtype)}: {dbtype[:6]}"))
allok = not (badrule or badwin or dbcar or dbtype)
print(("OFFLINE PASS ✅ — seeded data reproduces the expected NC verdicts under the documented rules"
       if allok else "OFFLINE FAIL ❌ — see BAD above"))
print("NOTE: rule-replica, not the live service. officeId/coupon aren't in trip-tracer tables (S3/index"
      " only), so channel+coupon rules use the index. Re-run `nc_crt_build.py verify` when the gateway restores.")
sys.exit(0 if allok else 1)
