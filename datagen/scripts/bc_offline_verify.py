#!/usr/bin/env python3
"""OFFLINE Booking-Change VOL eligibility verification (no live endpoint needed).

When the CRT rule-engine API Gateway 403s the whole environment (its resource policy is pinned to
one VPC endpoint), `bc_crt_build.py verify` can't reach it. This evaluator reproduces the VOL rule
flow LOCALLY from each PNR's trip-tracer data and asserts the same VBC reason code — using the exact
rule semantics probed against the LIVE endpoint on sets 1-6 (documented in the booking-change memory
and bc_crt_build's header). It is an independent check that the seeded DATA yields the intended
verdict; it does NOT call the service, so it validates data shape against the known rules, not the
running rules. Run it alongside bc_checkpoints; when the endpoint recovers, `verify` reconfirms live.

Rule set (VBC-*, first failing rule in this precedence wins — matches the live segment-eligibility
aggregation order):
  NE-01 rule72hrWindow    minutes-to-departure of the selected bound's first UNFLOWN seg not in (0,4335]
  NE-03 ruleBookingSource bookingSource not in {ACO ADO AC_MOBILE AIRPORT CONTACT_CENTRE NDC 1A_GDS}
  NE-06 ruleTicketStatus  no 014 ticket, or every coupon of the selected bound invalid (flown/void)
  NE-07 ruleCheckinStatus a journey_updates CHECK_IN/LEG_DELIVERY acceptance == ACCEPTED
  NE-05 ruleSsrRestriction any SSR in the blocking lookup
  NE-08 ruleEUpgrade      an EUPG SSR
  NE-04 ruleFareEligibility fareFamily contains BASIC, or fareBasisCode suffix in {BA BV BQ}
  NE-02 ruleCheckInBag    NOT modelled (downstream self-serve check; the live endpoint always passes it)
  -> VBC-EL-01 when no rule fires.

Usage: BC_OUT=<index.json> python3 bc_offline_verify.py [index.json]   (read-only; WARP for the DB only)
"""
import json, sys, datetime
import sc_crt_build as SC
import bc_crt_build as B

IDX = sys.argv[1] if len(sys.argv) > 1 else B.OUT
rows = json.load(open(IDX))
vol = [r for r in rows if r["seed_pnr"] and r["flow"] == "vol" and r["exp"] is not None]

ELIG_SOURCES = {"ACO", "ADO", "AC_MOBILE", "AIRPORT", "CONTACT_CENTRE", "NDC", "1A_GDS"}
BLOCK_SSR = {"UPGD", "UPGO", "GRPS", "CBBG", "MEDA", "UMNR", "PETC", "MEQT", "ESAN", "OXYG",
             "DPNA", "SVAN", "DPLO", "EXST", "AVIH"}
BASIC_SUFFIX = ("BA", "BV", "BQ")
INVALID_COUPON = {"F", "FLOWN", "R", "REFUNDED", "X", "S", "SUSPENDED", "V", "VOID", "Q", "CLOSED",
                  "Z", "REVOKED"}
SOURCE_MAP = {"AC": "ACO"}


