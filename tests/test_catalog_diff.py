import dataclasses

from catalog.diff import content_hash, diff
from catalog.model import Checkpoint, CheckpointRef, SeedSpec, UseCase, Catalog
from catalog.parser import parse_gap_doc

from tests.conftest import GAP_MIN, GAP_MIN_V2


def _uc(case_id, **overrides):
    defaults = dict(
        id=case_id, regime="APPR", verdict="Eligible", system_code="SoC-APPR-EL-01",
        title="a title", third_party=False,
        checkpoint_vector=[CheckpointRef(id="GLOB-01", state="asserted")],
        customer_intent="intent", expected_transcript=[{"role": "bot", "text": "hi there"}],
        seed=SeedSpec(pnr="ABC123"), seed_pending=False, content_hash="",
    )
    defaults.update(overrides)
    uc = UseCase(**defaults)
    return dataclasses.replace(uc, content_hash=content_hash(uc))


def _catalog(cases, checkpoints=None, feed_id="gapmin", uncovered=None):
    return Catalog(feed_id=feed_id, checkpoints=checkpoints or [], cases=cases,
                   uncovered=uncovered or [])


# ---------------------------------------------------------------------------
# content_hash()
# ---------------------------------------------------------------------------

def test_content_hash_stable_for_identical_case():
    uc1 = _uc("A")
    uc2 = _uc("A")
    assert content_hash(uc1) == content_hash(uc2)


def test_content_hash_changes_when_seed_differs():
    uc1 = _uc("A", seed=SeedSpec(pnr="ABC123"))
    uc2 = _uc("A", seed=SeedSpec(pnr="ZZZ999"))
    assert content_hash(uc1) != content_hash(uc2)


def test_content_hash_ignores_transcript_whitespace():
    uc1 = _uc("A", expected_transcript=[{"role": "bot", "text": "hi   there"}])
    uc2 = _uc("A", expected_transcript=[{"role": "bot", "text": "hi\n  there  "}])
    assert content_hash(uc1) == content_hash(uc2)


def test_content_hash_changes_when_transcript_text_differs():
    uc1 = _uc("A", expected_transcript=[{"role": "bot", "text": "hi there"}])
    uc2 = _uc("A", expected_transcript=[{"role": "bot", "text": "bye there"}])
    assert content_hash(uc1) != content_hash(uc2)


def test_content_hash_ignores_title_and_third_party():
    uc1 = _uc("A", title="Title One", third_party=False)
    uc2 = _uc("A", title="A Completely Different Title", third_party=True)
    assert content_hash(uc1) == content_hash(uc2)


def test_content_hash_changes_when_checkpoint_vector_differs():
    uc1 = _uc("A", checkpoint_vector=[CheckpointRef(id="GLOB-01", state="asserted")])
    uc2 = _uc("A", checkpoint_vector=[CheckpointRef(id="GLOB-01", state="missing")])
    assert content_hash(uc1) != content_hash(uc2)


def test_content_hash_checkpoint_vector_order_independent():
    uc1 = _uc("A", checkpoint_vector=[CheckpointRef(id="GLOB-01", state="asserted"),
                                       CheckpointRef(id="GLOB-02", state="missing")])
    uc2 = _uc("A", checkpoint_vector=[CheckpointRef(id="GLOB-02", state="missing"),
                                       CheckpointRef(id="GLOB-01", state="asserted")])
    assert content_hash(uc1) == content_hash(uc2)


# ---------------------------------------------------------------------------
# diff() — unit level, constructed catalogs
# ---------------------------------------------------------------------------

def test_diff_added_and_removed():
    old = _catalog([_uc("A"), _uc("B")])
    new = _catalog([_uc("A"), _uc("C")])
    cs = diff(old, new)
    assert cs.added == ["C"]
    assert cs.removed == ["B"]
    assert cs.unchanged == ["A"]


def test_diff_unchanged_when_hash_equal():
    old = _catalog([_uc("A")])
    new = _catalog([_uc("A")])
    cs = diff(old, new)
    assert cs.unchanged == ["A"]
    assert cs.data_changed == []
    assert cs.expected_changed == []
    assert cs.checkpoint_changed == []


def test_diff_data_changed_when_seed_differs():
    old = _catalog([_uc("A", seed=SeedSpec(pnr="ABC123"))])
    new = _catalog([_uc("A", seed=SeedSpec(pnr="ZZZ999"))])
    cs = diff(old, new)
    assert cs.data_changed == ["A"]
    assert cs.expected_changed == []
    assert cs.checkpoint_changed == []
    assert cs.unchanged == []


def test_diff_checkpoint_changed_when_vector_differs():
    old = _catalog([_uc("A", checkpoint_vector=[CheckpointRef(id="GLOB-01", state="asserted")])])
    new = _catalog([_uc("A", checkpoint_vector=[CheckpointRef(id="GLOB-01", state="missing")])])
    cs = diff(old, new)
    assert cs.checkpoint_changed == ["A"]
    assert cs.data_changed == []
    assert cs.expected_changed == []


def test_diff_expected_changed_when_verdict_differs():
    old = _catalog([_uc("A", verdict="Eligible")])
    new = _catalog([_uc("A", verdict="Not Eligible")])
    cs = diff(old, new)
    assert cs.expected_changed == ["A"]
    assert cs.data_changed == []
    assert cs.checkpoint_changed == []


def test_diff_expected_changed_when_transcript_text_differs():
    old = _catalog([_uc("A", expected_transcript=[{"role": "bot", "text": "hi"}])])
    new = _catalog([_uc("A", expected_transcript=[{"role": "bot", "text": "bye"}])])
    cs = diff(old, new)
    assert cs.expected_changed == ["A"]


