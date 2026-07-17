"""Offline tests for runner.build — persona filling, judge tool schema, canonical-Result assembly with
injected fake flow + judge (NO network / Bedrock / bot). Also the Env -> config/OTP builders."""
from __future__ import annotations

from core.descriptors import Product, Env, Feed, RunContext
from core.result import validate_result
from catalog.model import SeedSpec, UseCase

from runner import build


# ── fixtures (self-contained; independent of the real registry) ──────────────
PERSONA = {
    "default": "You are CUSTOMER {first} {last}, PNR {pnr}. Disruption: {disruption}. Claim now.",
    "branches": {"third_party": "You file ON BEHALF OF {first} {last} ({minor_or_pax}), PNR {pnr}."},
}
JUDGE = {"verdict_enum": ["ELIGIBLE", "NOT_ELIGIBLE", "NO_DETERMINATION", "UNKNOWN"],
         "match_on": ["status", "amount"]}


def make_ctx() -> RunContext:
    product = Product(id="bravo", label="Bravo", transcript_dialect="bravo", overrides={}, defaults={})
    env = Env(id="int", label="INT",
              chatbot={"base_url": "https://x.example/prod", "endpoint_path": "/start-chat",
                       "region": "ca-central-1", "response_timeout_seconds": 120},
              aws={}, otp={"strategy": "fixed", "code": "654321"}, seed_targets={})
    feed = Feed(id="fd", label="Flight Disruption", gap_doc="", columns={}, persona=PERSONA,
                judge=JUDGE, checkpoints={"areas": []})
    return RunContext(product=product, env=env, feed=feed, scenario_prefix="bravo.int.fd",
                      persona=PERSONA, judge=JUDGE)


def make_uc(case_id="FD_TC_001", third_party=False, amount=None, passenger="Jane Marie Doe") -> UseCase:
    seed = SeedSpec(pnr="ABC123", pnr_id="ABC123-2026-07-16", passenger=passenger, route="YYZ-LHR",
                    ticket="0142212345678", status="ELIGIBLE", system_code="FD-APPR-NE-01",
                    amount=amount, currency=(amount or {}).get("currency", ""),
                    flags="APPR, DELAY", extras={"disruption": "flight YYZ-LHR delayed 6h",
                                                  "minor_or_pax": "minor"})
    return UseCase(id=case_id, regime="APPR", verdict="ELIGIBLE", system_code="FD-APPR-NE-01",
                   title="Delay comp", third_party=third_party, checkpoint_vector=[],
                   customer_intent="claim compensation", expected_transcript=[], seed=seed,
                   seed_pending=False, content_hash="")


# ── build_persona ────────────────────────────────────────────────────────────
def test_build_persona_fills_first_last_pnr():
    ctx, uc = make_ctx(), make_uc()
    prompt = build.build_persona(ctx, uc)
    assert "Jane" in prompt              # {first}
    assert "Marie Doe" in prompt         # {last} = everything after the first token
    assert "ABC123" in prompt            # {pnr}
    assert "delayed 6h" in prompt        # {disruption} from seed.extras
    assert "{" not in prompt             # all slots resolved / blanked


def test_build_persona_third_party_branch_chosen():
    ctx = make_ctx()
    uc = make_uc(third_party=True)
    prompt = build.build_persona(ctx, uc)
    assert "ON BEHALF OF" in prompt      # the third_party branch, not default
    assert "minor" in prompt             # {minor_or_pax} extra filled


def test_build_persona_uses_default_when_not_third_party():
    ctx, uc = make_ctx(), make_uc(third_party=False)
    prompt = build.build_persona(ctx, uc)
    assert "ON BEHALF OF" not in prompt
    assert prompt.startswith("You are CUSTOMER")


# ── build_judge ──────────────────────────────────────────────────────────────
def test_build_judge_enum_matches_feed():
    ctx = make_ctx()
    tool, judge_fn = build.build_judge(ctx)
    props = tool["toolSpec"]["inputSchema"]["json"]["properties"]
    assert props["decision"]["enum"] == JUDGE["verdict_enum"]
    assert tool["toolSpec"]["name"] == "submit_verdict"
    assert callable(judge_fn)


