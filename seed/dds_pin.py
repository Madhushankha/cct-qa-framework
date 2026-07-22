"""DDS determination pin — the second half of the INT/CRT seed.

The chatbot fetches a PNR's disruption determination via
`GET <by_pnr_url>/{pnrId}` (header x-api-key) -> the rule-engine looks up the newest
`execution_traces` row for that pnrId -> downloads its `response_s3_key` object from S3 and returns it.
DDS is NOT auto-computed in non-prod, so for a freshly-seeded PNR we must create both halves:

  1. S3 PutObject a `response.json` (canonical bot shape) under `<store_bucket>/<trace_prefix>/<date>/<uuid>/`
  2. INSERT an `execution_traces` row (entity_id=pnrId -> that s3 key) with a FUTURE `processed_at` so it
     always wins the engine's `ORDER BY processed_at DESC` (survives the 14-day ND retry).

The response.json is produced by rewriting a bundled, known-good template determination to the seeded
PNR's identity (locator, date, flight, route, passenger). Templates are descriptor-referenced so a new
verdict family is added by dropping in another template file — no code change.

Live deps (boto3, psycopg2, requests/urllib) are imported lazily; the pure rewrite functions are
offline-testable.
"""
from __future__ import annotations

import json
import re
import uuid
from pathlib import Path

_PT_RE = re.compile(r"-PT-\d+")


