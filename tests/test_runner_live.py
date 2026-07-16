"""GUARDED live smoke: drive ONE real case against an env and assert a canonical Result file is produced.
Skipped by default so offline runs never touch the network — set CCTQA_LIVE=1 (plus AWS creds + the live
extra) to enable. Cell defaults to brove.int.fd; override via CCTQA_PRODUCT / CCTQA_ENV / CCTQA_FEED."""
from __future__ import annotations

import json
import os

import pytest

pytestmark = pytest.mark.skipif(
    os.getenv("CCTQA_LIVE") != "1",
    reason="live chatbot smoke; set CCTQA_LIVE=1 (needs AWS + the [live] extra) to run",
)


def test_live_one_case(tmp_path):
    from core.registry import resolve
    from catalog.parser import load_catalog
    from core.result import validate_result
    from runner.orchestrator import run_batch

    product = os.getenv("CCTQA_PRODUCT", "brove")
    env = os.getenv("CCTQA_ENV", "int")
    feed = os.getenv("CCTQA_FEED", "fd")

    ctx = resolve(product, env, feed)
    cases = load_catalog(ctx.feed).cases[:1]
    assert cases, "no use-cases available to drive"

    paths = run_batch(ctx, cases, str(tmp_path), conc=1, otp_conc=1, stagger=0.0)
    assert len(paths) == 1
    assert paths[0].exists()

    doc = json.loads(paths[0].read_text(encoding="utf-8"))
    validate_result(doc)
    assert doc["scenario_id"].startswith(f"{product}.{env}.{feed}.")
