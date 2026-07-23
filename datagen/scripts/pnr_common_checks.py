#!/usr/bin/env python3
"""Shared post-creation checks used by EVERY *_checkpoints.py (fd / anc / bag / bc / nc / nmvp / sc).

Both checks here were added 2026-07-13 after a deep audit found defects that the existing
"is it present?" checks passed straight over:

  ticket linkage  — a ticket row must link to a passenger of THIS pnr and be document_type='T'.
                    The usual `ticket==npax` count check can't see a ticket that is present but
                    wired to the wrong passenger_id.

  eds auth == pax — eds_pnr_output.authenticationContactDetails.passengers must have exactly as
                    many entries as the booking has passengers. eds rows are CLONED FROM A DONOR
                    pnr, so if that donor later gains/loses a passenger every set built from it
                    silently ships a wrong auth block. Real hit: donor MHYLXV was converted to
                    2-pax, which pushed a phantom PT-2 auth entry onto a 1-pax booking (KNVKKZ).

Usage (mirrors crt_uniqnames — collect BEFORE cur.close(), print with the other areas):

    import pnr_common_checks as C
    _cc = C.collect(cur, ids)            # while the cursor is still open
    ...
    if C.print_check(ids, _cc): ok=False # in the print section
"""
import json


def _paxcount(cur, ids):
    cur.execute("""SELECT pnr_id,count(*) FROM passenger
                   WHERE pnr_id=ANY(%s) AND NOT is_removed GROUP BY pnr_id""", (ids,))
    return dict(cur.fetchall())


def ticket_linkage(cur, ids):
    """Offenders: any pnr with a ticket row whose passenger_id doesn't belong to it, or type != 'T'."""
    cur.execute("""SELECT pnr_id,primary_document_number,passenger_id,document_type
                   FROM ticket WHERE pnr_id=ANY(%s)""", (ids,))
    bad = set()
    for pid, doc, pxid, dtype in cur.fetchall():
        if not pxid or not str(pxid).startswith(pid) or dtype != "T":
            bad.add(pid)
    return sorted(bad)


def eds_auth_pax(cur, ids, paxn=None):
    """Offenders: eds auth-passenger count != real passenger count (donor-drift guard)."""
    if paxn is None:
        paxn = _paxcount(cur, ids)
    cur.execute("""SELECT DISTINCT ON (pnr_id) pnr_id,bounds FROM eds_pnr_output
                   WHERE pnr_id=ANY(%s) ORDER BY pnr_id,received_at DESC""", (ids,))
    bad = []
    for pid, b in cur.fetchall():
        try:
            bb = json.loads(b) if isinstance(b, str) else b
            aps = bb[0]["authenticationContactDetails"]["passengers"]
            if len(aps) != paxn.get(pid, 0):
                bad.append(pid)
        except Exception:
            pass          # eds missing/unparseable is already covered by the eds_pnr_output area
    return sorted(bad)


def eds_contact_phone(cur, by):
    """Offenders: eds apn.phone != index phone. The eds-inject regex only swaps the EMAIL, so the
    contact PHONE silently stays the DONOR's number — wrong on every set whose assigned phone
    differs from the donor's (found 2026-07-14: gimhan/doha/suresh carried the lahiru donor phone
    +94712534323). The bot reads this for SMS/OTP. Builders must set apn.phone to the target too."""
    ids = [p for p, m in by.items() if m.get("phone")]
    if not ids:
        return []
    cur.execute("""SELECT DISTINCT ON (pnr_id) pnr_id,bounds FROM eds_pnr_output
                   WHERE pnr_id=ANY(%s) ORDER BY pnr_id,received_at DESC""", (ids,))
    bad = []
    for pid, b in cur.fetchall():
        try:
            bb = json.loads(b) if isinstance(b, str) else b
            ph = bb[0]["authenticationContactDetails"]["passengers"][0]["contacts"]["apn"].get("phone")
            if ph != by[pid]["phone"]:
                bad.append(pid)
        except Exception:
            pass
    return sorted(bad)


