"""Tests for the checkpoint wiring: dob check, DDS checks, family auto-pick, sidecar -> seed block."""
import json

from catalog.model import SeedSpec, UseCase
from runner.build import _seed_from_sidecar
from seed.cli import _family_for
from seed.source import FakeSource
from seed.verify import verify_case


def _uc(amount=None, regime="APPR", verdict="ELIGIBLE", system_code=""):
    return UseCase(id="ZZ", regime=regime, verdict=verdict, system_code=system_code, title="",
                   third_party=False, checkpoint_vector=[], customer_intent="", expected_transcript=[],
                   seed=SeedSpec(pnr="ZZ", pnr_id="ZZ-2026-07-09", passenger="MARA OKONKWO",
                                 amount=amount), seed_pending=False)


def test_family_for():
    assert _family_for(_uc({"currency": "CAD", "value": 400}), "X") == "APPR_CAD_400"
    assert _family_for(_uc({"currency": "CAD", "value": 700}), "X") == "APPR_CAD_700"
    assert _family_for(_uc({"currency": "CAD", "value": 1000}), "X") == "APPR_CAD_1000"
    assert _family_for(_uc({"currency": "EUR", "value": 250}, regime="EU"), "DEF") == "DEF"


def test_dob_and_dds_checks():
    src = FakeSource({"ZZ": {"trip": {"last_name": "OKONKWO", "status": "ACTIVE"},
                            "eds": {"emails": ["lahiru@m.com"]}, "tickets": ["014900"],
                            "passengers": ["MARA OKONKWO"], "dob": "1986-04-23"}})
    dds = {"eligible": True, "amount": 400, "system_code": "FD-APPR-EL-400"}
    rep = verify_case(_uc({"currency": "CAD", "value": 400}), src, expected_email="lahiru@m.com",
                      areas=["dob", "dds_endpoint_systemcode_match", "dds_amount_match", "ticket"], dds=dds)
    by = {c.area: c for c in rep.checks}
    assert by["dob"].ok is True
    assert by["dds_endpoint_systemcode_match"].ok is True
    assert by["dds_amount_match"].ok is True
    assert by["ticket"].ok is True


def test_seed_from_sidecar(tmp_path):
    (tmp_path / "ZZ.checkpoints.json").write_text(json.dumps([
        {"area": "trip_active", "pass": True, "detail": "x"},
        {"area": "ticket", "pass": False, "detail": "y"},
        {"area": "dob", "pass": None, "detail": "skip"}]), encoding="utf-8")
    block = _seed_from_sidecar(str(tmp_path), _uc())
    assert block["verified"] is False  # a FAIL present
    assert {c["area"]: c["pass"] for c in block["checkpoints"]} == {"trip_active": True, "ticket": False}
    assert _seed_from_sidecar(str(tmp_path), _uc(system_code="MISSING")) is not None
    # no sidecar -> None (caller falls back)
    assert _seed_from_sidecar(str(tmp_path / "nope"), _uc()) is None


def test_sidecar_is_found_when_named_by_locator(tmp_path):
    """seed/cli writes `<locator>.checkpoints.json`; the runner keys cases by id. Looking only by
    id found nothing, so seeded runs reported 0/0 checkpoints even though the vector existed."""
    import json
    from catalog.model import SeedSpec, UseCase
    from runner.build import _seed_from_sidecar

    (tmp_path / "SWC77A.checkpoints.json").write_text(json.dumps(
        [{"area": "trip_active", "pass": True, "detail": "trip.status=ACTIVE"}]), encoding="utf-8")
    uc = UseCase(id="FD-SIT-001", regime="APPR", verdict="Eligible", system_code="FD-APPR-EL-400",
                 title="t", third_party=False, checkpoint_vector=[], customer_intent="",
                 expected_transcript=[],
                 seed=SeedSpec(pnr="SWC77A", pnr_id="SWC77A-2026-07-14", passenger="A B"),
                 seed_pending=False, content_hash="h")
    seed = _seed_from_sidecar(str(tmp_path), uc)
    assert seed is not None and len(seed["checkpoints"]) == 1
