"""`cctqa run <product> <env> <feed> [--n N] [--conc C] [--out DIR]` — resolve the RunContext, load the
feed catalog, select N use-cases, drive them through the async batched runner, and print a summary."""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def run_run(product: str, env: str, feed: str, n: int | None, conc: int,
            out_dir: str | None, otp_conc: int = 6, stagger: float = 2.0,
            fixtures_dir: str | None = None, only: list[str] | None = None) -> int:
    from core.registry import resolve

    from runner.orchestrator import run_batch

    ctx = resolve(product, env, feed)
    # Catalog source: an explicit fixtures dir (the seeded corpus, e.g. INT clones) takes precedence
    # over the feed's gap-doc/dataset. `--fixtures` defaults to the env's seed_targets.fixtures_dir.
    fixtures_dir = fixtures_dir or (ctx.env.seed_targets or {}).get("fixtures_dir") if only else fixtures_dir
    if fixtures_dir:
        from catalog.fixtures import load_fixture_catalog
        catalog = load_fixture_catalog(fixtures_dir, feed_id=feed, only=only)
    else:
        from catalog.parser import load_catalog
        catalog = load_catalog(ctx.feed)
    cases = catalog.cases
    if not cases:
        print(f"no use-cases in feed '{feed}' — nothing to run")
        return 1
    if n is not None:
        cases = cases[:n]

    from core.runpaths import new_run_dir
    out = out_dir or str(new_run_dir(product, env, feed))  # results/<date>/<env>_<product>_<feed>_<time>/

    print(f"[run] {product}.{env}.{feed}: {len(cases)} case(s), conc={conc}, otp-conc={otp_conc} -> {out}",
          flush=True)
    paths = run_batch(ctx, cases, out, conc=conc, otp_conc=otp_conc, stagger=stagger,
                      checkpoints_dir=fixtures_dir)

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
    parser.add_argument("--fixtures", dest="fixtures_dir", default=None,
                        help="build the catalog from a fixtures dir (seeded corpus) instead of the gap-doc")
    parser.add_argument("--only", nargs="*", default=None,
                        help="restrict to these case ids/locators (implies --fixtures from the env)")
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return int(exc.code) if exc.code is not None else 2
    return run_run(args.product, args.env, args.feed, args.n, args.conc, args.out_dir,
                   otp_conc=args.otp_conc, stagger=args.stagger,
                   fixtures_dir=args.fixtures_dir, only=args.only)


if __name__ == "__main__":
    import sys
    sys.exit(main())