def evaluate(pd, bound):
    """Reproduce the VOL rule flow for the SELECTED bound from a db_payload pnrData. -> (code, {rule:ok})."""
    now = datetime.datetime.now(datetime.timezone.utc)
    segs = [s for s in pd["flightSegments"] if s.get("boundRph") == bound] or pd["flightSegments"]
    segids = {s["segmentId"] for s in segs}

    # rule72hrWindow — earliest UNFLOWN segment of the selected bound governs
    def parse(t): return datetime.datetime.strptime(t[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=datetime.timezone.utc)
    # a segment is flown if its correlated coupon is invalid; approximate via coupon status per seg below
    coupons = []
    for t in pd["tickets"]:
        coupons += [(c.get("soldSegment", {}), (c.get("status") or "").upper(), c) for c in t.get("coupons", [])]
    # map coupon -> seg by sequence order within the bound
    bound_deps = sorted(parse(s["departureDatetime"]) for s in segs)
    # unflown seg departures: those whose coupon status is valid
    valid_statuses = [ (c.get("status") or "").upper() for t in pd["tickets"] for c in t.get("coupons",[]) ]
    # simpler: use segment departure + whether ANY coupon for the bound is still valid
    unflown_deps = []
    for s in segs:
        # find a coupon whose soldSegment matches this seg's airports
        flown = False
        for t in pd["tickets"]:
            for c in t.get("coupons", []):
                ss = c.get("soldSegment", {})
                dep = ss.get("departure"); arr = ss.get("arrival")
                dep = dep.get("iataCode") if isinstance(dep, dict) else dep
                arr = arr.get("iataCode") if isinstance(arr, dict) else arr
                if dep == s["departureAirport"] and arr == s["arrivalAirport"]:
                    if (c.get("status") or "").upper() in INVALID_COUPON: flown = True
        if not flown:
            unflown_deps.append(parse(s["departureDatetime"]))
    # The 72hr window rule is only meaningful for a segment you can still change (unflown + future).
    # A bound with NO unflown segment is N/A for this rule (it does NOT fail) — ticket status then
    # governs (all-flown -> VBC-NE-06). Matches live: both-legs-flown returns NE-06, not NE-01.
    if unflown_deps:
        mins = (min(unflown_deps) - now).total_seconds() / 60
        r72 = 0 < mins <= 4335
    else:
        r72 = True    # not applicable -> pass

    # ruleBookingSource
    src = None
    for e in pd.get("edsPnr", []):
        bc = e.get("bookingContext") or {}
        if bc.get("bookingSource"): src = bc["bookingSource"]
    src = SOURCE_MAP.get(src, src)
    rsrc = src in ELIG_SOURCES

    # ruleTicketStatus — >=1 ticket, and the selected bound has at least one valid coupon
    has_ticket = any((d or "").startswith("014") for t in pd["tickets"] for d in [t.get("primaryDocumentNumber")])
    bound_coupon_valid = False
    for t in pd["tickets"]:
        for c in t.get("coupons", []):
            ss = c.get("soldSegment", {})
            dep = ss.get("departure"); arr = ss.get("arrival")
            dep = dep.get("iataCode") if isinstance(dep, dict) else dep
            arr = arr.get("iataCode") if isinstance(arr, dict) else arr
            if any(dep == s["departureAirport"] and arr == s["arrivalAirport"] for s in segs):
                if (c.get("status") or "").upper() not in INVALID_COUPON: bound_coupon_valid = True
    rtkt = has_ticket and bound_coupon_valid

    # ruleCheckinStatus
    checked_in = False
    for ju in pd.get("journeyUpdates", []):
        d = ju.get("data") or {}
        for ld in (d.get("segment", {}).get("legDeliveries") or []):
            if (ld.get("acceptance") or {}).get("status") == "ACCEPTED": checked_in = True
    rchk = not checked_in

    ssr_codes = {(s.get("code") or "").strip() for s in pd.get("specialServiceRequests", [])}
    rssr = not (ssr_codes & BLOCK_SSR)
    reup = "EUPG" not in ssr_codes

    # ruleFareEligibility
    basic = False
    for t in pd["tickets"]:
        for c in t.get("coupons", []):
            ff = c.get("fareFamily"); ff = ff.get("code") if isinstance(ff, dict) else ff
            fb = c.get("fareBasisCode") or ""
            if (ff and "BASIC" in str(ff).upper()) or fb.upper().endswith(BASIC_SUFFIX): basic = True
    rfare = not basic

    status = {"rule72hrWindow": r72, "ruleBookingSource": rsrc, "ruleTicketStatus": rtkt,
              "ruleCheckinStatus": rchk, "ruleSsrRestriction": rssr, "ruleEUpgrade": reup,
              "ruleFareEligibility": rfare}
    # first failing rule in the live aggregation precedence wins
    order = [("rule72hrWindow", "VBC-NE-01"), ("ruleBookingSource", "VBC-NE-03"),
             ("ruleTicketStatus", "VBC-NE-06"), ("ruleCheckinStatus", "VBC-NE-07"),
             ("ruleSsrRestriction", "VBC-NE-05"), ("ruleEUpgrade", "VBC-NE-08"),
             ("ruleFareEligibility", "VBC-NE-04")]
    for rule, code in order:
        if not status[rule]: return code, status
    return "VBC-EL-01", status


def main():
    conn = SC.tt_conn(); ok = 0; bad = []
    print(f"OFFLINE VOL eligibility — {IDX}  ({len(vol)} VOL cases)")
    for r in vol:
        pd = SC.db_payload(r["pnr_id"], r["bound"], conn)
        if pd is None:
            bad.append((r["tc"], r["pnr"], "no trip row")); continue
        code, status = evaluate(pd["pnrData"], r["bound"])
        good = code == r["exp"]
        ok += good
        if not good:
            bad.append((r["tc"], r["pnr"], f"exp {r['exp']} got {code}", json.dumps(status)))
        print(f"  {r['tc']:20} {r['pnr']} bound{r['bound']} -> {code} "
              f"{'OK' if good else '<<< MISMATCH'}", flush=True)
    conn.close()
    print(f"[offline] {ok}/{len(vol)} VOL cases match expected")
    for b in bad: print("   ", b)
    sys.exit(0 if ok == len(vol) else 1)


if __name__ == "__main__":
    main()
