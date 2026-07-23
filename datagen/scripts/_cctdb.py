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

_TT_SECRET = "/crt-cac1/ac-cct-trip-tracer-rds-cluster-crt-cac1/db-credentials"
_RE_SECRET = "/crtca1/ac-cct-rule-engine-crt-cac1-cluster/db-credentials"
_cache = {}


def _secret(secret_id, profile, region="ca-central-1"):
    if secret_id not in _cache:
        import boto3
        sm = boto3.Session(profile_name=profile, region_name=region).client("secretsmanager")
        _cache[secret_id] = json.loads(sm.get_secret_value(SecretId=secret_id)["SecretString"])
    return _cache[secret_id]


def trip_tracer(host, *, dbname="trip-tracer", profile=None, region="ca-central-1", timeout=20):
    """Read-write psycopg2 connection to CRT trip-tracer, trying each credential pair in the secret."""
    import psycopg2

    return _connect(host, dbname, _secret(_TT_SECRET, profile or os.environ.get("AWS_PROFILE") or "ac-cct-crt", region), timeout)


def rule_engine(host, *, dbname="postgres", profile=None, region="ca-central-1", timeout=25):
    """Read-write psycopg2 connection to the CRT rule-engine cluster (execution_traces / DDS pin)."""
    return _connect(host, dbname, _secret(_RE_SECRET, profile or os.environ.get("AWS_PROFILE") or "ac-cct-crt", region), timeout)


def _connect(host, dbname, sec, timeout):
    import psycopg2

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