def test_diff_priority_data_changed_wins_over_others():
    old = _uc("A", seed=SeedSpec(pnr="ABC123"), verdict="Eligible",
              checkpoint_vector=[CheckpointRef(id="GLOB-01", state="asserted")])
    new = _uc("A", seed=SeedSpec(pnr="ZZZ999"), verdict="Not Eligible",
              checkpoint_vector=[CheckpointRef(id="GLOB-01", state="missing")])
    cs = diff(_catalog([old]), _catalog([new]))
    assert cs.data_changed == ["A"]
    assert cs.expected_changed == []
    assert cs.checkpoint_changed == []


def test_diff_priority_expected_changed_wins_over_checkpoint():
    old = _uc("A", verdict="Eligible",
              checkpoint_vector=[CheckpointRef(id="GLOB-01", state="asserted")])
    new = _uc("A", verdict="Not Eligible",
              checkpoint_vector=[CheckpointRef(id="GLOB-01", state="missing")])
    cs = diff(_catalog([old]), _catalog([new]))
    assert cs.expected_changed == ["A"]
    assert cs.checkpoint_changed == []
    assert cs.data_changed == []


def test_diff_spine_checkpoint_added_flags_referencing_cases():
    # Case content is byte-identical (same hash) but the spine gains a checkpoint that the
    # case's own vector references -> the case must still be flagged for re-verification.
    case = _uc("A", checkpoint_vector=[CheckpointRef(id="GLOB-05", state="na")])
    old = _catalog([case], checkpoints=[Checkpoint(id="GLOB-01", label="x", kind="core", assert_count=1)])
    new = _catalog([case], checkpoints=[
        Checkpoint(id="GLOB-01", label="x", kind="core", assert_count=1),
        Checkpoint(id="GLOB-05", label="new step", kind="branch", assert_count=0),
    ])
    cs = diff(old, new)
    assert "A" in cs.checkpoint_changed
    assert "A" not in cs.unchanged


def test_diff_spine_checkpoint_removed_flags_referencing_cases():
    case = _uc("A", checkpoint_vector=[CheckpointRef(id="GLOB-05", state="na")])
    old = _catalog([case], checkpoints=[
        Checkpoint(id="GLOB-01", label="x", kind="core", assert_count=1),
        Checkpoint(id="GLOB-05", label="old step", kind="branch", assert_count=0),
    ])
    new = _catalog([case], checkpoints=[Checkpoint(id="GLOB-01", label="x", kind="core", assert_count=1)])
    cs = diff(old, new)
    assert "A" in cs.checkpoint_changed
    assert "A" not in cs.unchanged


def test_diff_spine_change_does_not_affect_unrelated_cases():
    case = _uc("A", checkpoint_vector=[CheckpointRef(id="GLOB-01", state="asserted")])
    old = _catalog([case], checkpoints=[Checkpoint(id="GLOB-01", label="x", kind="core", assert_count=1)])
    new = _catalog([case], checkpoints=[
        Checkpoint(id="GLOB-01", label="x", kind="core", assert_count=1),
        Checkpoint(id="GLOB-09", label="unrelated new step", kind="branch", assert_count=0),
    ])
    cs = diff(old, new)
    assert cs.unchanged == ["A"]
    assert cs.checkpoint_changed == []


# ---------------------------------------------------------------------------
# diff() — integration level, real fixture HTML via parse_gap_doc
# ---------------------------------------------------------------------------

def test_diff_gap_min_vs_v2_fixture(feed):
    old = parse_gap_doc(str(GAP_MIN), feed)
    new = parse_gap_doc(str(GAP_MIN_V2), feed)
    cs = diff(old, new)

    assert cs.added == ["SOC_UAT-005"]
    assert cs.removed == []
    assert cs.data_changed == ["SOC_UAT-002"]
    assert cs.expected_changed == ["SOC_UAT-003"]
    assert cs.checkpoint_changed == []
    assert set(cs.unchanged) == {"SOC_UAT-001", "SOC_UAT-004"}

    summary = cs.summary()
    assert "1 added" in summary
    assert "1 data-changed" in summary
    assert "1 expected-changed" in summary
    assert "2 unchanged" in summary

    assert set(cs.to_seed()) == {"SOC_UAT-005", "SOC_UAT-002"}
    assert set(cs.to_run()) == {"SOC_UAT-005", "SOC_UAT-002", "SOC_UAT-003"}


def test_diff_identical_doc_is_all_unchanged(feed):
    catalog = parse_gap_doc(str(GAP_MIN), feed)
    cs = diff(catalog, catalog)
    assert cs.added == []
    assert cs.removed == []
    assert cs.data_changed == []
    assert cs.expected_changed == []
    assert cs.checkpoint_changed == []
    assert set(cs.unchanged) == {c.id for c in catalog.cases}


def test_diff_whitespace_only_edit_is_unchanged(feed, tmp_path):
    original = GAP_MIN.read_text(encoding="utf-8")
    # Cosmetically reflow one case's intent bubble — extra internal whitespace/newlines only.
    reflowed = original.replace(
        "<div class=\"intbub\">👤 My flight was delayed and I want reimbursement for my hotel.</div>",
        "<div class=\"intbub\">👤   My flight   was delayed and\n  I want reimbursement for my hotel.  </div>",
    )
    assert reflowed != original
    edited_path = tmp_path / "gap_min_whitespace.html"
    edited_path.write_text(reflowed, encoding="utf-8")

    old = parse_gap_doc(str(GAP_MIN), feed)
    new = parse_gap_doc(str(edited_path), feed)
    cs = diff(old, new)

    assert "SOC_UAT-001" in cs.unchanged
    assert cs.data_changed == []
    assert cs.expected_changed == []
    assert cs.checkpoint_changed == []