def date_windows(cur, rows, flight=None, claim_days=None):
    """DB-side date-window areas. Returns ({area: offenders}, bookdate).

    *** THE DIRECTIONAL CHECKS ARE NOT UNIVERSAL — they are DOMAIN-SPECIFIC. ***
      flight="past"    the flight must already have flown  -> FD, SOC, baggage-claim,
                       ancillary POST-travel cases (you claim on a flight that flew)
      flight="future"  the flight must not have flown yet  -> SEAT CHANGE, BOOKING CHANGE,
                       NAME CORRECTION, ancillary PRE-travel (you act before you travel)
      flight=None      skip the directional check          -> MIXED sets (bag / anc carry both)
    A row may override per-PNR with r["flight_expect"] = "past"|"future".
    claim_days: filing limit (FD/APPR = 365). None -> skip; it is meaningless for seat change.

    ALWAYS-SAFE areas (run regardless): eds promisedWindow — pure internal consistency between
    the booking's flight date and the eds window, independent of direction.

    PENDING rows are exempt from the directional check (their flight is imminent by definition)."""
    import datetime as _d
    ids = [m["pnr_id"] for m in rows]; by = {m["pnr_id"]: m for m in rows}
    cur.execute("""SELECT pnr_id, min(departure_datetime_local) FROM flight_segment
                   WHERE pnr_id=ANY(%s) AND NOT is_removed GROUP BY pnr_id""", (ids,))
    bookdate = {p: (d.date() if d else None) for p, d in cur.fetchall()}
    cur.execute("""SELECT DISTINCT ON (pnr_id) pnr_id,bounds FROM eds_pnr_output
                   WHERE pnr_id=ANY(%s) ORDER BY pnr_id,received_at DESC""", (ids,))
    pws = {}
    for pid, b in cur.fetchall():
        try:
            bb = json.loads(b) if isinstance(b, str) else b
            v = bb[0].get("promisedWindowStart")
            if v: pws[pid] = _d.date.fromisoformat(v[:10])
        except Exception: pass
    # UTC, NOT date.today(): every timestamp we compare against (flight_segment.departure_datetime[_local],
    # eds promisedWindowStart) is UTC, while date.today() is the machine's LOCAL date. On a box ahead of
    # UTC (e.g. +05:30) local-today has already rolled over, so a flight departing later TODAY IN UTC was
    # reported "flight in past" while it is still hours in the future. Real hit: BC VOL_TC036, a deliberate
    # departs-in-30-minutes case, flagged 23 minutes BEFORE its own departure.
    today = _d.datetime.now(_d.timezone.utc).date()
    def pending(p):
        m = by[p]; return m.get("status") == "PENDING" or "-PE-" in (m.get("syscode") or "")
    def _expect(p):
        return by[p].get("flight_expect") or flight        # per-row override, else domain default
    def dir_bad(p):
        d = bookdate.get(p)
        if not d or pending(p): return False               # PENDING is imminent by definition
        e = _expect(p)
        if e == "past":   return d > today
        if e == "future": return d < today
        return False                                       # no expectation declared -> skip
    def stale(p):
        if not claim_days: return False
        if by[p].get("claim_exempt"): return False         # outside-limitation-period cases fly OLD by design
        d = bookdate.get(p); return bool(d) and (today - d).days > claim_days
    def pwsbad(p):
        f, w = bookdate.get(p), pws.get(p)
        if not f or not w: return False
        return not (PROMISED_WINDOW_MIN <= (f - w).days <= PROMISED_WINDOW_MAX)
    res = {"eds promisedWindow": [p for p in ids if pwsbad(p)]}
    if flight or any(m.get("flight_expect") for m in rows):
        label = {"past": "flight in past", "future": "flight upcoming"}.get(flight, "flight window")
        res[label] = [p for p in ids if dir_bad(p)]
    if claim_days:
        res[f"claim win <={claim_days}d"] = [p for p in ids if stale(p)]
    return res, bookdate


def collect(cur, ids, rows=None, flight=None, claim_days=None):
    """Run every shared check while the cursor is open. Returns a dict for print_check().
    Pass `rows` to also get the date-window areas. `flight`/`claim_days` are DOMAIN-SPECIFIC —
    see date_windows(). Leave them None on mixed sets; the always-safe areas still run."""
    paxn = _paxcount(cur, ids)
    res = {
        "ticket linkage":  ticket_linkage(cur, ids),
        "eds auth == pax": eds_auth_pax(cur, ids, paxn),
    }
    if rows:
        by = {m["pnr_id"]: m for m in rows}
        res["eds contact phone"] = eds_contact_phone(cur, by)
    if rows:
        win, bookdate = date_windows(cur, rows, flight=flight, claim_days=claim_days)
        res.update(win)
        res["_bookdate"] = bookdate      # for a booking==dds check where the script has DDS
    return res


def print_check(ids, res):
    """Print one line per shared check. Returns True if the audit should FAIL."""
    fail = False
    for label, off in res.items():
        if label.startswith("_"): continue
        print(f"  {label:18} {len(ids)-len(off)}/{len(ids)}"
              + ("" if not off else f"  BAD {len(off)}: {off[:8]}"))
        if off:
            fail = True
    return fail


