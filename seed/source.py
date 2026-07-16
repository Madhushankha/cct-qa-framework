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


_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+")


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


def connect(env):
    """Build an AuroraSource from an Env descriptor's seed_targets. Requires boto3 + psycopg2
    (install the `live` extra). Read-only usage."""
    import boto3  # noqa: local import so the package imports without the live extra
    import psycopg2
    st = env.seed_targets
    secret_id = st["aurora_secret"]
    host = st["aurora_host"]
    # Use the env's AWS profile (SSO) explicitly — a bare boto3.client() would fall back to the
    # default credential chain (often absent/expired), which is why the checkpoint audit hit
    # ExpiredToken while the pin/trip paths (which pass profile_name) succeeded.
    region = env.chatbot.get("region", "ca-central-1")
    profile = (env.aws or {}).get("profile")
    sm = boto3.Session(profile_name=profile).client("secretsmanager", region_name=region)
    creds = json.loads(sm.get_secret_value(SecretId=secret_id)["SecretString"])
    conn = psycopg2.connect(host=host, port=5432, dbname="trip-tracer",
                            user=creds["username"], password=creds["password"],
                            sslmode="require", connect_timeout=20)
    conn.autocommit = True
    return AuroraSource(conn)
