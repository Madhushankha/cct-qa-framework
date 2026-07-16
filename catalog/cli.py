"""`cctqa catalog <feed> [--diff <old_gap_doc.html>]` — parse a feed's gap doc and print counts,
or diff it against an older gap-doc snapshot and print the ChangeSet summary + per-bucket ids.
"""
from __future__ import annotations

import argparse
from collections import Counter

from core.descriptors import Feed
from core.registry import load_feed

from catalog.diff import diff
from catalog.model import Catalog
from catalog.parser import join_dataset, load_catalog, parse_gap_doc

_BUCKETS = ("added", "removed", "data_changed", "checkpoint_changed", "expected_changed", "unchanged")


def _print_counts(catalog: Catalog) -> None:
    print(f"feed: {catalog.feed_id}")
    print(f"checkpoints: {len(catalog.checkpoints)}")
    print(f"cases: {len(catalog.cases)}")

    by_verdict = Counter(c.verdict for c in catalog.cases)
    for verdict, n in sorted(by_verdict.items()):
        print(f"  verdict {verdict}: {n}")

    by_regime = Counter(c.regime for c in catalog.cases)
    for regime, n in sorted(by_regime.items()):
        print(f"  regime {regime}: {n}")

    third_party_n = sum(1 for c in catalog.cases if c.third_party)
    print(f"third_party: {third_party_n}")

    print(f"uncovered: {len(catalog.uncovered)}")
    if catalog.uncovered:
        print("  " + ", ".join(catalog.uncovered))


def run_catalog(feed: Feed, diff_doc: str | None) -> int:
    new_catalog = load_catalog(feed)

    if diff_doc:
        old_catalog = parse_gap_doc(diff_doc, feed)
        if feed.dataset:
            old_catalog = join_dataset(old_catalog, feed.dataset, feed)
        change_set = diff(old_catalog, new_catalog)
        print(change_set.summary())
        for bucket in _BUCKETS:
            ids = getattr(change_set, bucket)
            label = bucket.replace("_", "-")
            print(f"{label}: {', '.join(ids) if ids else '(none)'}")
        return 0

    _print_counts(new_catalog)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="cctqa catalog")
    parser.add_argument("feed")
    parser.add_argument("--diff", dest="diff_doc", default=None)
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return int(exc.code) if exc.code is not None else 2
    feed = load_feed(args.feed)
    return run_catalog(feed, args.diff_doc)


if __name__ == "__main__":
    import sys
    sys.exit(main())
