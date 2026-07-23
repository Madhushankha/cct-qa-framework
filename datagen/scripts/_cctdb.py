"""Shared trip-tracer connection for the CRT builders.

Every builder used to carry a plaintext dbadmin password inline. The credential sweep replaced those
with `os.environ.get("CCT_TRIPTRACER_PASSWORD","")` — which is empty by default, so `tt_conn()` fails
with "no password supplied". This helper resolves the credentials from Secrets Manager instead (the
same secret the checkpoint scripts use), trying both pairs the secret carries: the trip-tracer proxy
accepts only `dbdevuser` (username/password) while the cluster endpoint accepts only `dbadmin`
(adminuser/adminpassword), so a static choice fails half the hosts.

Usage in a builder:
    import _cctdb
    def tt_conn(): return _cctdb.trip_tracer(CRT["tt_host"], profile=CRT.get("profile"))
"""
import json
import os

_SECRET_ID = "/crt-cac1/ac-cct-trip-tracer-rds-cluster-crt-cac1/db-credentials"
_cache = {}


def _secret(profile, region="ca-central-1"):
    if "sec" not in _cache:
        import boto3
        sm = boto3.Session(profile_name=profile, region_name=region).client("secretsmanager")
        _cache["sec"] = json.loads(sm.get_secret_value(SecretId=_SECRET_ID)["SecretString"])
    return _cache["sec"]


def trip_tracer(host, *, dbname="trip-tracer", profile=None, region="ca-central-1", timeout=20):
    """Read-write psycopg2 connection to CRT trip-tracer, trying each credential pair in the secret."""
    import psycopg2

    profile = profile or os.environ.get("AWS_PROFILE") or "ac-cct-crt"
    sec = _secret(profile, region)
    pairs = [(sec.get("username"), sec.get("password")),
             (sec.get("adminuser"), sec.get("adminpassword"))]
    last = None
    for user, pw in pairs:
        if not user or not pw:
            continue
        try:
            return psycopg2.connect(host=host, port=5432, dbname=dbname, user=user, password=pw,
                                    sslmode="require", connect_timeout=timeout)
        except psycopg2.OperationalError as exc:
            if "password authentication failed" not in str(exc):
                raise
            last = exc
    raise last or RuntimeError(f"no usable credential pair for {host}/{dbname}")
