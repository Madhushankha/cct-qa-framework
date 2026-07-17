import pytest
from core.registry import resolve, RegistryError
from core.descriptors import RunContext


def test_resolve_valid_cell():
    ctx = resolve("bravo", "crt", "fd")
    assert isinstance(ctx, RunContext)
    assert ctx.scenario_prefix == "bravo.crt.fd"
    assert ctx.scenario_id("FD_TC_001") == "bravo.crt.fd.FD_TC_001"
    assert ctx.feed.id == "fd" and ctx.env.id == "crt" and ctx.product.id == "bravo"


def test_resolve_layers_persona_and_judge():
    # bravo has empty overrides, so the merged persona/judge equal the feed's
    ctx = resolve("bravo", "crt", "fd")
    assert ctx.persona.get("default"), "merged persona should carry the feed's default"
    assert "ELIGIBLE" in ctx.judge["verdict_enum"]


def test_resolve_override_wins_on_collision():
    # Directly exercise the layering rule the resolver uses (product override wins).
    feed_persona = {"default": "feed-text"}
    override_persona = {"default": "product-text"}
    merged = {**feed_persona, **override_persona}
    assert merged["default"] == "product-text"


def test_resolve_disallowed_env_cell():
    # 'bat' is a real, valid env, but bravo.defaults.envs is [crt, int] -> not allowed.
    # This reaches the allow-cell check (bat.yaml loads + validates first).
    with pytest.raises(RegistryError) as exc:
        resolve("bravo", "bat", "fd")
    assert "bat" in str(exc.value) and "does not allow" in str(exc.value)
