"""preflight_credentials validates AWS creds before the verify phase so an SSO token that lapsed
during the settle produces a fast, clean failure (not a per-worker explosion)."""
import types

import pytest

from seed import cli


class _Env:
    aws = {"profile": "int-sso"}
    chatbot = {"region": "ca-central-1"}


def test_preflight_ok(monkeypatch):
    class _Sts:
        def get_caller_identity(self):
            return {"Arn": "arn:aws:sts::1:assumed-role/Arc75/lahiru"}

    class _Creds:
        def get_frozen_credentials(self):
            return object()

    class _Sess:
        def __init__(self, **kw):
            pass

        def get_credentials(self):
            return _Creds()

        def client(self, *a, **k):
            return _Sts()

    monkeypatch.setitem(__import__("sys").modules, "boto3",
                        types.SimpleNamespace(Session=_Sess))
    ok, detail = cli.preflight_credentials(_Env())
    assert ok is True and "Arc75" in detail


def test_preflight_expired(monkeypatch):
    class _Sess:
        def __init__(self, **kw):
            pass

        def get_credentials(self):
            raise RuntimeError("ExpiredToken: The security token is expired")

        def client(self, *a, **k):
            raise AssertionError("should not reach client() when creds fail")

    monkeypatch.setitem(__import__("sys").modules, "boto3",
                        types.SimpleNamespace(Session=_Sess))
    ok, detail = cli.preflight_credentials(_Env())
    assert ok is False and "ExpiredToken" in detail