def load_template(path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


# The chatbot's assess_eligibility reads a RICHER shape than the raw rule-engine emits: the eligible
# regime needs an amount-encoded systemCode (FD-APPR-EL-400/700/1000), the matching delayBand, the
# delay fields, a disruptionReason + a customer-friendly reason, and compensationDetails.{amount,
# currency,delayBand,expiryDate}; every non-applicable regime must read NOT_ELIGIBLE + FD-<reg>-NA-01
# with a zero compensationDetails. A raw pin (real engine shape) is read but NOT usable -> the bot
# escalates to manual. This canonicalizer (ported from the proven fix_dds_shape recipe) fixes that.
APPR_FAMILY = {
    "APPR_CAD_400": {"amount": 400, "currency": "CAD", "system_code": "FD-APPR-EL-400",
                     "delay_band": "DELAY_3_TO_LT_6_HOURS", "delay_minutes": 240,
                     "reason": "arrival delay 3 to less than 6 hours, within carrier control"},
    "APPR_CAD_700": {"amount": 700, "currency": "CAD", "system_code": "FD-APPR-EL-700",
                     "delay_band": "DELAY_6_TO_LT_9_HOURS", "delay_minutes": 400,
                     "reason": "arrival delay 6 to less than 9 hours, within carrier control"},
    "APPR_CAD_1000": {"amount": 1000, "currency": "CAD", "system_code": "FD-APPR-EL-1000",
                      "delay_band": "DELAY_9_HOURS_OR_MORE", "delay_minutes": 600,
                      "reason": "arrival delay 9 hours or more, within carrier control"},
}
_NA_SYS = {"EU": "FD-EU-NA-01", "EU261": "FD-EU-NA-01", "UK": "FD-UK-NA-01",
           "ASL": "FD-ASL-NA-01"}
_FRIENDLY = ("Your flight arrived more than 3 hours late due to a reason within "
             "Air Canada's control.")


def canonicalize_appr(response: dict, family: str, *, expiry_date: str,
                      delay_code: str = "64") -> dict:
    """Rewrite a determination in place to the bot's canonical eligible-APPR shape (per `family`),
    marking every other regime NOT_ELIGIBLE / not-applicable. Returns the response."""
    spec = APPR_FAMILY.get(family)
    if not spec:
        return response  # unknown family -> leave the determination as-is
    for c in response.get("compensationEligibility", []):
        reg = (c.get("regime") or "").upper()
        if reg == "APPR":
            c["delayMinutes"] = spec["delay_minutes"]
            c["delayType"] = "CONTROLLABLE"
            c["delayCode"] = delay_code
            c["disruptionReason"] = "MECHANICAL"
            c["customerFriendlyDisruptionReason"] = _FRIENDLY
            for pe in c.get("passengerEligibility", []):
                pe["passengerType"] = pe.get("passengerType") or "ADT"
                pe["eligibilityStatus"] = "ELIGIBLE"
                pe["systemCode"] = spec["system_code"]
                pe["reason"] = spec["reason"]
                pe["compensationDetails"] = {"amount": spec["amount"], "currency": spec["currency"],
                                             "delayBand": spec["delay_band"], "expiryDate": expiry_date}
                pe.pop("failureReasons", None)
        else:
            c["delayMinutes"] = 0
            c["delayType"] = ""
            c["delayCode"] = ""
            for pe in c.get("passengerEligibility", []):
                pe["passengerType"] = pe.get("passengerType") or "ADT"
                pe["eligibilityStatus"] = "NOT_ELIGIBLE"
                pe["systemCode"] = _NA_SYS.get(reg, f"FD-{reg}-NA-01")
                pe["reason"] = "Regime not applicable to this itinerary"
                pe["compensationDetails"] = {"amount": 0, "currency": spec["currency"],
                                             "delayBand": "NOT_APPLICABLE"}
                pe.pop("failureReasons", None)
    return response


# CLASS (from systemCode FD-<REGIME>-<CLASS>-<n>) -> the bot's eligibilityStatus enum.
_CLASS_STATUS = {"EL": "ELIGIBLE", "NE": "NOT_ELIGIBLE", "ND": "NO_DETERMINATION",
                 "PE": "PENDING", "DB": "ELIGIBLE"}
# REGIME token in the systemCode -> the compensationEligibility.regime it targets. MIXED/DUP are
# APPR-driven in the FD catalog, so their determination lands on the APPR regime entry.
_REGIME_TARGET = {"APPR": "APPR", "EU": "EU", "UK": "EU", "ASL": "ASL", "MIXED": "APPR", "DUP": "APPR"}
# compensation currency -> the compensationEligibility.regime that currency's leg belongs to. Used to
# pick the ELIGIBLE leg of a MIXED/DUP itinerary: its systemCode regime defaults to APPR, but when the
# eligible leg is the EU/UK (GBP/EUR) or ASL (ILS) one, the determination must land there, not on APPR.
_CURRENCY_REGIME = {"CAD": "APPR", "EUR": "EU", "GBP": "EU", "ILS": "ASL"}
_CLASS_REASON = {
    "NE": "Not eligible for compensation for this disruption.",
    "ND": "A determination could not be made for this disruption.",
    "PE": "Your claim is pending — the disruption is within the assessment window.",
}


def _load_reason_codes() -> dict:
    """systemCode -> the rule-engine's specific determination reason text (e.g. FD-ASL-NE-01 ->
    'Employee booking AC'). Mined from the reference DDS-RULE `*-reason.md` rules; the bot renders its
    customer-friendly not-eligible message from THIS reason, so a generic reason makes it escalate."""
    try:
        return json.loads((Path(__file__).resolve().parent.parent / "data" / "fd_reason_codes.json")
                          .read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 — fall back to the class-generic reason if the map is absent
        return {}


_REASON_CODES = _load_reason_codes()


def reason_for(system_code: str, cls: str) -> str:
    """The determination reason to pin: the systemCode-specific text (FD-<reg>-NE-<n> -> its rule
    reason) when known, else the class-generic fallback."""
    return _REASON_CODES.get((system_code or "").upper()) or _CLASS_REASON.get(cls, "Not eligible.")


def ne_disruption(reason: str) -> tuple:
    """(delayType, disruptionReason, customerFriendlyDisruptionReason) for a NOT_ELIGIBLE case, derived
    from its rule reason. The controllability MUST match the reason or the determination is incoherent
    (a 'not eligible because it was uncontrollable weather' case pinned as CONTROLLABLE makes the
    customer/persona dispute it — FD_TC_052). Weather/extraordinary/outside-control and safety cases are
    NOT_CONTROLLABLE; employee/OAL/denied-boarding/threshold cases keep the real controllable delay."""
    r = (reason or "").lower()
    if "safety" in r:
        return ("NOT_CONTROLLABLE", "SAFETY",
                "Your flight was disrupted for reasons required for safety.")
    if "control" in r or "extraordinary" in r or "weather" in r:
        return ("NOT_CONTROLLABLE", "WEATHER",
                "Your flight was disrupted by circumstances outside the carrier's control.")
    return ("CONTROLLABLE", "MECHANICAL", "Your flight was disrupted.")


def _delay_band(delay_minutes: int) -> str:
    if delay_minutes >= 540:
        return "DELAY_9_HOURS_OR_MORE"
    if delay_minutes >= 360:
        return "DELAY_6_TO_LT_9_HOURS"
    return "DELAY_3_TO_LT_6_HOURS"


def parse_system_code(system_code: str) -> tuple[str, str]:
    """`FD-APPR-EL-400` -> ('APPR', 'EL'); tolerant of trailing junk. Defaults ('APPR','EL')."""
    parts = (system_code or "").upper().split("-")
    regime = parts[1] if len(parts) > 1 else "APPR"
    cls = parts[2] if len(parts) > 2 else "EL"
    return regime, cls


def canonicalize_verdict(response: dict, *, system_code: str, amount: float = 0.0,
                         currency: str = "CAD", delay_minutes: int = 240,
                         expiry_date: str, delay_code: str = "64", status: str = "") -> dict:
    """Rewrite a determination in place to the bot's assess_eligibility shape for ANY FD verdict —
    ELIGIBLE / NOT_ELIGIBLE / NO_DETERMINATION / PENDING — driven by the case's `system_code`
    (`FD-<REGIME>-<CLASS>-<n>`). The target regime carries the case's exact systemCode + status;
    every other regime reads NOT_ELIGIBLE / not-applicable. One base template covers all 239 cases:
    the itinerary is set by rewrite_determination, the verdict by this function.

    For eligible cases (EL/DB) the target regime gets compensationDetails{amount,currency,delayBand,
    expiryDate}; NE/ND/PE get a zero compensation + a class-appropriate reason.

    `status`: the case's EXPECTED verdict, when known. It overrides the systemCode class letter —
    essential for MIXED/DUP cases, whose class letter describes only ONE leg (FD-MIXED-NE-01 = the
    APPR leg is not eligible) while the customer is ELIGIBLE via the most-generous OTHER leg. Trusting
    the class letter alone wrongly seeds those as not-eligible (FD_TC_150/152)."""
    regime_tok, cls = parse_system_code(system_code)
    # verdict: an explicit expected status wins over the class letter (see MIXED/DUP note above).
    status = (status or _CLASS_STATUS.get(cls, "NOT_ELIGIBLE")).upper()
    eligible = status == "ELIGIBLE"
    # target regime: the systemCode's regime, EXCEPT an eligible MIXED/DUP case is eligible on the leg
    # matching the compensation currency (GBP/EUR->EU, ILS->ASL, CAD->APPR), not the default APPR leg.
    target = _REGIME_TARGET.get(regime_tok, "APPR")
    if regime_tok in ("MIXED", "DUP") and eligible:
        target = _CURRENCY_REGIME.get((currency or "").upper(), target)
    band = _delay_band(delay_minutes) if eligible else "NOT_APPLICABLE"

    for c in response.get("compensationEligibility", []):
        reg = (c.get("regime") or "").upper()
        is_target = reg == target
        # The target regime carries the REAL disruption context at the regime level whether or not the
        # passenger is eligible — an employee whose flight was genuinely delayed still had a disruption.
        # The backend reads this regime-level context to know there IS something to assess; zeroing it
        # for NE (the old path) made it return manual_required and the bot escalate. This matches the
        # set-5 determination shape the bot renders ("not eligible because <reason>").
        if is_target:
            c["delayMinutes"] = delay_minutes
            c["delayCode"] = delay_code
            c["disruptionType"] = c.get("disruptionType") or "INVOLUNTARY"
            if eligible:
                c["delayType"] = "CONTROLLABLE"
                c["disruptionReason"] = "MECHANICAL"
                c["customerFriendlyDisruptionReason"] = _FRIENDLY
            else:
                # controllability + reason must match the NE cause, else the determination is incoherent
                # ("not eligible" + "within carrier's control" makes the customer dispute — FD_TC_052).
                dtype, dreason, friendly = ne_disruption(reason_for(system_code, cls))
                c["delayType"] = dtype
                c["disruptionReason"] = dreason
                c["customerFriendlyDisruptionReason"] = friendly
        else:
            c["delayMinutes"] = 0
            c["delayType"] = ""
            c["delayCode"] = ""
        for pe in c.get("passengerEligibility", []):
            pe["passengerType"] = pe.get("passengerType") or "ADT"
            pe["failureReasons"] = None  # set-5 carries failureReasons: null on every entry
            if is_target:
                pe["eligibilityStatus"] = status
                pe["systemCode"] = system_code
                if eligible:
                    pe["reason"] = "You're eligible for compensation."
                    pe["compensationDetails"] = {"amount": amount, "currency": currency,
                                                 "delayBand": band, "expiryDate": expiry_date}
                else:
                    # case-specific determination reason (e.g. 'Employee booking AC') keyed by the
                    # systemCode, so the bot renders "not eligible because X" instead of escalating.
                    # NE entries carry NO compensationDetails (matches set-5).
                    pe["reason"] = reason_for(system_code, cls)
                    pe.pop("compensationDetails", None)
            else:
                pe["eligibilityStatus"] = "NOT_ELIGIBLE"
                pe["systemCode"] = _NA_SYS.get(reg, f"FD-{reg}-NA-01")
                pe["reason"] = "Regime not applicable to this itinerary"
                pe["compensationDetails"] = {"amount": 0, "currency": currency,
                                             "delayBand": "NOT_APPLICABLE"}
    return response


def rewrite_determination(template: dict, *, pnr_id: str, locator: str, carrier: str,
                          flight_number, origin: str, destination: str,
                          passenger_id: str | None = None, timestamp: str | None = None) -> dict:
    """Rewrite a template determination to the seeded PNR's identity.

    - the template's placeholder pnrId (`<TLOC>-<TDATE>`) and bare locator are replaced with the
      seeded `pnr_id` / `locator`, which carries every derived `-PT-*`/`-ST-*` id with them;
    - every `-PT-N` reference collapses to the seeded passenger (single-pax fixtures) so the eligible
      verdict lands on the passenger the bot authenticates;
    - each `mslFlight` / itinerary segment's carrier/flight/airports are set to the seeded flight so the
      determination matches the flight the bot shows from the PNR;
    - eventMetadata.timestamp is refreshed.
    Returns a new dict (the input template is not mutated)."""
    t_pnr = template["pnrIdentifier"]["pnrId"]   # e.g. ZZTMPL-2000-01-01
    t_loc = template["pnrIdentifier"]["pnr"]      # e.g. ZZTMPL
    raw = json.dumps(template)
    raw = raw.replace(t_pnr, pnr_id).replace(t_loc, locator)
    # collapse all passenger indices onto the seeded passenger (PT-1 for single-pax)
    pid_suffix = passenger_id.rsplit("-PT-", 1)[-1] if (passenger_id and "-PT-" in passenger_id) else "1"
    raw = _PT_RE.sub(f"-PT-{pid_suffix}", raw)
    d = json.loads(raw)

    # Recursively rewrite EVERY flight/route reference in the whole determination (mslFlight,
    # itineraryDetails.promised/actualItinerary, associatedSegments, ...) to the seeded flight, so the
    # determination is fully consistent with the flight the bot shows from the PNR — no template
    # origin/destination (e.g. YUL/CUN) leaks through.
    seg_id = f"{pnr_id}-ST-1"
    _set_flight_deep(d, carrier, str(flight_number), origin, destination, seg_id)

    if timestamp:
        d.setdefault("eventMetadata", {})["timestamp"] = timestamp
    return d


# flight/route-identifying keys -> which seeded value they take
def _set_flight_deep(node, carrier, flight_number, origin, destination, seg_id) -> None:
    if isinstance(node, dict):
        for k, v in list(node.items()):
            if k == "carrierCode":
                node[k] = carrier
            elif k == "flightNumber":
                node[k] = flight_number
            elif k in ("departureAirport", "origin", "boardPoint"):
                node[k] = origin
            elif k in ("arrivalAirport", "destination", "offPoint"):
                node[k] = destination
            elif k == "segmentId":
                node[k] = seg_id
            else:
                _set_flight_deep(v, carrier, flight_number, origin, destination, seg_id)
    elif isinstance(node, list):
        for item in node:
            _set_flight_deep(item, carrier, flight_number, origin, destination, seg_id)


def s3_trace_key(trace_prefix: str, date: str, trace_uuid: str | None = None) -> str:
    """`<trace_prefix>/<date>/<uuid>/response.json` — the key layout the rule-engine trace lookup expects."""
    return f"{trace_prefix}/{date}/{trace_uuid or uuid.uuid4()}/response.json"


# ── live side ────────────────────────────────────────────────────────────────
def _dds_cfg(env) -> dict:
    dds = (env.seed_targets or {}).get("dds")
    if not dds:
        raise ValueError(f"env '{env.id}' seed_targets has no 'dds' block")
    return dds


def put_response(env, response: dict, *, date: str, region: str = "ca-central-1") -> str:
    """PutObject the response.json under a fresh trace key; return the S3 key."""
    import boto3  # lazy

    dds = _dds_cfg(env)
    profile = (env.aws or {}).get("profile")
    s3 = boto3.Session(profile_name=profile).client("s3", region_name=region)
    key = s3_trace_key(dds["trace_prefix"], date)
    s3.put_object(Bucket=dds["store_bucket"], Key=key,
                  Body=json.dumps(response, separators=(",", ":")).encode("utf-8"),
                  ContentType="application/json")
    return key


def pin_trace(env, pnr_id: str, s3_key: str, *, correlation_id: str = "cctqa-fd",
              processed_at: str = "2027-12-31 00:00:00+00", region: str = "ca-central-1") -> str:
    """INSERT the execution_traces row via direct psycopg2 to the rule-engine cluster (using
    rule_engine_secret). Deletes any prior cctqa pin for this pnr first (idempotent re-seed).
    Returns 'inserted'. Raises on failure (caller may fall back to ECS-exec)."""
    from seed.source import db_connect, read_secret  # lazy

    dds = _dds_cfg(env)
    sec = read_secret(env, (env.seed_targets or {}).get("rule_engine_secret"))
    # Try every credential pair the secret carries: the rule-engine cluster rejects `username`
    # (dbdevuser) and accepts `adminuser` (dbadmin), the reverse of trip-tracer's proxy.
    conn = db_connect(dds["rule_engine_host"], dds.get("rule_engine_db", "postgres"), sec,
                      port=int(sec.get("port", 5432)), timeout=15)
    conn.autocommit = True
    cur = conn.cursor()
    cur.execute("delete from execution_traces where entity_id=%s and correlation_id=%s", (pnr_id, correlation_id))
    cur.execute(
        "insert into execution_traces(id,service_type,correlation_id,entity_id,processed_at,request_s3_key,response_s3_key) "
        "values (gen_random_uuid(),'DDS',%s,%s,%s,NULL,%s)",
        (correlation_id, pnr_id, processed_at, s3_key))
    conn.close()
    return "inserted"


def pin_trace_ecs(env, pnr_id: str, s3_key: str, *, correlation_id: str = "cctqa-fd",
                  processed_at: str = "2027-12-31 00:00:00+00", container: str = "App",
                  region: str = "ca-central-1") -> str:
    """INSERT the execution_traces row via ECS-exec into the rule-engine container — the only in-VPC
    path when the cluster DB is SG-blocked from here. Installs psql if absent, connects with the
    container's own CCT_TRACING_DB_* env creds. Returns 'inserted-ecs'. Raises on failure."""
    import base64  # lazy
    import os
    import subprocess

    import boto3  # lazy

    dds = _dds_cfg(env)
    cluster = dds["ecs_cluster"]
    profile = (env.aws or {}).get("profile")
    ecs = boto3.Session(profile_name=profile).client("ecs", region_name=region)
    tasks = ecs.list_tasks(cluster=cluster, desiredStatus="RUNNING").get("taskArns") or []
    if not tasks:
        raise RuntimeError(f"no RUNNING task in {cluster} for ECS-exec")
    task = tasks[0].split("/")[-1]

    sql = (f"delete from execution_traces where entity_id='{pnr_id}' and correlation_id='{correlation_id}';"
           f"insert into execution_traces(id,service_type,correlation_id,entity_id,processed_at,request_s3_key,response_s3_key) "
           f"values (gen_random_uuid(),'DDS','{correlation_id}','{pnr_id}','{processed_at}',NULL,'{s3_key}');"
           f"select 'PIN_COUNT='||count(*) from execution_traces where entity_id='{pnr_id}' and correlation_id='{correlation_id}';")
    script = ('command -v psql >/dev/null 2>&1 || (apt-get update -qq >/dev/null 2>&1; apt-get install -y -qq postgresql-client >/dev/null 2>&1)\n'
              'export PGPASSWORD="$CCT_TRACING_DB_PASSWORD"\n'
              'psql -h "$CCT_TRACING_DB_HOST" -p "${CCT_TRACING_DB_PORT:-5432}" -d "$CCT_TRACING_DB_NAME" '
              '-U "$CCT_TRACING_DB_USER" -v ON_ERROR_STOP=1 -c "' + sql.replace('"', '\\"') + '"\n')
    b64 = base64.b64encode(script.encode()).decode()
    env2 = {**os.environ, "AWS_REGION": region, "MSYS_NO_PATHCONV": "1"}
    if profile:
        env2["AWS_PROFILE"] = profile
    r = subprocess.run(
        ["aws", "ecs", "execute-command", "--cluster", cluster, "--task", task,
         "--container", container, "--interactive",
         "--command", f'bash -c "echo {b64} | base64 -d | bash"'],
        input=b"", capture_output=True, timeout=290, env=env2)
    out = r.stdout.decode(errors="ignore") + r.stderr.decode(errors="ignore")
    if "PIN_COUNT=" not in out:
        raise RuntimeError("ECS-exec pin failed: " + out[-400:])
    return "inserted-ecs"


def extract_verdict(body: str, code: int) -> dict:
    """Parse a by-pnr determination body into {status_code, eligible, amount, system_code, reason,
    raw}. Surfaces the REAL verdict — whether ELIGIBLE or a negative one (NOT_ELIGIBLE /
    NO_DETERMINATION / PENDING) — by picking the passengerEligibility with the case's own systemCode
    (a non-`-NA-` code), preferring an ELIGIBLE one. The old code only read ELIGIBLE, so every
    negative scenario came back systemCode=none / amount=None / no reason and failed its checkpoints
    even though the pinned determination was correct."""
    out = {"status_code": code, "eligible": False, "amount": None, "system_code": None,
           "reason": None, "raw": body[:400]}
    try:
        d = json.loads(body)
    except Exception:
        return out
    best = None  # (priority, pe, status); prefer ELIGIBLE(2) > real negative verdict(1) > NA(0)
    for c in d.get("compensationEligibility", []):
        for pe in c.get("passengerEligibility", []):
            status = pe.get("eligibilityStatus") or ""
            sc = pe.get("systemCode") or ""
            prio = 2 if status == "ELIGIBLE" else (1 if (sc and "-NA-" not in sc) else 0)
            if best is None or prio > best[0]:
                best = (prio, pe, status)
    if best and best[0] > 0:
        _prio, pe, status = best
        cd = pe.get("compensationDetails") or {}
        out.update(eligible=(status == "ELIGIBLE"), amount=cd.get("amount"),
                   system_code=pe.get("systemCode"), reason=pe.get("reason"))
    return out


_s3_clients: dict = {}


def verify_from_s3(env, s3_key: str, *, region: str = "ca-central-1") -> dict:
    """Read a pinned determination straight out of the DDS store and extract its verdict.

    The fallback for environments whose by-pnr endpoint is not reachable from here — CRT's returns
    403 (see envs/crt.yaml), which would otherwise leave every DDS checkpoint unverifiable even
    though the determination was pinned correctly. This reads the exact object the rule-engine trace
    points at, so it confirms what the bot would serve, one hop earlier."""
    import boto3  # lazy

    dds = _dds_cfg(env)
    profile = (env.aws or {}).get("profile")
    key = (profile, region)
    s3 = _s3_clients.get(key)
    if s3 is None:  # one client per (profile, region) — creating one per case is pure overhead
        s3 = _s3_clients[key] = boto3.Session(profile_name=profile).client("s3", region_name=region)
    body = s3.get_object(Bucket=dds["store_bucket"], Key=s3_key)["Body"].read().decode("utf-8")
    out = extract_verdict(body, 200)
    out["source"] = "s3"
    return out


# Reused rule-engine connection for key lookups. Opening one per case means a Secrets Manager
# round-trip plus a TLS Postgres handshake for every PNR — at 132 cases that dominated the whole
# re-audit. Cached per env id; a dead connection is dropped and reopened on next use.
_trace_conn: dict = {}


def _rule_engine_conn(env):
    from seed.source import db_connect, read_secret

    dds = _dds_cfg(env)
    if not dds.get("rule_engine_host"):
        return None
    conn = _trace_conn.get(env.id)
    if conn is not None and getattr(conn, "closed", 0) == 0:
        return conn
    try:
        conn = db_connect(dds["rule_engine_host"], dds.get("rule_engine_db", "postgres"),
                          read_secret(env, (env.seed_targets or {}).get("rule_engine_secret")))
        conn.autocommit = True
    except Exception:  # noqa: BLE001 — no DB access just means no fallback key
        return None
    _trace_conn[env.id] = conn
    return conn


def pinned_s3_key(env, pnr_id: str) -> str | None:
    """The response_s3_key of the most recent DDS trace pinned for this pnr_id, or None.

    Lets the S3 fallback work when the caller does not already hold the key from its own pin (a
    later re-audit of a set seeded in an earlier run, for example)."""
    conn = _rule_engine_conn(env)
    if conn is None:
        return None
    try:
        cur = conn.cursor()
        cur.execute("select response_s3_key from execution_traces where entity_id=%s "
                    "and service_type='DDS' order by processed_at desc limit 1", (pnr_id,))
        row = cur.fetchone()
        cur.close()
        return row[0] if row else None
    except Exception:  # noqa: BLE001 — drop a broken connection so the next call reopens
        _trace_conn.pop(env.id, None)
        return None


# Sticky endpoint-down latch. The rule-engine API Gateway serves the whole environment behind a
# resource policy pinned to one VPC endpoint, so depending on how the request egresses (WARP
# routing) it can 403 — or fail to resolve — for every call at once. Once that is observed, going
# back to the endpoint for each of 132 cases just buys 132 timeouts, so later calls read the pinned
# S3 object directly. Mirrors the reference auditor's `_dds_endpoint_down`.
_endpoint_down = {"down": False}


def verify_by_pnr(env, pnr_id: str, *, timeout: int = 20, s3_key: str | None = None) -> dict:
    """GET the DDS by-pnr endpoint the bot uses; return the extracted verdict (see extract_verdict).

    On ANY endpoint failure — 403, DNS, timeout — falls back to the pinned S3 response, which is
    the exact object the endpoint would serve. The key comes from `s3_key` when the caller just
    pinned it, else from `pinned_s3_key()`. Raises only when both paths are unavailable."""
    import urllib.request  # lazy
    from core.secrets import resolve_secret

    dds = _dds_cfg(env)
    key = s3_key

    def _fallback(reason: str):
        nonlocal key
        if key is None:
            key = pinned_s3_key(env, pnr_id)
        if not key:
            return None
        if not _endpoint_down["down"]:
            _endpoint_down["down"] = True
            print(f"  [DDS] endpoint unreachable ({reason}) — falling back to pinned S3 responses "
                  f"({dds.get('store_bucket')})", flush=True)
        return verify_from_s3(env, key)

    if _endpoint_down["down"]:
        got = _fallback("cached")
        if got is not None:
            return got
    try:
        api_key = resolve_secret(dds["api_key_secret"])
        req = urllib.request.Request(f"{dds['by_pnr_url']}/{pnr_id}",
                                     headers={"x-api-key": api_key})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            out = extract_verdict(r.read().decode("utf-8"), r.getcode())
        out["source"] = "endpoint"
        if out.get("system_code") or out.get("eligible"):
            return out
        got = _fallback(f"empty verdict HTTP {out['status_code']}")
        return got if got is not None else out
    except Exception as exc:  # noqa: BLE001 — any endpoint failure is a fallback trigger
        got = _fallback(f"{type(exc).__name__}")
        if got is None:
            raise
        return got


def _default_expiry(date: str) -> str:
    """Claim-window expiry ~1 year after the flight date (APPR filing deadline is generous)."""
    import datetime as _dt

    try:
        d = _dt.date.fromisoformat(date)
    except ValueError:
        d = _dt.date.fromisoformat(date[:10])
    return (d.replace(year=d.year + 1)).isoformat()


def pin_case(env, *, pnr_id: str, locator: str, carrier: str, flight_number, origin: str,
             destination: str, date: str, family: str = "APPR_CAD_400",
             passenger_id: str | None = None, timestamp: str | None = None,
             expiry_date: str | None = None, system_code: str | None = None,
             amount: float | None = None, currency: str = "CAD",
             delay_minutes: int = 240, status: str = "") -> dict:
    """Full DDS pin for one case: rewrite the base template -> canonicalize to the bot shape ->
    S3 PutObject -> execution_traces INSERT. Returns {s3_key, pnr_id, family}.

    Two canonicalization paths:
      - `system_code` given  -> `canonicalize_verdict` (ANY verdict EL/NE/ND/PE, any regime), the
        general path used by `seed --all` so one base template covers all 239 cases;
      - else                 -> `canonicalize_appr(family)` (legacy APPR-CAD-eligible path).
    The base template is always the APPR family file (it only supplies the itinerary structure)."""
    dds = _dds_cfg(env)
    tpl_path = dds["templates"][family]
    template = load_template(tpl_path)
    response = rewrite_determination(
        template, pnr_id=pnr_id, locator=locator, carrier=carrier, flight_number=flight_number,
        origin=origin, destination=destination, passenger_id=passenger_id, timestamp=timestamp)
    # canonicalize to the bot's assess_eligibility shape, else the bot reads the pin but escalates.
    expiry = expiry_date or _default_expiry(date)
    if system_code:
        canonicalize_verdict(response, system_code=system_code, amount=amount or 0.0,
                             currency=currency, delay_minutes=delay_minutes, expiry_date=expiry,
                             status=status)
    else:
        canonicalize_appr(response, family, expiry_date=expiry)
    key = put_response(env, response, date=date)
    # Prefer the direct DB insert; fall back to ECS-exec when the cluster DB is SG-blocked from here.
    try:
        how = pin_trace(env, pnr_id, key)
    except Exception:
        how = pin_trace_ecs(env, pnr_id, key)
    return {"s3_key": key, "pnr_id": pnr_id, "family": family, "pin": how}
