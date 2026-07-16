"""join_dataset must bind dataset rows to EVERY matching case, not just seed_pending ones."""
from pathlib import Path

from catalog.parser import join_dataset, parse_gap_doc
from core.registry import load_feed

FEED = load_feed("fd")


def test_join_binds_all_cases():
    cat = parse_gap_doc(FEED.gap_doc, FEED)
    joined = join_dataset(cat, FEED.dataset, FEED)
    bound = [c for c in joined.cases if c.seed.pnr and c.seed.passenger]
    assert len(bound) == len(joined.cases) == 239  # every case gets dataset data
    assert not any(c.seed_pending for c in bound)


def test_join_preserves_case_identity():
    cat = parse_gap_doc(FEED.gap_doc, FEED)
    joined = join_dataset(cat, FEED.dataset, FEED)
    tc1 = joined.by_id("FD_TC_001")
    assert tc1 is not None and tc1.seed.pnr  # e.g. "MHGQHS" in v15
    assert tc1.seed.system_code.startswith("FD-")
