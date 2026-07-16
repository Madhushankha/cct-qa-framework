from core.descriptors import Feed, Product, Env, RunContext, SEEDSPEC_REQUIRED


def test_seedspec_required_fields():
    assert SEEDSPEC_REQUIRED == (
        "pnr", "pnr_id", "passenger", "route", "ticket",
        "status", "system_code", "amount", "currency", "flags",
    )


def test_feed_is_frozen():
    f = Feed(id="fd", label="Flight Disruption", gap_doc="data/x.html",
             columns={}, persona={}, judge={}, checkpoints={})
    assert f.id == "fd"
    try:
        f.id = "soc"  # type: ignore[misc]
        raised = False
    except Exception:
        raised = True
    assert raised, "Feed must be frozen/immutable"


def test_runcontext_scenario_id():
    p = Product(id="brove", label="Brove", transcript_dialect="brove", overrides={}, defaults={})
    e = Env(id="crt", label="CRT", chatbot={}, aws={}, otp={}, seed_targets={})
    f = Feed(id="fd", label="FD", gap_doc="x", columns={}, persona={}, judge={}, checkpoints={})
    ctx = RunContext(product=p, env=e, feed=f, scenario_prefix="brove.crt.fd")
    assert ctx.scenario_id("FD_TC_089") == "brove.crt.fd.FD_TC_089"
