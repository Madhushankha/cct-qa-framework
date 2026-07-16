import pytest
from core.secrets import resolve_secret, SecretError


def test_resolve_from_env(monkeypatch):
    monkeypatch.setenv("MAILINATOR_TOKEN", "abc123")
    assert resolve_secret("MAILINATOR_TOKEN") == "abc123"


def test_missing_secret_raises(monkeypatch):
    monkeypatch.delenv("NOPE_SECRET", raising=False)
    with pytest.raises(SecretError) as exc:
        resolve_secret("NOPE_SECRET")
    assert "NOPE_SECRET" in str(exc.value)


def test_empty_secret_raises(monkeypatch):
    monkeypatch.setenv("EMPTY_SECRET", "")
    with pytest.raises(SecretError):
        resolve_secret("EMPTY_SECRET")
