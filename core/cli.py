"""Thin CLI: `cctqa list` and `cctqa validate`."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from core.registry import list_feeds, list_products, list_envs, load_product, RegistryError
from core.validate import validate_all


def _cmd_list() -> int:
    print("feeds:   ", ", ".join(list_feeds()))
    print("products:", ", ".join(list_products()))
    print("envs:    ", ", ".join(list_envs()))
    print("valid cells (product x env x feed):")
    for pid in list_products():
        try:
            p = load_product(pid)
        except RegistryError:
            continue
        for env in p.defaults.get("envs", []):
            for feed in p.defaults.get("feeds", []):
                print(f"  {pid}.{env}.{feed}")
    return 0


def _cmd_validate() -> int:
    errors = validate_all()
    if not errors:
        print("OK — registry validates clean")
        return 0
    print(f"{len(errors)} error(s):")
    for e in errors:
        print(f"  - {e}")
    return 1


def _cmd_evidence(run_dir: str, out_dir: str | None) -> int:
    from evidence.build import build_evidence

    resolved_out = out_dir or str(Path(run_dir) / "evidence")
    build_evidence(run_dir, resolved_out)
    print(f"wrote evidence to {resolved_out}")
    return 0


def _cmd_metrics(run_dir: str, out_dir: str | None) -> int:
    from metrics.run import build_metrics

    resolved_out = out_dir or str(Path(run_dir) / "metrics")
    build_metrics(run_dir, resolved_out)
    print(f"wrote metrics to {resolved_out}")
    return 0


def _cmd_analyze(run_dir: str, prev_dir: str | None, out_file: str | None) -> int:
    import json

    from analysis.build import analyze

    doc = analyze(run_dir, prev_dir=prev_dir)
    resolved_out = out_file or str(Path(run_dir) / "analysis" / "analysis.json")
    out_path = Path(resolved_out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(doc, indent=2, sort_keys=True), encoding="utf-8")
    print(f"wrote analysis to {resolved_out}")
    return 0


def _cmd_jira(run_dir: str, file_flag: bool, limit: int | None, out_file: str | None) -> int:
    from jira.cli import run_jira

    return run_jira(run_dir, file=file_flag, limit=limit, out_file=out_file)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="cctqa")
    sub = parser.add_subparsers(dest="cmd")
    sub.add_parser("list")
    sub.add_parser("validate")
    catalog_parser = sub.add_parser("catalog")
    # Forward everything after `catalog` as-is to catalog.cli.main (P1), which owns its own
    # <feed> / --diff argument parsing — avoids duplicating that parser here.
    catalog_parser.add_argument("catalog_args", nargs=argparse.REMAINDER)
    evidence_parser = sub.add_parser("evidence")
    evidence_parser.add_argument("run_dir")
    evidence_parser.add_argument("--out", dest="out_dir", default=None,
                                  help="output dir (default: <run_dir>/evidence)")
    metrics_parser = sub.add_parser("metrics")
    metrics_parser.add_argument("run_dir")
    metrics_parser.add_argument("--out", dest="out_dir", default=None,
                                 help="output dir (default: <run_dir>/metrics)")
    analyze_parser = sub.add_parser("analyze")
    analyze_parser.add_argument("run_dir")
    analyze_parser.add_argument("--prev", dest="prev_dir", default=None,
                                 help="previous run dir to diff against (default: no diff)")
    analyze_parser.add_argument("--out", dest="out_file", default=None,
                                 help="output JSON file (default: <run_dir>/analysis/analysis.json)")
    jira_parser = sub.add_parser("jira")
    jira_parser.add_argument("run_dir")
    jira_parser.add_argument("--file", action="store_true",
                              help="actually file defects in JIRA (default: dry-run, files nothing)")
    jira_parser.add_argument("--limit", type=int, default=None,
                              help="cap how many defects to file (dry-run also caps the plan)")
    jira_parser.add_argument("--out", dest="out_file", default=None,
                              help="review HTML output path (default: <run_dir>/jira/review.html)")
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:  # argparse hard-exits on an invalid/unknown command
        return int(exc.code) if exc.code is not None else 2
    try:
        if args.cmd == "list":
            return _cmd_list()
        if args.cmd == "validate":
            return _cmd_validate()
        if args.cmd == "catalog":
            from catalog.cli import main as catalog_main
            return catalog_main(args.catalog_args)
        if args.cmd == "evidence":
            return _cmd_evidence(args.run_dir, args.out_dir)
        if args.cmd == "metrics":
            return _cmd_metrics(args.run_dir, args.out_dir)
        if args.cmd == "analyze":
            return _cmd_analyze(args.run_dir, args.prev_dir, args.out_file)
        if args.cmd == "jira":
            return _cmd_jira(args.run_dir, args.file, args.limit, args.out_file)
        parser.print_usage()
        return 2
    except SystemExit as exc:  # a subcommand's own exit (e.g. no results found)
        if exc.code is None:
            return 1
        if isinstance(exc.code, int):
            return exc.code
        print(exc.code, file=sys.stderr)  # e.g. SystemExit("message") from build_metrics
        return 1


if __name__ == "__main__":
    sys.exit(main())
