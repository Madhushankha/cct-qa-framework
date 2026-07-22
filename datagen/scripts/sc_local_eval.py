#!/usr/bin/env python3
"""Seat Change LOCAL rule evaluator — offline verification when the live eligibility
endpoint is unreachable (private-API-Gateway 403 from an off-VPC network path).

Seat-change eligibility is stateless + deterministic, so unlike FD there is NOTHING pinned
to S3 to fall back to. The faithful equivalent is to RE-COMPUTE the verdict locally from the
exact same inputs the service reads, using the rule flow probed live against sets 1-9:

  SC-NE-02  booking_source empty
  SC-NE-03  booking_source not in the eligible-channel set
  SC-NE-01  any segment of the bound has marketing OR operating carrier not in {AC,QK,RV}
  SC-NE-04  ticket not 014 stock, missing, or all coupons flown/void (per passenger)
  SC-NE-05  <24h to first-segment departure, or departed (OUT_OF_SCOPE)
  SC-NE-06  a blocking SSR present (EXST/CBBG/SVAN/ESAN)
  SC-NE-07  booking_source==GROUP and <6h to departure
  SC-NE-08  passenger checked in (journey_updates CHECK_IN acceptance=ACCEPTED)
  SC-EL-01  all rules pass; window VOID if booked <=24h ago else NON_VOID
A bound is eligible iff at least one passenger passes every rule.

This reads each PNR's pnrData straight from trip-tracer via sc_crt_build.db_payload (the SAME
payload the chatbot would POST), so it exercises the real cascaded data, not the index.

Usage: python3 sc_local_eval.py <index.json>
"""
import json, sys, datetime
import sc_crt_build as B

ELIGIBLE_SRC = {"AC_ONLINE","ACO","AC_MOBILE","CONTACT_CENTRE","AIRPORT","NDC","1A_GDS","GDS_1A",
                "GROUP","AEROPLAN","AC_VACATIONS","ACV","ADO","AGENCY_DIRECT_ONLINE"}
AC_FAMILY   = {"AC","QK","RV"}
BLOCK_SSR   = {"EXST","CBBG","SVAN","ESAN"}
INVALID_CPN = {"F","FLOWN","R","REFUNDED","X","S","SUSPENDED","V","VOID","Q","CLOSED","Z","REVOKED"}
BOOKING_SOURCE_MAP = {"AC":"ACO"}   # SP router mapping, mirrored in db_payload


def _dt(s):
    return datetime.datetime.fromisoformat(s.replace("Z","+00:00"))