# ============================================================================
# FULL CANONICAL SUITE (2026-07-13 consolidation) — every generic check any
# data-creation pipeline must pass, in ONE place. See scripts/CHECKPOINTS.md
# for the creation-time rules behind each area. Domain scripts keep their
# domain-specific areas and call collect_full()/print_full() for the rest.
# The original collect()/print_check() API above is unchanged (7 scripts wired).
#
# DATE WINDOWS (added 2026-07-14) — the booking's flight date must sit in the
# window its verdict implies, and booking / eds / DDS must AGREE on that date:
#   flight in past     non-PENDING verdicts need a flown/cancelled flight
#   claim win <=365d   APPR filing limit
#   eds promisedWindow eds promisedWindowStart sits 12-16d before the flight (tolerant:
#                      the exact delta varies by leg/timezone; catches a STALE pws after a re-date)
#   booking==dds date  DDS itinerary date == flight_segment date  (in dds_checks)
#   PENDING flight<=72h  (existing)
# Why: a PENDING case's DDS itinerary was re-dated into the ±72h window while the
# BOOKING and eds kept the original flight date — three sources, three answers, and
# nothing caught it.
# ============================================================================
import ssl as _ssl, os as _os, datetime as _dt, urllib.request as _ur

ENVS = {
 "int": dict(host="ac-cct-trip-tracer-rds-proxy-int-cac1.proxy-czy2ye8u22qy.ca-central-1.rds.amazonaws.com",
             secret="/int-cac1/ac-cct-trip-tracer-rds-cluster-int-cac1/db-credentials",
             dds="https://rule-engine-platform-service.ac-cct-int.cloud.aircanada.com/rule-engine/dds/output/"),
 "crt": dict(host="ac-cct-trip-tracer-rds-cluster-crt-cac1.cluster-cxqe2wacy866.ca-central-1.rds.amazonaws.com",
             secret="/crt-cac1/ac-cct-trip-tracer-rds-cluster-crt-cac1/db-credentials",
             dds="https://rule-engine-platform-service-be.ac-cct-crt.cloud.aircanada.com/rule-engine/dds/output/"),
 "bat": dict(host="ac-cct-trip-tracer-rds-proxy-bat-cac1.proxy-cnc6sqy2ooev.ca-central-1.rds.amazonaws.com",
             secret="/bat-cac1/ac-cct-trip-tracer-rds-cluster-bat-cac1/db-credentials",
             dds="https://rule-engine-platform-service.ac-cct-bat.cloud.aircanada.com/rule-engine/dds/output/"),
}
# Read from the environment (same name the framework resolves): never committed in source.
API_KEY = _os.environ.get("DDS_API_KEY", "")
# The DDS /dds/output endpoint is a PRIVATE API Gateway that can 403 the whole environment
# (resource-policy pinned to one VPC endpoint — see the fd-crt memory). The endpoint merely serves
# the pinned response.json from S3, so when it's unreachable we read that same object directly:
# the winning execution_traces pin's key == the index row's `s3_key` (written by finalize).
S3_BUCKETS = {"int": "ac-cct-rule-engine-store-int", "bat": "cct-ask-ac-bat-logs", "crt": "cct-ask-ac-crt-logs"}
_s3client = None
_dds_endpoint_down = False           # once the endpoint fails, skip it for the rest of the run
_dds_src = {"endpoint": 0, "s3": 0}
def _s3get(env, key):
    global _s3client
    if _s3client is None:
        import boto3; _s3client = boto3.Session(region_name="ca-central-1").client("s3")
    return json.loads(_s3client.get_object(Bucket=S3_BUCKETS[env], Key=key)["Body"].read())
def dds_fetch(pnr_id, row, env, ctx=None):
    """DDS response JSON for one pnr. Try the HTTP endpoint; on ANY failure fall back to the pinned
    S3 response.json (row['s3_key']) — the exact bytes the endpoint serves. Once the endpoint is
    seen down, later calls go straight to S3 (no repeated timeouts). Raises only if both fail."""
    global _dds_endpoint_down
    key = (row or {}).get("s3_key")
    if _dds_endpoint_down and key:
        _dds_src["s3"] += 1; return _s3get(env, key)
    if ctx is None:
        ctx = _ssl.create_default_context(); ctx.check_hostname = False; ctx.verify_mode = _ssl.CERT_NONE
    try:
        req = _ur.Request(ENVS[env]["dds"] + pnr_id, headers={"x-api-key": API_KEY})
        d = json.load(_ur.urlopen(req, timeout=25, context=ctx)); _dds_src["endpoint"] += 1; return d
    except Exception:
        if not key: raise
        if not _dds_endpoint_down:
            _dds_endpoint_down = True
            print(f"  [DDS] endpoint unreachable — falling back to pinned S3 responses ({S3_BUCKETS[env]})")
        _dds_src["s3"] += 1; return _s3get(env, key)


