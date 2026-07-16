import pytest
from core.descriptors import Feed, Product, Env
from core.validate import validate_feed, validate_env, validate_all, DescriptorError


def _good_feed(**kw):
    base = dict(
        id="fd", label="FD", gap_doc="data/gap-docs/fd/x.html",
        columns={k: k for k in ("pnr", "pnr_id", "passenger", "route", "ticket",
                                 "status", "system_code", "amount", "currency", "flags")},
        persona={"default": "hi {pnr}"}, judge={"verdict_enum": ["ELIGIBLE"], "match_on": ["status"]},
        checkpoints={"auditor": "fd", "areas": ["trip_active"]},
    )
    base.update(kw)
    return Feed(**base)


def test_good_feed_passes():
    validate_feed(_good_feed())  # no raise


def test_feed_missing_seedspec_column_fails():
    cols = {k: k for k in ("pnr", "pnr_id", "passenger", "route", "ticket",
                           "status", "system_code", "amount", "currency")}  # missing 'flags'
    with pytest.raises(DescriptorError) as exc:
        validate_feed(_good_feed(columns=cols))
    assert "flags" in str(exc.value)


def test_env_bad_otp_strategy_fails():
    e = Env(id="crt", label="CRT", chatbot={"base_url": "x", "endpoint_path": "/y", "region": "z"},
            aws={"profile": "p", "account": "1"}, otp={"strategy": "carrier-pigeon"}, seed_targets={})
    with pytest.raises(DescriptorError) as exc:
        validate_env(e)
    assert "strategy" in str(exc.value)


def test_validate_all_on_checked_in_registry_is_clean():
    errors = validate_all()
    assert errors == [], f"registry should validate clean, got: {errors}"
