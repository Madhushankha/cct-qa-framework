"""Async batched orchestration with the OTP-phase gate + shared Bedrock semaphore + staggered starts —
the pattern from cct-qa-1/fd-int-flow/run_flow_async.py, reimplemented descriptor-driven (no per-flow
dict wiring). One asyncio loop drives all sessions; the blocking per-session work (boto3/websocket/OTP)
runs in a thread pool.

The OTP-phase gate limits how many sessions may be inside the OTP wait at once (that's the part that
hammers the verification-send backend); a session frees its slot the moment the code is fetched/times out
so the next session is admitted while this one keeps going through its backend-light chat + judge phase.

run_batch is offline-testable: inject a fake run_case_fn (no network). The OTP gate wraps the provided
otp_provider, so a fake case that calls otp_provider.wait_for_otp is admitted at most otp_conc at a time.
"""
from __future__ import annotations

import asyncio
import threading
from pathlib import Path

from core.result import write_result


def _gate_provider(otp_provider, gate: threading.Semaphore):
    """Wrap an OTP provider so its wait_for_otp acquires `gate` for the duration of the wait (releases on
    return/raise). Only `gate._value` sessions can be in the OTP window at once."""
    if otp_provider is None:
        return None
    orig_wait = otp_provider.wait_for_otp

    def gated_wait(*a, **k):
        with gate:
            return orig_wait(*a, **k)

    otp_provider.wait_for_otp = gated_wait
    return otp_provider


async def _stagger(lock: asyncio.Lock, last: list, stagger: float, loop):
    async with lock:
        wait = max(0.0, last[0] + stagger - loop.time())
        if wait:
            await asyncio.sleep(wait)
        last[0] = loop.time()


def run_batch(ctx, use_cases, out_dir, *, conc=14, otp_conc=6, stagger=2.0, limit=None,
              bedrock_conc=8, chat_config=None, otp_provider=None, run_case_fn=None,
              run_id=None, run_date=None) -> list[Path]:
    """Drive run_case over use_cases and write each canonical Result to out_dir/<id>.result.json.

    Returns the written paths. conc = max concurrent sessions; otp_conc = OTP-phase gate width;
    stagger = seconds between session starts; bedrock_conc = shared Bedrock TPS budget."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    cases = list(use_cases)[: (limit if limit is not None else len(list(use_cases)))]

    # Build engine config/OTP from the Env descriptor when not injected (real path only — kept lazy so a
    # fake-run_case_fn test never imports the engine).
    if run_case_fn is None:
        from runner import build as _build
        from runner.engine import bedrock as _bedrock

        _bedrock.set_concurrency(bedrock_conc)  # shared Bedrock semaphore
        if chat_config is None:
            chat_config = _build.chat_config_from_env(ctx.env)
        if otp_provider is None:
            otp_provider = _build.otp_provider_from_env(ctx.env)
        run_case_fn = _build.run_case

    otp_gate = threading.Semaphore(otp_conc)
    gated_provider = _gate_provider(otp_provider, otp_gate)

    async def _drive():
        loop = asyncio.get_running_loop()
        sem = asyncio.Semaphore(conc)
        lock = asyncio.Lock()
        last = [0.0]
        written: list[Path] = []

        async def one(uc):
            async with sem:
                await _stagger(lock, last, stagger, loop)
                result = await asyncio.to_thread(
                    run_case_fn, ctx, uc, chat_config, gated_provider,
                    run_id=run_id, run_date=run_date)
                path = out / f"{uc.id}.result.json"
                write_result(result, path)  # re-validates before writing
                written.append(path)
                print(f"   wrote {path.name} "
                      f"(otp={result.get('auth', {}).get('otp_fetched')} "
                      f"decision={result.get('verdict', {}).get('decision')})", flush=True)
                return path

        await asyncio.gather(*[asyncio.create_task(one(uc)) for uc in cases])
        # preserve input order
        by_id = {p.stem.replace(".result", ""): p for p in written}
        return [by_id[uc.id] for uc in cases if uc.id in by_id]

    return asyncio.run(_drive())