# ---------------------------------------------------------------------------
# SHARED GATEWAY-DOWN FALLBACK (2026-07-17)
# The rule-engine API Gateway (one host serves BOTH /eligibility-service/execute-with-mapping
# AND /rule-engine/dds/output) has a resource policy pinned to one VPC endpoint, so it can 403 the
# WHOLE environment ("User: anonymous is not authorized ... execute-api:Invoke") depending on how a
# request egresses (WARP routing). When that happens the LIVE eligibility/DDS areas can't run — but
# nothing is wrong with the seeded data, so a checkpoint script must DEGRADE GRACEFULLY (report the
# live area as SKIPPED, keep the booking-side verdict) instead of dumping N×403 and failing.
#
#   DDS domains (fd / anc / bag)      -> dds_fetch() already falls back to the pinned S3 response.json.
#   Stateless-eligibility (sc/nc/bc)  -> nothing to pin (verdict is computed from the POSTed body);
#                                        use gateway_down() to SKIP, and bc has bc_offline_verify.py
#                                        which reproduces the VBC rules from the DB (offline).
# Usage in a checkpoint script's live-endpoint section:
#     if C.gateway_down():
#         print(C.skip_area("eligibility outcome", len(rows)))   # SKIP, do NOT set ok=False
#     else:
#         ... run the live loop ...
_gw_state = {}
def gateway_down(env="crt"):
    """True iff the rule-engine gateway is 403-locked / unreachable env-wide. Probed once per env
    per run (cached). A normal 400/404 from the probe path means the gateway is UP (returns False)."""
    if env in _gw_state:
        return _gw_state[env]
    host = ENVS[env]["dds"].split("/rule-engine/")[0]
    ctx = _ssl.create_default_context(); ctx.check_hostname = False; ctx.verify_mode = _ssl.CERT_NONE
    try:
        req = _ur.Request(host + "/rule-engine/dds/output/__gw_probe__", headers={"x-api-key": API_KEY})
        _ur.urlopen(req, timeout=12, context=ctx); _gw_state[env] = False
    except _ur.HTTPError as e:
        body = (e.read()[:200] or b"").decode("utf-8", "ignore")
        # the VPC-endpoint lockout answers 403 "...execute-api:Invoke"; any other code = gateway reachable
        _gw_state[env] = (e.code == 403 and "execute-api:Invoke" in body)
    except Exception:
        _gw_state[env] = True     # host unreachable
    if _gw_state[env]:
        print(f"  [GATEWAY] rule-engine gateway 403/unreachable ({env}) — live eligibility/DDS areas "
              f"SKIPPED (seeded data unaffected; retry when restored, or run the offline verifier)")
    return _gw_state[env]

def skip_area(label, n):
    """One-line SKIP marker for a live area that couldn't run (gateway down). Never fails the audit."""
    return f"  {label:24} SKIP 0/{n}  (rule-engine gateway unreachable — not a data defect)"


_elig_state = {}


def eligibility_live_ok(env="crt"):
    """True iff the eligibility COMPUTE endpoint (/eligibility-service/execute-with-mapping) actually
    returns a verdict from here. This is SEPARATE from gateway_down(): the DDS read path
    (/rule-engine/dds/output) is served by the ALB and works, but the eligibility compute is served
    only via the API Gateway, whose resource policy 403s depending on WARP egress — and the ALB
    answers the eligibility path with a bare health "ok". So a working DDS read does NOT imply a
    working eligibility compute; probe it independently. Cached per env.

    When this returns False, the sc/nc/bc checkpoints validate eligibility with the offline
    rule-replica against the live DB data instead — a real verdict per case, not a skip."""
    if env in _elig_state:
        return _elig_state[env]
    host = ENVS[env]["dds"].split("/rule-engine/")[0]
    url = host + "/eligibility-service/execute-with-mapping"
    ctx = _ssl.create_default_context(); ctx.check_hostname = False; ctx.verify_mode = _ssl.CERT_NONE
    ok = False
    try:
        req = _ur.Request(url, data=b"{}", method="POST",
                          headers={"Content-Type": "application/json", "x-api-key": API_KEY})
        body = _ur.urlopen(req, timeout=12, context=ctx).read(64)
        # a real compute returns JSON with data/boundEligibility; the ALB health handler returns "ok"
        ok = body.strip() not in (b"ok", b"") and body.lstrip()[:1] in (b"{", b"[")
    except Exception:
        ok = False
    _elig_state[env] = ok
    if not ok:
        print(f"  [ELIGIBILITY] compute endpoint not reachable from here ({env}: ALB health-only / "
              f"API-GW 403) — eligibility validated via the offline rule-replica against live DB data")
    return ok


