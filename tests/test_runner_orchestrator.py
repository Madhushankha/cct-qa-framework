"""Offline test for runner.orchestrator.run_batch — with an injected fake run_case (NO network):
it writes one <id>.result.json per use-case and returns their paths, and the OTP-phase gate admits at
most otp_conc sessions into the OTP window at once."""
from __future__ import annotations

import datetime
import threading
import time
from datetime import timezone

from core.descriptors import Product, Env, Feed, RunContext
from catalog.model import SeedSpec, UseCase

from runner import build
from runner.orchestrator import run_batch


def make_ctx() -> RunContext:
    product = Product(id="brove", label="Brove", transcript_dialect="brove", overrides={}, defaults={})
    env = Env(id="int", label="INT", chatbot={}, aws={}, otp={"strategy": "fixed"}, seed_targets={})
    feed = Feed(id="fd", label="FD", gap_doc="", columns={},
                persona={"default": "You are CUSTOMER {first} {last} PNR {pnr}."},
                judge={"verdict_enum": ["ELIGIBLE", "UNKNOWN"], "match_on": ["status"]},
                checkpoints={"areas": []})
    return RunContext(product=product, env=env, feed=feed, scenario_prefix="brove.int.fd",
                      persona=feed.persona, judge=feed.judge)


def make_uc(i: int) -> UseCase:
    seed = SeedSpec(pnr=f"PNR{i:03d}", pnr_id=f"PNR{i:03d}-2026", passenger="Jane Doe",
                    status="ELIGIBLE", system_code="FD-01", amount=None, flags="")
    return UseCase(id=f"FD_TC_{i:03d}", regime="APPR", verdict="ELIGIBLE", system_code="FD-01",
                   title="t", third_party=False, checkpoint_vector=[], customer_intent="",
                   expected_transcript=[], seed=seed, seed_pending=False, content_hash="")


class CountingOtp:
    """Records the peak number of concurrent wait_for_otp calls (the OTP window occupancy)."""
    def __init__(self):
        self._lock = threading.Lock()
        self.current = 0
        self.peak = 0

    def wait_for_otp(self, since, *, otp_filter=None, timeout_seconds=None):
        with self._lock:
            self.current += 1
            self.peak = max(self.peak, self.current)
        time.sleep(0.05)   # hold the slot so overlap is observable
        with self._lock:
            self.current -= 1
        return "123456"


def _fake_flow(uc, persona, first, chat_config, otp_provider, br):
    return {"transcript": [{"role": "customer", "text": "hi", "ts": None, "note": ""}],
            "contact_id": f"c-{uc.id}", "otp_fetched": True, "error": None,
            "started": "2026-07-16T00:00:00Z", "duration_s": 0.1, "widgets": []}


def _fake_judge(uc, transcript, br=None, model_id=None):
    return {"bot_outcome_summary": "ok", "decision": "ELIGIBLE", "amount": "none",
            "reached_determination": True, "matches_expected": True, "checks": [], "reasoning": "ok"}


def test_run_batch_writes_files_and_returns_paths(tmp_path):
    ctx = make_ctx()
    cases = [make_uc(i) for i in range(1, 7)]   # 6 cases
    otp = CountingOtp()
    otp_conc = 2

    def fake_run_case(ctx, uc, chat_config, otp_provider, *, run_id=None, run_date=None, checkpoints_dir=None):
        # enter the OTP window (gated by run_batch), then assemble a real, schema-valid Result
        otp_provider.wait_for_otp(datetime.datetime.now(timezone.utc))
        return build.run_case(ctx, uc, chat_config, otp_provider,
                              flow_fn=_fake_flow, judge_fn=_fake_judge,
                              run_id=run_id, run_date=run_date)

    paths = run_batch(ctx, cases, str(tmp_path), conc=6, otp_conc=otp_conc, stagger=0.0,
                      otp_provider=otp, run_case_fn=fake_run_case)

    assert len(paths) == 6
    for uc in cases:
        p = tmp_path / f"{uc.id}.result.json"
        assert p.exists()
        assert p in paths
    # the OTP-phase gate must never have admitted more than otp_conc at once
    assert otp.peak <= otp_conc
    assert otp.peak >= 1


def test_run_batch_limit(tmp_path):
    ctx = make_ctx()
    cases = [make_uc(i) for i in range(1, 6)]
    otp = CountingOtp()

    def fake_run_case(ctx, uc, chat_config, otp_provider, *, run_id=None, run_date=None, checkpoints_dir=None):
        return build.run_case(ctx, uc, chat_config, otp_provider,
                              flow_fn=_fake_flow, judge_fn=_fake_judge,
                              run_id=run_id, run_date=run_date)

    paths = run_batch(ctx, cases, str(tmp_path), conc=3, otp_conc=2, stagger=0.0, limit=2,
                      otp_provider=otp, run_case_fn=fake_run_case)
    assert len(paths) == 2
