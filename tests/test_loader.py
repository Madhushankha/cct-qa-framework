import pytest
from core.registry import load_feed, load_product, load_env, list_feeds, list_envs, RegistryError
from core.descriptors import Feed, Product, Env


def test_load_feed():
    f = load_feed("fd")
    assert isinstance(f, Feed)
    assert f.id == "fd"
    assert f.columns["pnr"] == "Locator"
    assert "ELIGIBLE" in f.judge["verdict_enum"]


def test_load_env_and_product():
    e = load_env("crt")
    assert isinstance(e, Env)
    assert e.otp["strategy"] == "mailinator"
    p = load_product("bravo")
    assert isinstance(p, Product)
    assert p.defaults["feeds"] == ["fd", "soc"]


def test_listers():
    assert set(list_feeds()) >= {"fd", "soc"}
    assert set(list_envs()) >= {"crt", "int"}


def test_missing_feed_raises():
    with pytest.raises(RegistryError):
        load_feed("does_not_exist")
