"""`cctqa dashboard [results_root] [--out FILE]` — build the browsable results index."""
from __future__ import annotations

import argparse


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="cctqa dashboard")
    p.add_argument("results_root", nargs="?", default="results")
    p.add_argument("--out", default=None, help="output HTML (default: <results_root>/index.html)")
    try:
        args = p.parse_args(argv)
    except SystemExit as exc:
        return int(exc.code) if exc.code is not None else 2
    from ui.dashboard import build_dashboard

    out = build_dashboard(args.results_root, args.out)
    print(f"wrote dashboard -> {out}")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
