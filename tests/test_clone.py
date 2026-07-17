"""Tests for seed/clone.py — fresh-locator + date-shift + docnum + contact rewrite (offline)."""
import json

from seed.clone import ac_docnum, clone_fixture


def _make_src(root):
    d = root / "FDAP36"
    d.mkdir()
    (d / "01_pnr.json").write_text(json.dumps({"processedPnr": {
        "bookingIdentifier": "FDAP36", "recordLocator": "FDAP36", "version": "1",
        "id": "FDAP36-2026-06-13", "passengers": [{"id": "FDAP36-2026-06-13-PT-1"}],
        "segments": [{"id": "FDAP36-2026-06-13-ST-1", "date": "2026-06-13"}],
        "contacts": [{"email": {"address": "old@gmail.com"}}]}}), encoding="utf-8")
    (d / "02_ticket.json").write_text(json.dumps({"processedTicket": {
        "primaryDocumentNumber": "0142000800200", "pnrId": "FDAP36-2026-06-13"}}), encoding="utf-8")
    (d / "03_fdm_skd_leg1.xml").write_text("<f><dep>2026-06-13T08:00:00</dep></f>", encoding="utf-8")
    (d / "meta.json").write_text(json.dumps({
        "locator": "FDAP36", "pnr_id": "FDAP36-2026-06-13", "date": "2026-06-13",
        "ticket": "0142000800200", "leg_id": "AC#8002#YYZ#2026-06-13",
        "carrier": "AC", "flight": 8002, "route": "YYZ-LHR", "first": "MARA", "surname": "OKONKWO"}),
        encoding="utf-8")
    return d


def test_clone_rewrites_locator_docnum_date_contact(tmp_path):
    _make_src(tmp_path)
    out = tmp_path / "out"
    d = clone_fixture(tmp_path / "FDAP36", out, "ZZFDAC", contact_email="lahiru@m.com",
                      index=2, new_date="2026-07-09", pnr_version="9")
    pnr = json.loads((d / "01_pnr.json").read_text(encoding="utf-8"))["processedPnr"]
    assert pnr["bookingIdentifier"] == "ZZFDAC" and pnr["recordLocator"] == "ZZFDAC"
    assert pnr["id"] == "ZZFDAC-2026-07-09"                      # locator + date rekeyed
    assert pnr["passengers"][0]["id"] == "ZZFDAC-2026-07-09-PT-1"
    assert pnr["segments"][0]["id"] == "ZZFDAC-2026-07-09-ST-1"
    assert pnr["segments"][0]["date"] == "2026-07-09"
    assert pnr["version"] == "9"
    assert pnr["contacts"][0]["email"]["address"] == "lahiru@m.com"
    tkt = json.loads((d / "02_ticket.json").read_text(encoding="utf-8"))["processedTicket"]
    assert tkt["primaryDocumentNumber"] == ac_docnum(2)
    assert tkt["pnrId"] == "ZZFDAC-2026-07-09"
    # XML date-shifted too
    assert "2026-07-09T08:00:00" in (d / "03_fdm_skd_leg1.xml").read_text(encoding="utf-8")
    assert "2026-06-13" not in (d / "03_fdm_skd_leg1.xml").read_text(encoding="utf-8")
    meta = json.loads((d / "meta.json").read_text(encoding="utf-8"))
    assert meta["pnr_id"] == "ZZFDAC-2026-07-09" and meta["date"] == "2026-07-09"
    assert meta["leg_id"] == "AC#8002#YYZ#2026-07-09"
    assert meta["cloned_from"] == "FDAP36"


def test_clone_no_date_shift_keeps_source_date(tmp_path):
    _make_src(tmp_path)
    d = clone_fixture(tmp_path / "FDAP36", tmp_path / "out2", "ZZFDAD",
                      contact_email="x@m.com", index=3)
    meta = json.loads((d / "meta.json").read_text(encoding="utf-8"))
    assert meta["date"] == "2026-06-13" and meta["pnr_id"] == "ZZFDAD-2026-06-13"
