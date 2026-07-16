"""`cctqa run <product> <env> <feed> [--n N] [--conc C] [--out DIR]` — resolve the RunContext, load the
feed catalog, select N use-cases, drive them through the async batched runner, and print a summary."""
from __future__ import annotations

import argparse
import datetime
import json
from pathlib import Path


def run_run(product: str, env: str, feed: str, n: int | None, conc: int,
            out_dir: str | None, otp_conc: int = 6, stagger: float = 2.0) -> int:
    from core.registry import resolve
    from catalog.parser import load_catalog

    from runner.orchestrator import run_batch

    ctx = resolve(product, env, feed)
    catalog = load_catalog(ctx.feed)
    cases = catalog.cases
    if not cases:
        print(f"no use-cases in feed '{feed}' — nothing to run")
        return 1
    if n is not None:
        cases = cases[:n]

    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    out = out_dir or str(Path("runs") / f"{product}.{env}.{feed}" / stamp)

    print(f"[run] {product}.{env}.{feed}: {len(cases)} case(s), conc={conc}, otp-conc={otp_conc} -> {out}",
          flush=True)
    paths = run_batch(ctx, cases, out, conc=conc, otp_conc=otp_conc, stagger=stagger)

    passed = failed = errored = 0
    for p in paths:
        try:
            doc = json.loads(Path(p).read_text(encoding="utf-8"))
            v = doc.get("verdict", {})
            if doc.get("harness", {}).get("error") and not v.get("reached_determination"):
                errored += 1
            elif v.get("matches_expected"):
                passed += 1
            else:
                failed += 1
        except Exception:
            errored += 1
    print(f"\n=== {product}.{env}.{feed}: {len(paths)} result(s) · "
          f"PASS {passed} · FAIL {failed} · ERROR {errored} · out {out} ===", flush=True)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="cctqa run")
    parser.add_argument("product")
    parser.add_argument("env")
    parser.add_argument("feed")
    parser.add_argument("--n", type=int, default=None, help="run only the first N use-cases")
    parser.add_argument("--conc", type=int, default=14, help="max concurrent sessions")
    parser.add_argument("--otp-conc", type=int, default=6, help="OTP-phase gate width")
    parser.add_argument("--stagger", type=float, default=2.0, help="seconds between session starts")
    parser.add_argument("--out", dest="out_dir", default=None, help="output dir (default: runs/<cell>/<ts>)")
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return int(exc.code) if exc.code is not None else 2
    return run_run(args.product, args.env, args.feed, args.n, args.conc, args.out_dir,
                   otp_conc=args.otp_conc, stagger=args.stagger)


if __name__ == "__main__":
    import sys
    sys.exit(main())
