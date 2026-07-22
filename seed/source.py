"""Data sources for the seed verifier. The pure verify logic (verify.py) runs against this small
read-only interface, so it is unit-testable with FakeSource and runs live via AuroraSource."""
from __future__ import annotations

import json
import re
from typing import Protocol


class TripTracerSource(Protocol):
    """Read-only lookups a checkpoint auditor needs. All keyed by 6-char locator (pnr)."""
    def eds(self, pnr: str) -> dict | None: ...        # {"emails": [...], "passengers": [...], "raw": str}
    def trip(self, pnr: str) -> dict | None: ...        # {"last_name": str, "status": str}
    def tickets(self, pnr: str) -> list[str]: ...       # ticket numbers
    def passengers(self, pnr: str) -> list[str]: ...    # passenger full names
    def dob(self, pnr: str) -> str | None: ...          # a passenger date_of_birth, or None
    # ── added for the ported checkpoint areas ──
    def surnames_present(self, surnames: list[str]) -> set[str]: ...  # which already exist (name gen)
    def names_elsewhere(self, pnr: str) -> set[tuple]: ...  # this PNR's (first,last) seen on OTHER pnrs
    def booking_context(self, pnr: str) -> dict | None: ...  # eds_pnr_output.booking_context
    def loyalty(self, pnr: str) -> list[str]: ...       # Aeroplan/FQTV membership ids on the booking
    def flight_dates(self, pnr: str) -> list[str]: ...  # scheduled departure dates (PENDING window)


class FakeSource:
    """Dict-backed source for offline unit tests."""
    def __init__(self, data: dict):
        self._d = data  # {pnr: {"eds": {...}|None, "trip": {...}|None, "tickets": [...], "passengers": [...]}}

    def _get(self, pnr, key, default):
        return (self._d.get(pnr) or {}).get(key, default)

    def eds(self, pnr): return self._get(pnr, "eds", None)
    def trip(self, pnr): return self._get(pnr, "trip", None)
    def tickets(self, pnr): return self._get(pnr, "tickets", [])
    def passengers(self, pnr): return self._get(pnr, "passengers", [])
    def dob(self, pnr): return self._get(pnr, "dob", None)

    def surnames_present(self, surnames):
        taken = {s.upper() for s in (self._d.get("_surnames_in_db") or [])}
        return {s for s in (x.upper() for x in surnames) if s in taken}

    def names_elsewhere(self, pnr):
        return {tuple(x) for x in self._get(pnr, "names_elsewhere", [])}

    def booking_context(self, pnr): return self._get(pnr, "booking_context", None)
    def loyalty(self, pnr): return self._get(pnr, "loyalty", [])
    def flight_dates(self, pnr): return self._get(pnr, "flight_dates", [])


_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+")
# FQTV / Aeroplan membership as it appears in the eds bounds blob, e.g.
# "frequentTravellerNumber":"123456789" or "loyaltyMembershipId": "AC 123456789".
_FQTV_RE = re.compile(
    r'"(?:frequentTravellerNumber|loyaltyMembershipId|membershipNumber)"\s*:\s*"([^"]+)"')