def run_offline_eligibility(script, index_path, env_extra=None):
    """Shell out to a domain's offline rule-replica verifier and return (passed, tail_lines).

    Used by the eligibility checkpoints when the live compute endpoint is unreachable, so the
    eligibility area still yields a real PASS/FAIL from the seeded DB data rather than a SKIP."""
    import os as _os
    import subprocess as _sp

    here = _os.path.dirname(_os.path.abspath(__file__))
    e = dict(_os.environ)
    if env_extra:
        e.update(env_extra)
    args = ["python3", _os.path.join(here, script)]
    if index_path:
        args.append(index_path)
    p = _sp.run(args, capture_output=True, text=True, env=e, cwd=here)
    out = (p.stdout + p.stderr).strip().splitlines()
    import re as _re
    # pass when an explicit PASS marker is present, or every "N/M match" line has N == M, and no FAIL
    ratios = [(int(m.group(1)), int(m.group(2)))
              for ln in out for m in [_re.search(r"(\d+)/(\d+)\s+(?:VOL cases |cases )?match", ln)] if m]
    all_match = bool(ratios) and all(n == m for n, m in ratios)
    has_pass = any("PASS" in ln for ln in out)
    has_fail = any("FAIL" in ln or "❌" in ln for ln in out)
    passed = (has_pass or all_match) and not has_fail and p.returncode == 0
    return passed, out[-4:]

PENDING_WINDOW_DAYS = 3      # a PENDING verdict only holds while the disruption is still assessed
CLAIM_WINDOW_DAYS  = 365     # APPR filing limit — a flight older than this can't be claimed
# eds promisedWindowStart sits ~14d before the flight, but the exact delta depends on the
# segment/timezone shape (measured: 13d22h single-leg, 13d14h two-leg — both pipeline-produced).
# So this is a TOLERANT band, not an exact rule: it still catches a pws left stale when the flight
# date is moved (the real defect: flight -> 2026-07-14 while pws stayed 2026-06-01 = 43d).
PROMISED_WINDOW_MIN = 12
PROMISED_WINDOW_MAX = 16


def connect(env):
    """trip-tracer connection for an ENVS key (secret via boto3 where configured)."""
    import psycopg2
    cfg = ENVS[env]
    if cfg.get("secret"):
        import boto3
        sec = json.loads(boto3.Session(region_name="ca-central-1").client("secretsmanager")
                         .get_secret_value(SecretId=cfg["secret"])["SecretString"])
        u, p = sec["username"], sec["password"]
    else:
        u, p = cfg["user"], cfg["password"]
    return psycopg2.connect(host=cfg["host"], port=5432, dbname="trip-tracer",
                            user=u, password=p, sslmode="require", connect_timeout=20)


