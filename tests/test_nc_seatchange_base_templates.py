"""Structural tests for the nc/seatchange pnr+ticket base seed templates (no FDM/EMD/DDS) and their
integration with seed.render.render_case + seed.feeds.prelude's CREATE-prelude mechanism."""
import json
from pathlib import Path

import yaml

from catalog.model import SeedSpec, UseCase
from seed.feeds import prelude
from seed.render import render_case

NC_BASE = Path("data/seed-templates/nc/base")
SC_BASE = Path("data/seed-templates/seatchange/base")


def _load(base: Path, name: str) -> dict:
    return json.loads((base / name).read_text(encoding="utf-8"))


def _case(pnr, passenger, route="YYZ-YVR"):
    return UseCase(id="X_TC001", regime="", verdict="", system_code="", title="",
                   third_party=False, checkpoint_vector=[], customer_intent="",
                   expected_transcript=[],
                   seed=SeedSpec(pnr=pnr, passenger=passenger, route=route, amount=None),
                   seed_pending=False)


# --- shape: pnr + ticket ONLY, no FDM/EMD/DDS -------------------------------------------------

def test_nc_base_has_no_fdm_or_emd_files():
    names = {p.name for p in NC_BASE.iterdir()}
    assert names == {"01_pnr.json", "02_ticket.json", "meta.json"}


def test_seatchange_base_has_no_fdm_or_emd_files():
    names = {p.name for p in SC_BASE.iterdir()}
    assert names == {"01_pnr.json", "02_ticket.json", "meta.json"}


def test_both_bases_are_valid_json():
    for base in (NC_BASE, SC_BASE):
        for name in ("01_pnr.json", "02_ticket.json", "meta.json"):
            json.loads((base / name).read_text(encoding="utf-8"))  # raises on invalid JSON


# --- nc: name-change parent identity ------------------------------------------------------------

def test_nc_base_carries_single_traveler_and_ticket():
    pnr = _load(NC_BASE, "01_pnr.json")
    travelers = pnr["processedPnr"]["travelers"]
    assert len(travelers) == 1
    assert travelers[0]["names"][0]["firstName"] and travelers[0]["names"][0]["lastName"]
    assert "ticketingReferences" in pnr["processedPnr"]


def test_nc_meta_prelude_block_matches_base_pnr_path():
    meta = _load(NC_BASE, "meta.json")
    prelude_block = meta["prelude"]
    revert = prelude_block["revert_fields"]
    assert "processedPnr.travelers[0].names[0].firstName" in revert
    assert "processedPnr.travelers[0].names[0].lastName" in revert
    assert prelude_block["wait_for"]["table"] == "passenger"
    assert meta["change_kind"] == "name"


# --- seatchange: seating parent identity ---------------------------------------------------------

def test_seatchange_base_carries_seating_block():
    pnr = _load(SC_BASE, "01_pnr.json")
    products = pnr["processedPnr"]["products"]
    assert len(products) == 1
    seating = products[0]["seating"]
    assert seating["seats"][0]["number"] == "14C"


def test_seatchange_meta_prelude_block_matches_base_pnr_path():
    meta = _load(SC_BASE, "meta.json")
    prelude_block = meta["prelude"]
    assert prelude_block["revert_fields"]["processedPnr.products[0].seating.seats[0].number"] == "14C"
    assert prelude_block["wait_for"]["table"] == "trip_details"
    assert meta["change_kind"] == "seat"


# --- manifest scaffolds parse and point at the right base_dir -----------------------------------

def test_nc_manifest_parses_and_points_at_base():
    m = yaml.safe_load((Path("data/seed-templates/nc/manifest.yaml")).read_text(encoding="utf-8"))
    assert m["feed"] == "nc"
    assert m["base_dir"] == "data/seed-templates/nc/base"


def test_seatchange_manifest_parses_and_points_at_base():
    m = yaml.safe_load((Path("data/seed-templates/seatchange/manifest.yaml")).read_text(encoding="utf-8"))
    assert m["feed"] == "seatchange"
    assert m["base_dir"] == "data/seed-templates/seatchange/base"


# --- integration: render_case works against these bases, and the rendered body still needs (and
#     can go through) a CREATE-prelude ------------------------------------------------------------

def test_render_case_against_nc_base_then_prelude_reverts_rendered_name(tmp_path):
    uc = _case(pnr="ZZNCAA", passenger="JOHN SMITH")
    dst = render_case(NC_BASE, tmp_path, uc, contact_email="qa@example.com",
                      flight_date="2026-07-10", index=1)
    pnr = json.loads((dst / "01_pnr.json").read_text(encoding="utf-8"))
    assert pnr["processedPnr"]["travelers"][0]["names"][0] == {"firstName": "JOHN", "lastName": "SMITH"}

    # simulate the real name-change UPDATE event this rendered body would carry, then build the
    # CREATE-prelude from it.
    update_payload = dict(pnr)
    update_payload["events"] = {"events": [
        {"origin": "COMPARISON", "eventType": "UPDATED", "currentPath": "/travelers/0/names/0/firstName"}]}
    assert prelude.needs_create_prelude(update_payload) is True

    meta = json.loads((dst / "meta.json").read_text(encoding="utf-8"))
    create_payload = prelude.build_create_payload(update_payload, meta["prelude"]["revert_fields"])
    reverted = create_payload["processedPnr"]["travelers"][0]["names"][0]
    assert reverted["firstName"] == "JOAO" and reverted["lastName"] == "MAIA"
    # the rendered UPDATE body's own to-name is untouched by building the CREATE
    assert update_payload["processedPnr"]["travelers"][0]["names"][0]["firstName"] == "JOHN"


def test_render_case_against_seatchange_base_then_prelude_reverts_rendered_seat(tmp_path):
    uc = _case(pnr="ZZSCAA", passenger="JANE DOE")
    dst = render_case(SC_BASE, tmp_path, uc, contact_email="qa@example.com",
                      flight_date="2026-07-10", index=1)
    pnr = json.loads((dst / "01_pnr.json").read_text(encoding="utf-8"))
    seating = pnr["processedPnr"]["products"][0]["seating"]
    assert seating["seats"][0]["number"] == "14C"  # base's own pre-change default carries through

    update_payload = dict(pnr)
    update_payload["processedPnr"]["products"][0]["seating"]["seats"][0]["number"] = "22A"  # to-seat
    update_payload["events"] = {"events": [
        {"origin": "COMPARISON", "eventType": "UPDATED", "currentPath": "/products/0/seating"}]}
    assert prelude.needs_create_prelude(update_payload) is True

    meta = json.loads((dst / "meta.json").read_text(encoding="utf-8"))
    create_payload = prelude.build_create_payload(update_payload, meta["prelude"]["revert_fields"])
    assert create_payload["processedPnr"]["products"][0]["seating"]["seats"][0]["number"] == "14C"
    # the real UPDATE's to-seat is untouched by building the CREATE
    assert update_payload["processedPnr"]["products"][0]["seating"]["seats"][0]["number"] == "22A"
