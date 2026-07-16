import dataclasses

import pytest

from catalog.model import Checkpoint, SeedSpec, CheckpointRef, UseCase, Catalog, ChangeSet


def _uc(case_id, **overrides):
    defaults = dict(
        id=case_id, regime="APPR", verdict="Eligible", system_code="SoC-APPR-EL-01",
        title="title", third_party=False,
        checkpoint_vector=[CheckpointRef(id="GLOB-01", state="asserted")],
        customer_intent="intent", expected_transcript=[{"role": "bot", "text": "hi"}],
        seed=SeedSpec(), seed_pending=True, content_hash="",
    )
    defaults.update(overrides)
    return UseCase(**defaults)


def test_checkpoint_is_frozen():
    cp = Checkpoint(id="GLOB-01", label="Conversation Entry", kind="core", assert_count=81)
    assert cp.id == "GLOB-01"
    assert cp.kind == "core"
    with pytest.raises(dataclasses.FrozenInstanceError):
        cp.id = "GLOB-02"


def test_seedspec_defaults_are_empty():
    seed = SeedSpec()
    assert seed.pnr == ""
    assert seed.amount is None
    assert seed.extras == {}


def test_seedspec_amount_shape():
    seed = SeedSpec(pnr="ABC123", amount={"currency": "CAD", "value": 45.0})
    assert seed.amount == {"currency": "CAD", "value": 45.0}


def test_checkpointref_state_values():
    ref = CheckpointRef(id="GLOB-01", state="asserted")
    assert ref.state == "asserted"


def test_usecase_construction():
    uc = _uc("SOC_UAT-001")
    assert uc.id == "SOC_UAT-001"
    assert uc.seed_pending is True
    assert uc.content_hash == ""


def test_catalog_by_id_found():
    cases = [_uc("SOC_UAT-001"), _uc("SOC_UAT-002")]
    catalog = Catalog(feed_id="soc", checkpoints=[], cases=cases, uncovered=[])
    found = catalog.by_id("SOC_UAT-002")
    assert found is not None
    assert found.id == "SOC_UAT-002"


def test_catalog_by_id_missing_returns_none():
    catalog = Catalog(feed_id="soc", checkpoints=[], cases=[_uc("SOC_UAT-001")], uncovered=[])
    assert catalog.by_id("NOPE") is None


def test_changeset_summary_lists_nonzero_buckets_only():
    cs = ChangeSet(added=["a", "b", "c"], removed=[], data_changed=["d", "e"],
                    checkpoint_changed=[], expected_changed=[], unchanged=["u"] * 194)
    summary = cs.summary()
    assert "3 added" in summary
    assert "2 data-changed" in summary
    assert "194 unchanged" in summary
    assert "removed" not in summary
    assert "checkpoint-changed" not in summary


def test_changeset_summary_no_changes():
    cs = ChangeSet(added=[], removed=[], data_changed=[], checkpoint_changed=[],
                    expected_changed=[], unchanged=[])
    assert "no changes" in cs.summary().lower()


def test_changeset_to_seed_is_added_union_data_changed():
    cs = ChangeSet(added=["a"], removed=["r"], data_changed=["d"],
                    checkpoint_changed=["c"], expected_changed=["e"], unchanged=["u"])
    assert set(cs.to_seed()) == {"a", "d"}


def test_changeset_to_run_is_added_union_data_union_expected():
    cs = ChangeSet(added=["a"], removed=["r"], data_changed=["d"],
                    checkpoint_changed=["c"], expected_changed=["e"], unchanged=["u"])
    assert set(cs.to_run()) == {"a", "d", "e"}