def collect_full(cur, rows):
    """All generic BOOKING-side areas in one pass. rows = index dicts (need pnr_id;
    optional email/group/npax/uniq_names). Returns {area: offender_list} ordered."""
    ids = [m["pnr_id"] for m in rows]; by = {m["pnr_id"]: m for m in rows}
    def col(q):
        cur.execute(q, (ids,)); return dict(cur.fetchall())
    trip  = col("SELECT pnr_id,status FROM trip WHERE pnr_id=ANY(%s)")
    td    = col("SELECT pnr_id,count(*) FROM trip_details WHERE pnr_id=ANY(%s) GROUP BY pnr_id")
    cur.execute("""SELECT pnr_id,count(*),count(*) FILTER (WHERE date_of_birth IS NULL)
                   FROM passenger WHERE pnr_id=ANY(%s) AND NOT is_removed GROUP BY pnr_id""", (ids,))
    pax = {r[0]: (r[1], r[2]) for r in cur.fetchall()}
    tkt = col("SELECT pnr_id,count(*) FROM ticket WHERE pnr_id=ANY(%s) GROUP BY pnr_id")
    link_off = set(ticket_linkage(cur, ids))
    cur.execute("""SELECT DISTINCT ON (pnr_id) pnr_id,bounds,booking_context FROM eds_pnr_output
                   WHERE pnr_id=ANY(%s) ORDER BY pnr_id,received_at DESC""", (ids,))
    _edsrows = cur.fetchall()
    eds, mail, grp, authn, fone = {}, {}, {}, {}, {}
    for pid, b, bc in _edsrows:
        eds[pid] = 1
        try:
            bb = json.loads(b) if isinstance(b, str) else b
            aps = bb[0]["authenticationContactDetails"]["passengers"]
            mail[pid] = aps[0]["contacts"]["apn"].get("email"); authn[pid] = len(aps)
            fone[pid] = aps[0]["contacts"]["apn"].get("phone")
        except Exception: mail[pid] = None
        try:
            o = json.loads(bc) if isinstance(bc, str) else (bc or {}); grp[pid] = o.get("bookingSubtype")
        except Exception: grp[pid] = None
    # ---- DATE WINDOWS (added 2026-07-14) ------------------------------------
    # The booking's flight date must sit in the window the verdict implies, and the three
    # sources (booking / eds / DDS) must agree on it. Caught: PENDING cases whose DDS itinerary
    # was re-dated into the ±72h window while the BOOKING + eds kept the original flight date.
    cur.execute("""SELECT pnr_id, min(departure_datetime_local) FROM flight_segment
                   WHERE pnr_id=ANY(%s) AND NOT is_removed GROUP BY pnr_id""", (ids,))
    bookdate = {p: (d.date() if d else None) for p, d in cur.fetchall()}
    # NOTE: eds bounds do NOT embed flight dates — promisedSegments/actualSegments are lists of
    # segment IDs that resolve to flight_segment. The only date eds carries is promisedWindowStart,
    # which must equal flight_date - 14d. (An earlier version of this check tried to read a
    # departureDatetime out of the segment list and silently passed on every set.)
    edspws = {}
    for pid, b, bc in _edsrows:
        try:
            bb = json.loads(b) if isinstance(b, str) else b
            pws = bb[0].get("promisedWindowStart")
            if pws: edspws[pid] = _dt.date.fromisoformat(pws[:10])
        except Exception: pass
    _today = _dt.date.today()
    def _is_pending(p):
        m = by[p]; return m.get("status") == "PENDING" or "-PE-" in (m.get("syscode") or "")
    def _flight_future(p):
        d = bookdate.get(p)
        if not d or _is_pending(p):            # PENDING is imminent by definition
            return False
        # Honour the documented per-row override (date_windows() already did; collect_full did
        # not, so the universal runner ignored it). A row with flight_expect="future" is a
        # deliberate upcoming booking — e.g. FD_TC_063, which carries NO DDS/verdict, so there
        # is no claim and therefore no "must have flown" requirement.
        if by[p].get("flight_expect") == "future":
            return False
        return d > _today
    def _flight_stale(p):
        if by[p].get("claim_exempt"): return False        # outside-limitation cases fly OLD by design
        d = bookdate.get(p)
        return bool(d) and (_today - d).days > CLAIM_WINDOW_DAYS
    def _pws_bad(p):
        # eds promisedWindowStart must be flight_date - 14d. Offender only when BOTH are known,
        # so a set with no eds rows fails on the eds_pnr_output area, not misleadingly here.
        f, w = bookdate.get(p), edspws.get(p)
        if not f or not w: return False
        return not (PROMISED_WINDOW_MIN <= (f - w).days <= PROMISED_WINDOW_MAX)

    import crt_uniqnames as _U
    _, name_off = _U.name_uniqueness(cur, ids)
    uniq_enforced = any(m.get("uniq_names") for m in rows)
    def off(pred): return [p for p in ids if pred(p)]
    res = {
        "trip ACTIVE":       off(lambda p: trip.get(p) != "ACTIVE"),
        "trip_details":      off(lambda p: td.get(p, 0) == 0),
        "passenger":         off(lambda p: pax.get(p, (0, 0))[0] == 0),
        "DOB set":           off(lambda p: pax.get(p, (0, 1))[1] > 0),
        "ticket":            off(lambda p: tkt.get(p, 0) == 0),
        "ticket == pax":     off(lambda p: tkt.get(p, 0) != pax.get(p, (0, 0))[0]),
        "ticket linkage":    off(lambda p: p in link_off),
        "eds_pnr_output":    off(lambda p: p not in eds),
        "eds contact email": off(lambda p: by[p].get("email") and mail.get(p) != by[p]["email"]),
        "eds contact phone": off(lambda p: by[p].get("phone") and fone.get(p) != by[p]["phone"]),
        "eds auth == pax":   off(lambda p: p in authn and authn[p] != pax.get(p, (0, 0))[0]),
        "GROUP context":     off(lambda p: by[p].get("group") and grp.get(p) != "GROUP"),
        ("name uniqueness" if uniq_enforced else "name uniq (info)"): list(name_off),
        # date windows
        "flight in past":    off(_flight_future),
        "claim win <=365d":  off(_flight_stale),
        "eds promisedWindow": off(_pws_bad),
    }
    res["_pax"] = pax                     # for dds_checks(); stripped by print_full
    res["_uniq_enforced"] = uniq_enforced
    res["_bookdate"] = bookdate           # for dds_checks() booking-vs-DDS date agreement
    return res