class AuroraSource:
    """Live read-only source backed by a psycopg2 connection to trip-tracer Aurora.
    Import-safe without psycopg2/boto3 — those are only needed to CONSTRUCT one (see connect())."""
    def __init__(self, conn):
        self._conn = conn

    def _q(self, sql, params):
        cur = self._conn.cursor()
        cur.execute(sql, params)
        rows = cur.fetchall()
        cur.close()
        return rows

    def eds(self, pnr):
        rows = self._q(
            "select bounds from eds_pnr_output where substring(pnr_id from 1 for 6)=%s limit 1", (pnr,))
        if not rows:
            return None
        raw = rows[0][0] if isinstance(rows[0][0], str) else json.dumps(rows[0][0], default=str)
        emails = sorted(set(_EMAIL_RE.findall(raw)))
        return {"emails": emails, "raw": raw}

    def trip(self, pnr):
        rows = self._q(
            "select last_name, status from trip where substring(pnr_id from 1 for 6)=%s limit 1", (pnr,))
        if not rows:
            return None
        last, status = rows[0]
        if isinstance(last, list):
            last = last[0] if last else ""
        return {"last_name": last, "status": status}

    def tickets(self, pnr):
        rows = self._q(
            "select primary_document_number from ticket where substring(pnr_id from 1 for 6)=%s", (pnr,))
        return [str(r[0]) for r in rows if r[0]]

    def passengers(self, pnr):
        rows = self._q(
            "select first_name, last_name from passenger where substring(pnr_id from 1 for 6)=%s", (pnr,))
        out = []
        for fn, ln in rows:
            fn = fn[0] if isinstance(fn, list) and fn else fn
            ln = ln[0] if isinstance(ln, list) and ln else ln
            out.append(f"{fn or ''} {ln or ''}".strip())
        return out

    def dob(self, pnr):
        rows = self._q(
            "select date_of_birth from passenger where substring(pnr_id from 1 for 6)=%s "
            "and date_of_birth is not null limit 1", (pnr,))
        return str(rows[0][0]) if rows and rows[0][0] else None

    # ── ported checkpoint lookups ─────────────────────────────────────────────────────────────
    def surnames_present(self, surnames):
        """Which of `surnames` already exist in passenger.last_name (uppercased match)."""
        if not surnames:
            return set()
        wanted = [s.upper() for s in surnames]
        rows = self._q(
            "select distinct upper(last_name) from passenger where upper(last_name) = any(%s)",
            (wanted,))
        return {r[0] for r in rows if r[0]}

    def names_elsewhere(self, pnr):
        """(first, last) pairs on this PNR that ALSO appear on a different pnr_id — the DB-collision
        half of the name-uniqueness check. Uppercased; empty set means every name is exclusive."""
        pairs = self._q(
            "select distinct upper(first_name), upper(last_name) from passenger "
            "where substring(pnr_id from 1 for 6)=%s and not is_removed", (pnr,))
        pairs = [(f, ln) for f, ln in pairs if f and ln]
        if not pairs:
            return set()
        rows = self._q(
            "select distinct upper(first_name), upper(last_name) from passenger "
            "where (upper(first_name), upper(last_name)) in %s "
            "and substring(pnr_id from 1 for 6) <> %s and not is_removed",
            (tuple(pairs), pnr))
        return {(f, ln) for f, ln in rows}

    def booking_context(self, pnr):
        rows = self._q(
            "select booking_context from eds_pnr_output where substring(pnr_id from 1 for 6)=%s "
            "and booking_context is not null limit 1", (pnr,))
        if not rows:
            return None
        bc = rows[0][0]
        return json.loads(bc) if isinstance(bc, str) else bc

    def loyalty(self, pnr):
        """Aeroplan / FQTV membership ids carried on the booking. Read from the eds bounds blob,
        which is where the cascade lands the FQTV element (no dedicated column)."""
        eds = self.eds(pnr)
        if not eds:
            return []
        return sorted(set(_FQTV_RE.findall(eds.get("raw") or "")))

    def flight_dates(self, pnr):
        """Scheduled departure dates of the booking's segments (local), for the PENDING window."""
        rows = self._q(
            "select distinct departure_datetime_local::date from flight_segment "
            "where substring(pnr_id from 1 for 6)=%s and departure_datetime_local is not null "
            "and not is_removed", (pnr,))
        return [str(r[0]) for r in rows if r[0]]


def db_connect(host, dbname, secret: dict, *, port: int = 5432, timeout: int = 20):
    """psycopg2 connection, trying each credential pair the secret carries until one authenticates.

    The CCT secrets hold BOTH a `username`/`password` and an `adminuser`/`adminpassword` pair, and
    which one works differs per database: trip-tracer goes through an RDS proxy that only accepts
    `dbdevuser` (`username`), while the rule-engine cluster rejects that user and accepts `dbadmin`
    (`adminuser`). Picking one statically fails half the time — hence the ordered fallback. Raises
    the last authentication error when no pair works."""
    import psycopg2

    pairs = [(secret.get("username"), secret.get("password")),
             (secret.get("adminuser"), secret.get("adminpassword"))]
    last = None
    for user, pw in pairs:
        if not user or not pw:
            continue
        try:
            return psycopg2.connect(host=host, port=port, dbname=dbname, user=user, password=pw,
                                    sslmode="require", connect_timeout=timeout)
        except psycopg2.OperationalError as exc:
            if "password authentication failed" not in str(exc):
                raise  # a network/DNS/timeout failure is not something another user would fix
            last = exc
    raise last or RuntimeError(f"no usable credential pair in the secret for {host}/{dbname}")


def read_secret(env, secret_id: str) -> dict:
    """Fetch and parse a Secrets Manager JSON secret using the env's AWS profile."""
    import boto3  # noqa: local import so the package imports without the live extra

    region = env.chatbot.get("region", "ca-central-1")
    profile = (env.aws or {}).get("profile")
    sm = boto3.Session(profile_name=profile).client("secretsmanager", region_name=region)
    return json.loads(sm.get_secret_value(SecretId=secret_id)["SecretString"])


def connect(env):
    """Build an AuroraSource from an Env descriptor's seed_targets. Requires boto3 + psycopg2
    (install the `live` extra). Read-only usage."""
    # Uses the env's AWS profile (SSO) explicitly — a bare boto3.client() would fall back to the
    # default credential chain (often absent/expired), which is why the checkpoint audit hit
    # ExpiredToken while the pin/trip paths (which pass profile_name) succeeded.
    st = env.seed_targets
    conn = db_connect(st["aurora_host"], "trip-tracer", read_secret(env, st["aurora_secret"]))
    conn.autocommit = True
    return AuroraSource(conn)
