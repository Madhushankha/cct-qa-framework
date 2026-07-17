"""Tests for catalog/fixtures.py — free-text expected parsing + meta.json -> UseCase."""
import json

from catalog.fixtures import (derive_verdict, load_fixture_catalog, parse_amount,
                              usecase_from_meta)


def test_parse_amount_money():
    assert parse_amount("CAD 400 cash") == {"currency": "CAD", "value": 400.0}
    assert parse_amount("ILS 3,580 (ASL 480m+)") == {"currency": "ILS", "value": 3580.0}
    assert parse_amount("EUR 400/600 (EU 4h+)") == {"currency": "EUR", "value": 400.0}


def test_parse_amount_rejects_duration_only():
    assert parse_amount("GBP (UK 3-4h)") is None
    assert parse_amount("below threshold - accepted") is None
    assert parse_amount("") is None


def test_derive_verdict():
    assert derive_verdict("CAD 400 cash", {"currency": "CAD", "value": 400.0}) == "ELIGIBLE"
    assert derive_verdict("denied boarding - NE (diff regime)", None) == "NOT_ELIGIBLE"
    assert derive_verdict("handed to agent", None) == "ESCALATED"
    assert derive_verdict("something odd", None) == "UNKNOWN"


def test_usecase_from_meta():
    uc = usecase_from_meta({
        "locator": "FDAP36", "pnr_id": "FDAP36-2026-06-13", "first": "MARA",
        "surname": "OKONKWO", "route": "YYZ-LHR", "ticket": "0142000800200",
        "expected": "CAD 400 cash", "fdm_spec": "240m/43 x1", "pax": "ADT",
        "carrier": "AC", "flight": 8002, "date": "2026-06-13",
    })
    assert uc.id == "FDAP36" and uc.seed.pnr == "FDAP36"
    assert uc.seed.passenger == "MARA OKONKWO"
    assert uc.verdict == "ELIGIBLE" and uc.regime == "APPR"
    assert uc.seed.amount == {"currency": "CAD", "value": 400.0}
    assert uc.seed.extras["disruption"] == "240m/43 x1"


def test_load_fixture_catalog(tmp_path):
    d = tmp_path / "FDAP36"
    d.mkdir()
    (d / "meta.json").write_text(json.dumps({
        "locator": "FDAP36", "pnr_id": "FDAP36-2026-06-13", "first": "MARA",
        "surname": "OKONKWO", "expected": "CAD 400 cash"}), encoding="utf-8")
    cat = load_fixture_catalog(tmp_path)
    assert [c.id for c in cat.cases] == ["FDAP36"]
    assert cat.feed_id == "fd"