def evaluate(payload, now):
    """Return (reason_code, is_eligible, window, per-rule status) for the selected bound."""
    pd = payload["pnrData"]; bound = payload["changeTrigger"]["selectedBound"]
    src = pd.get("source")
    segs = [s for s in pd["flightSegments"] if s.get("boundRph") == bound]
    st = {}

    # booking channel
    if not src: st["BookingChannel"] = ("fail","SC-NE-02")
    elif src not in ELIGIBLE_SRC: st["BookingChannel"] = ("fail","SC-NE-03")
    else: st["BookingChannel"] = ("pass",None)

    # carrier mix (every segment of the bound)
    cm = "pass"
    for s in segs:
        if (s.get("marketingCarrierCode") not in AC_FAMILY or
                s.get("operatingCarrierCode") not in AC_FAMILY):
            cm = "fail"; break
    st["CarrierMix"] = (cm, "SC-NE-01" if cm == "fail" else None)

    # time window
    dep = min((_dt(s["departureDatetime"]) for s in segs), default=None)
    created = _dt(pd["createdAt"])
    mins_since_booking = (now - created).total_seconds()/60
    mins_to_dep = ((dep - now).total_seconds()/60) if dep else None
    if dep is None:
        st["TimeWindow"] = ("fail","SC-NE-05"); window = None
    elif mins_since_booking <= 1440:
        st["TimeWindow"] = ("pass",None); window = "VOID"
    elif mins_to_dep >= 1440:
        st["TimeWindow"] = ("pass",None); window = "NON_VOID"
    else:
        st["TimeWindow"] = ("fail","SC-NE-05"); window = "OUT_OF_SCOPE"

    # group PNR (<6h)
    if src == "GROUP" and dep is not None and mins_to_dep < 360:
        st["GroupPnr"] = ("fail","SC-NE-07")
    else:
        st["GroupPnr"] = ("not_applicable" if src != "GROUP" else "pass", None)

    # per-passenger rules: ticket, ssr, checkin
    ssr_by_pax = {}
    for s in pd.get("specialServiceRequests") or []:
        ssr_by_pax.setdefault(s.get("passengerId"), []).append((s.get("code") or "").strip())
    checked_in = set()
    for ju in pd.get("journeyUpdates") or []:
        d = ju.get("data") or {}
        for ld in (d.get("segment", {}) or {}).get("legDeliveries", []) or []:
            if (ld.get("acceptance") or {}).get("status") == "ACCEPTED":
                if d.get("pnrTravelerId"): checked_in.add(d["pnrTravelerId"])
    tkt_by_pax = {}
    for t in pd.get("tickets") or []:
        tkt_by_pax.setdefault(t.get("passengerId"), []).append(t)

    def ticket_ok(ppid):
        ts = tkt_by_pax.get(ppid, [])
        if not ts: return False
        for t in ts:
            doc = t.get("primaryDocumentNumber") or ""
            if not doc.startswith("014"): return False
            cps = t.get("coupons") or []
            if cps and all((c.get("status") or "").upper() in INVALID_CPN for c in cps): return False
        return True

    pax_pass = []
    for p in pd["passengers"]:
        ppid = p["passengerId"]
        ok = (st["BookingChannel"][0] == "pass" and st["CarrierMix"][0] == "pass"
              and st["TimeWindow"][0] == "pass" and st["GroupPnr"][0] != "fail")
        tk = ticket_ok(ppid)
        blk = any(c in BLOCK_SSR for c in ssr_by_pax.get(ppid, []))
        ci = ppid in checked_in
        st.setdefault("TicketStatus", ("pass",None))
        st.setdefault("SsrRestriction", ("pass",None))
        st.setdefault("CheckinStatus", ("pass",None))
        if not tk: st["TicketStatus"] = ("fail","SC-NE-04")
        if blk:    st["SsrRestriction"] = ("fail","SC-NE-06")
        if ci:     st["CheckinStatus"] = ("fail","SC-NE-08")
        pax_pass.append(ok and tk and not blk and not ci)

    # first failing rule (booking-level precedence, then per-pax) drives the reason code
    order = ["CarrierMix","BookingChannel","TimeWindow","TicketStatus","SsrRestriction","GroupPnr","CheckinStatus"]
    eligible = any(pax_pass)
    if eligible:
        return "SC-EL-01", True, window, st
    for k in order:
        if st.get(k, ("pass",None))[0] == "fail":
            return st[k][1], False, window, st
    return "SC-NE-01", False, window, st


def main():
    idx = sys.argv[1] if len(sys.argv) > 1 else B.OUT
    rows = [r for r in json.load(open(idx)) if r["seed_pnr"]]
    now = datetime.datetime.now(datetime.timezone.utc)
    conn = B.tt_conn()
    ok = 0; bad = []
    for r in rows:
        p = B.db_payload(r["pnr_id"], r["bound"], conn)
        if p is None:
            bad.append((r["tc"], r["pnr"], "no trip row")); continue
        code, elig, win, st = evaluate(p, now)
        good = (code == r["exp_reason"] and elig == r["exp_elig"] and win == r["exp_win"])
        ok += good
        mark = "OK" if good else "<<< MISMATCH"
        print(f"  {r['tc']:20} {r['pnr']} b{r['bound']} -> {code} {win} elig={elig} {mark}", flush=True)
        if not good:
            bad.append((r["tc"], r["pnr"], f"exp {r['exp_elig']}/{r['exp_win']}/{r['exp_reason']} "
                        f"got {elig}/{win}/{code}"))
    conn.close()
    print(f"\n[local-eval] {ok}/{len(rows)} match expected (offline rule computation)")
    for b in bad: print("   ", b)
    print("LOCAL EVAL PASS ✅" if ok == len(rows) else "LOCAL EVAL FAIL ❌")
    sys.exit(0 if ok == len(rows) else 1)


if __name__ == "__main__":
    main()
