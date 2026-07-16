"""Offline tests for seed/feeds/prelude.py (the NC/SeatChange CREATE-prelude port of contrail's
pnr_lifecycle.py). No boto3/psycopg2 — wait_for is exercised against seed.source.FakeSource."""
import json
import time
from pathlib import Path

import pytest

from seed.feeds import prelude
from seed.source import FakeSource

NC_BASE = Path("data/seed-templates/nc/base")
SC_BASE = Path("data/seed-templates/seatchange/base")


def _load(base: Path, name: str) -> dict:
    return json.loads((base / name).read_text(encoding="utf-8"))


def _updated_event(path: str) -> dict:
    return {
        "events": {"events": [{"origin": "COMPARISON", "eventType": "UPDATED", "currentPath": path}]},
        "processedPnr": {"id": "X"},
    }


def _created_event() -> dict:
    return {
        "events": {"events": [{"origin": "COMPARISON", "eventType": "CREATED", "currentPath": ""}]},
        "processedPnr": {"id": "X"},
    }


# --- needs_create_prelude ------------------------------------------------------------------------

def test_needs_prelude_true_for_name_change_update():
    payload = _updated_event("/travelers/0/names/0/firstName")
    assert prelude.needs_create_prelude(payload) is True


def test_needs_prelude_true_for_seating_update():
    payload = _updated_event("/products/0/seating")
    assert prelude.needs_create_prelude(payload) is True


def test_needs_prelude_false_when_root_create_present():
    """A root CREATE would let PNRCreationDetector ingest the PNR on its own -- no prelude needed
    even if a name-change UPDATE event also happens to be present in the same body."""
    payload = _updated_event("/travelers/0/names/0/firstName")
    payload["events"]["events"].append({"origin": "COMPARISON", "eventType": "CREATED", "currentPath": ""})
    assert prelude.needs_create_prelude(payload) is False


def test_needs_prelude_false_for_unrelated_path():
    payload = _updated_event("/contacts/0/email/address")
    assert prelude.needs_create_prelude(payload) is False


def test_needs_prelude_false_for_bare_create():
    assert prelude.needs_create_prelude(_created_event()) is False


def test_needs_prelude_false_on_malformed_events():
    assert prelude.needs_create_prelude({}) is False
    assert prelude.needs_create_prelude({"events": {}}) is False


# --- build_create_payload -------------------------------------------------------------------------

def test_build_create_payload_replaces_events_and_drops_previous_record():
    payload = _updated_event("/travelers/0/names/0/firstName")
    payload["previousRecord"] = {"processedPnr": {"travelers": [{"names": [{"firstName": "OLD"}]}]}}
    out = prelude.build_create_payload(payload, {})
    assert out["events"]["events"] == [
        {"origin": "COMPARISON", "eventType": "CREATED", "currentPath": ""}]
    assert "previousRecord" not in out


def test_build_create_payload_reverts_name_fields():
    pnr = _load(NC_BASE, "01_pnr.json")
    payload = dict(pnr)
    payload["events"] = {"events": [
        {"origin": "COMPARISON", "eventType": "UPDATED", "currentPath": "/travelers/0/names/0/firstName"}]}
    revert = {
        "processedPnr.travelers[0].names[0].firstName": "JOAO",
        "processedPnr.travelers[0].names[0].lastName": "MAIA",
    }
    out = prelude.build_create_payload(payload, revert)
    names = out["processedPnr"]["travelers"][0]["names"][0]
    assert names["firstName"] == "JOAO"
    assert names["lastName"] == "MAIA"
    # single root CREATE event
    assert out["events"]["events"] == [
        {"origin": "COMPARISON", "eventType": "CREATED", "currentPath": ""}]


def test_build_create_payload_reverts_seating_field():
    pnr = _load(SC_BASE, "01_pnr.json")
    payload = dict(pnr)
    payload["events"] = {"events": [
        {"origin": "COMPARISON", "eventType": "UPDATED", "currentPath": "/products/0/seating"}]}
    revert = {"processedPnr.products[0].seating.seats[0].number": "14C"}
    out = prelude.build_create_payload(payload, revert)
    assert out["processedPnr"]["products"][0]["seating"]["seats"][0]["number"] == "14C"


def test_build_create_payload_does_not_mutate_input():
    payload = _updated_event("/travelers/0/names/0/firstName")
    payload["processedPnr"] = {"travelers": [{"names": [{"firstName": "TO_NAME"}]}]}
    before = json.dumps(payload)
    prelude.build_create_payload(payload, {"processedPnr.travelers[0].names[0].firstName": "JOAO"})
    assert json.dumps(payload) == before  # original untouched


def test_build_create_payload_skips_unresolvable_paths_without_raising():
    payload = _updated_event("/travelers/0/names/0/firstName")
    out = prelude.build_create_payload(payload, {"processedPnr.doesNotExist[9].x": "y"})
    assert "processedPnr" not in out or "doesNotExist" not in out.get("processedPnr", {})


# --- wait_for --------------------------------------------------------------------------------------

def test_wait_for_passenger_returns_true_when_row_present():
    src = FakeSource({"ZZNCAA": {"passengers": ["JOHN SMITH"]}})
    assert prelude.wait_for(src, "passenger", "ZZNCAA-2026-07-10", timeout_seconds=1, poll_seconds=0.01) is True


def test_wait_for_passenger_times_out_when_absent():
    src = FakeSource({})
    start = time.time()
    ok = prelude.wait_for(src, "passenger", "ZZNCAA-2026-07-10", timeout_seconds=0.05, poll_seconds=0.01)
    assert ok is False
    assert time.time() - start < 2  # didn't hang past the timeout


def test_wait_for_trip_details_proxies_through_trip():
    src = FakeSource({"ZZSCAA": {"trip": {"last_name": "DOE", "status": "ACTIVE"}}})
    assert prelude.wait_for(src, "trip_details", "ZZSCAA-2026-07-10", timeout_seconds=1, poll_seconds=0.01) is True


def test_wait_for_unknown_table_raises():
    with pytest.raises(ValueError):
        prelude.wait_for(FakeSource({}), "nope", "ZZNCAA-2026-07-10", timeout_seconds=0.01, poll_seconds=0.01)


def test_wait_for_locator_truncates_composite_pnr_id():
    # only the leading 6 chars of a "<locator>-<date>" composite id are used to key the lookup.
    src = FakeSource({"ZZNCAA": {"passengers": ["JOHN SMITH"]}})
    assert prelude.wait_for(src, "passenger", "ZZNCAA-2026-07-10-extra", timeout_seconds=1,
                            poll_seconds=0.01) is True


def test_wait_for_survives_transient_probe_exception():
    class FlakySource:
        def __init__(self):
            self.calls = 0

        def passengers(self, pnr):
            self.calls += 1
            if self.calls < 2:
                raise RuntimeError("transient")
            return ["JOHN SMITH"]

    ok = prelude.wait_for(FlakySource(), "passenger", "ZZNCAA-2026-07-10", timeout_seconds=1,
                          poll_seconds=0.01)
    assert ok is True