# ── run_case assembly (fake flow + fake judge, no network) ───────────────────
def _fake_flow(uc, persona, first, chat_config, otp_provider, br):
    assert "CUSTOMER" in persona and first == "Jane"   # persona reached the flow
    return {
        "transcript": [
            {"role": "assistant", "text": "Hello, how can I help?", "ts": None, "note": "greeting"},
            {"role": "customer", "text": "My flight was delayed.", "ts": "2026-07-16T00:00:01Z", "note": ""},
            {"role": "assistant", "text": "You are eligible for CAD 400.", "ts": None, "note": None},
        ],
        "contact_id": "contact-123", "otp_fetched": True, "error": None,
        "started": "2026-07-16T00:00:00Z", "duration_s": 12.3, "widgets": [],
    }


def _fake_judge(uc, transcript, br=None, model_id=None):
    assert any(t["role"] == "customer" for t in transcript)
    return {"bot_outcome_summary": "eligible 400", "decision": "ELIGIBLE", "amount": "CAD 400",
            "reached_determination": True, "matches_expected": True,
            "checks": [{"name": "status", "expected": "ELIGIBLE", "actual": "ELIGIBLE", "pass": True}],
            "reasoning": "bot confirmed eligibility and amount"}


def test_run_case_assembles_valid_result():
    ctx = make_ctx()
    uc = make_uc(amount={"currency": "CAD", "value": 400})
    result = build.run_case(ctx, uc, chat_config=None, otp_provider=None,
                            flow_fn=_fake_flow, judge_fn=_fake_judge, run_date="2026-07-16")
    validate_result(result)   # explicit belt-and-suspenders (run_case already validated)

    assert result["scenario_id"] == "bravo.int.fd.FD_TC_001"
    assert result["run"]["product"] == "bravo" and result["run"]["env"] == "int" and result["run"]["feed"] == "fd"
    assert result["case"]["test_case"] == "FD_TC_001"
    assert result["case"]["expected_status"] == "ELIGIBLE"
    assert result["case"]["expected_system_code"] == "FD-APPR-NE-01"
    assert result["case"]["expected_amount"] == {"currency": "CAD", "value": 400}
    assert result["case"]["flags"] == ["APPR", "DELAY"]
    assert result["verdict"]["decision"] == "ELIGIBLE"
    assert result["verdict"]["amount"] == {"currency": "CAD", "value": 400.0}
    assert result["verdict"]["matches_expected"] is True
    assert result["auth"] == {"otp_fetched": True, "contact_id": "contact-123"}
    assert result["seed"] == {"verified": False, "checkpoints": [], "dds": None}
    assert len(result["transcript"]) == 3
    assert result["harness"] == {"error": None, "error_bucket": None}


def test_run_case_no_transcript_yields_unknown_but_valid():
    ctx = make_ctx()
    uc = make_uc()

    def empty_flow(uc, persona, first, chat_config, otp_provider, br):
        return {"transcript": [], "contact_id": None, "otp_fetched": False,
                "error": "booking-lookup outage — session terminated",
                "started": "2026-07-16T00:00:00Z", "duration_s": 3.0, "widgets": []}

    result = build.run_case(ctx, uc, None, None, flow_fn=empty_flow, judge_fn=_fake_judge)
    validate_result(result)
    assert result["verdict"]["decision"] == "UNKNOWN"
    assert result["verdict"]["matches_expected"] is False
    assert result["harness"]["error_bucket"] == "outage"


# ── Env -> config / OTP ──────────────────────────────────────────────────────
def test_chat_config_from_env():
    ctx = make_ctx()
    cfg = build.chat_config_from_env(ctx.env)
    assert cfg.base_url == "https://x.example/prod"
    assert cfg.endpoint_path == "/start-chat"
    assert cfg.response_timeout_seconds == 120
    assert cfg.init_payload  # default init payload present so the client can handshake


def test_otp_provider_fixed():
    ctx = make_ctx()
    prov = build.otp_provider_from_env(ctx.env)
    assert isinstance(prov, build.FixedOtpProvider)
    assert prov.wait_for_otp(None) == "654321"


def test_otp_provider_mailinator_uses_secret(monkeypatch):
    monkeypatch.setenv("MAILINATOR_TOKEN", "tok-abc")
    env = Env(id="crt", label="CRT", chatbot={"region": "ca-central-1"}, aws={},
              otp={"strategy": "mailinator", "domain": "d.mailinator.com", "inbox": "lahiru",
                   "token_secret": "MAILINATOR_TOKEN"}, seed_targets={})
    prov = build.otp_provider_from_env(env)
    assert prov.token == "tok-abc" and prov.domain == "d.mailinator.com" and prov.inbox == "lahiru"
