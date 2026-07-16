import pytest
from core.registry import resolve, RegistryError
from core.descriptors import RunContext


def test_resolve_valid_cell():
    ctx = resolve("brove", "crt", "fd")
    assert isinstance(ctx, RunContext)
    assert ctx.scenario_prefix == "brove.crt.fd"
    assert ctx.scenario_id("FD_TC_001") == "brove.crt.fd.FD_TC_001"
    assert ctx.feed.id == "fd" and ctx.env.id == "crt" and ctx.product.id == "brove"


def test_resolve_disallowed_feed_cell():
    # brove.defaults.feeds is [fd, soc]; 'nc' is not allowed
    with pytest.raises(RegistryError) as exc:
        resolve("brove", "crt", "nc")
    assert "nc" in str(exc.value)
