"""Thin CLI: `cctqa list` and `cctqa validate`."""
from __future__ import annotations

import argparse
import sys

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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="cctqa")
    sub = parser.add_subparsers(dest="cmd")
    sub.add_parser("list")
    sub.add_parser("validate")
    catalog_parser = sub.add_parser("catalog")
    # Forward everything after `catalog` as-is to catalog.cli.main (P1), which owns its own
    # <feed> / --diff argument parsing — avoids duplicating that parser here.
    catalog_parser.add_argument("catalog_args", nargs=argparse.REMAINDER)
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:  # argparse hard-exits on an invalid/unknown command
        return int(exc.code) if exc.code is not None else 2
    if args.cmd == "list":
        return _cmd_list()
    if args.cmd == "validate":
        return _cmd_validate()
    if args.cmd == "catalog":
        from catalog.cli import main as catalog_main
        return catalog_main(args.catalog_args)
    parser.print_usage()
    return 2


if __name__ == "__main__":
    sys.exit(main())