def dds_checks(rows, env, pax=None, dds_field="syscode", bookdate=None):
    """Generic ENDPOINT-side areas for pinned rows: systemCode match, ELIGIBLE amount match,
    NE/ND non-empty reason, passenger-count vs DDS pe, PENDING flight within ±72h, and
    booking==DDS flight-date agreement (pass bookdate from collect_full()['_bookdate']).
    Returns list of (label, good, total, bad_samples)."""
    cfg = ENVS[env]
    ctx = _ssl.create_default_context(); ctx.check_hostname = False; ctx.verify_mode = _ssl.CERT_NONE
    today = _dt.date.today()
    pinned = [m for m in rows if m.get("pin")]
    dmatch, dbad = 0, []; amtn, amtbad = 0, []; rsnn, rsnbad = 0, []
    pcn, pcbad = 0, []; pend, datebad = 0, []; bdn, bdbad = 0, []
    for m in pinned:
        try:
            d = dds_fetch(m["pnr_id"], m, env, ctx)   # endpoint, with automatic S3-pin fallback
            pe0 = d["compensationEligibility"][0]["passengerEligibility"][0]
            got = pe0["systemCode"]
            if got == m.get(dds_field): dmatch += 1
            else: dbad.append((m["pnr_id"], f"exp {m.get(dds_field)} got {got}"))
            if pe0.get("eligibilityStatus") == "ELIGIBLE" and m.get("amount"):
                amtn += 1; a = (pe0.get("compensationDetails") or {}).get("amount")
                if a != m["amount"]: amtbad.append((m["pnr_id"], f"exp {m['amount']} got {a}"))
            if pe0.get("eligibilityStatus") in ("NOT_ELIGIBLE", "NO_DETERMINATION"):
                rsnn += 1
                if not (pe0.get("reason") or "").strip(): rsnbad.append((m["pnr_id"], f"{got} empty reason"))
            pcn += 1
            dpe = len(d["compensationEligibility"][0]["passengerEligibility"])
            tp = (pax or {}).get(m["pnr_id"], (dpe, 0))[0]
            exp = m.get("npax")
            # GROUP is checked BEFORE npax: a group booking's DDS assesses the HOLDER only
            # (pe>=1) while the trip legitimately carries every traveller. A group row that also
            # (correctly) declares npax must NOT be forced to npax passengerEligibility entries —
            # that made the 12-pax group bookings fail with "exp12 trip12/dds1" even though the
            # data matched the documented rule. Precedence was backwards before 2026-07-14.
            if m.get("group"):
                if dpe < 1 or tp < 1: pcbad.append((m["pnr_id"], f"group trip{tp}/dds{dpe}"))
            elif exp:
                if tp != exp or dpe != exp: pcbad.append((m["pnr_id"], f"exp{exp} trip{tp}/dds{dpe}"))
            elif tp != dpe: pcbad.append((m["pnr_id"], f"trip{tp}!=dds{dpe}"))
            # DDS itinerary flight date — used for the PENDING window AND the booking-agreement check
            _dep = None
            try:
                _dep = d["itineraryDetails"][0]["actualItinerary"]["associatedSegments"][0]["departureDatetime"][:10]
            except Exception: pass
            if m.get("status") == "PENDING" or "-PE-" in (m.get(dds_field) or ""):
                pend += 1
                if not _dep: datebad.append((m["pnr_id"], "no flight date in DDS"))
                else:
                    delta = (_dt.date.fromisoformat(_dep) - today).days
                    if abs(delta) > PENDING_WINDOW_DAYS:
                        datebad.append((m["pnr_id"], f"flight {_dep} Δ{delta}d outside ±{PENDING_WINDOW_DAYS}d"))
            # booking == DDS flight date. A verdict whose itinerary date differs from the booking
            # the bot reads is inconsistent (hit: PENDING DDS re-dated into ±72h, booking left behind).
            if bookdate and _dep:
                bd = bookdate.get(m["pnr_id"])
                if bd:
                    bdn += 1
                    if str(bd) != _dep:
                        bdbad.append((m["pnr_id"], f"booking {bd} != dds {_dep}"))
        except Exception as e: dbad.append((m["pnr_id"], str(e)[:40]))
    return [("DDS endpoint", dmatch, len(pinned), dbad),
            ("DDS amount match", amtn - len(amtbad), amtn, amtbad),
            ("NE/ND reason text", rsnn - len(rsnbad), rsnn, rsnbad),
            ("passenger count", pcn - len(pcbad), pcn, pcbad),
            ("PENDING flight≤72h", pend - len(datebad), pend, datebad),
            ("booking==dds date", bdn - len(bdbad), bdn, bdbad)]


def segments_vs_scenario(cur, rows, scenario_dir):
    """Booking-vs-scenario JSON: trip.pnr, passenger names, per-segment airports/flight/carrier/
    date/bound_rph. PNRs without a scenario file count n/a. Returns (good, total, na, bad)."""
    ids = [m["pnr_id"] for m in rows]
    cur.execute("SELECT pnr_id,pnr FROM trip WHERE pnr_id=ANY(%s)", (ids,))
    trip_pnr = dict(cur.fetchall())
    cur.execute("""SELECT pnr_id,bound_rph,departure_airport,arrival_airport,marketing_flight_number,
                          marketing_carrier_code,departure_datetime_local
                   FROM flight_segment WHERE pnr_id=ANY(%s) AND NOT is_removed""", (ids,))
    segs = {}
    for r in cur.fetchall(): segs.setdefault(r[0], []).append(r[1:])
    cur.execute("SELECT pnr_id,first_name,last_name FROM passenger WHERE pnr_id=ANY(%s) AND NOT is_removed", (ids,))
    names = {}
    for pid, f, l in cur.fetchall(): names.setdefault(pid, []).append((f, l))
    segn, bad = 0, []
    for m in rows:
        p = m["pnr_id"]; sp = _os.path.join(scenario_dir, f"{p}.json")
        if not _os.path.exists(sp): continue
        segn += 1; iss = []
        try:
            scn = json.load(open(sp))
            if trip_pnr.get(p) != scn["identity"]["pnr"]: iss.append("trip.pnr mismatch")
            if sorted(names.get(p, [])) != sorted((x["first_name"], x["last_name"]) for x in scn["passengers"]):
                iss.append("passenger names != scenario")
            db = sorted(segs.get(p, []), key=lambda x: str(x[5])); sc = sorted(scn["segments"], key=lambda x: x["dep_local"])
            if len(db) != len(sc): iss.append(f"segments {len(db)}!={len(sc)}")
            else:
                for (brph, dep, arr, mfn, mcar, ddt), s in zip(db, sc):
                    if dep != s["origin"] or arr != s["destination"]: iss.append("route mismatch")
                    if int(mfn) != int(s["flight_number"]): iss.append(f"flt {mfn}!={s['flight_number']}")
                    if mcar != s["carrier"]: iss.append(f"carrier {mcar}!={s['carrier']}")
                    if ddt and str(ddt)[:10] != s["dep_local"][:10]: iss.append("dep date mismatch")
                    if s.get("bound") is not None and brph is not None and int(brph) != int(s["bound"]):
                        iss.append(f"bound_rph {brph}!={s['bound']}")
        except Exception as e: iss.append(str(e)[:40])
        if iss: bad.append((p, iss[:3]))
    return segn - len(bad), segn, len(ids) - segn, bad


def print_full(rows, booking_res, dds_res=None, seg_res=None):
    """Print every area; returns True if the audit should FAIL."""
    ids = [m["pnr_id"] for m in rows]; fail = False
    uniq_enforced = booking_res.get("_uniq_enforced", False)
    for label, off in booking_res.items():
        if label.startswith("_"): continue
        n = len(ids) - len(off)
        print(f"  {label:18} {n}/{len(ids)}" + ("" if not off else f"  MISS {len(off)}: {off[:8]}"))
        if off and not (label == "name uniq (info)" and not uniq_enforced): fail = True
    for label, good, total, bad in (dds_res or []):
        print(f"  {label:18} {good}/{total}" + ("" if not bad else f"  BAD {len(bad)}: {bad[:6]}"))
        if bad: fail = True
    if seg_res:
        good, total, na, bad = seg_res
        print(f"  segments==scenario {good}/{total}" + (f"  (n/a {na})" if na else "")
              + ("" if not bad else f"  BAD {len(bad)}: {bad[:6]}"))
        if bad: fail = True
    return fail
