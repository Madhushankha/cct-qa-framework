"""render_case builds a per-case ALTEA fixture from the framework-owned base template + gap-doc
data (dataset 6-char locator, independent name, route, delay) — no reference-corpus cloning."""
import json
from pathlib import Path

from catalog.model import SeedSpec, UseCase
from seed.render import render_case

BASE = Path("data/fd-templates/base_appr")


def _case(pnr="MHGQHS", passenger="YANNICK THORNENLOW", route="YUL-YYZ",
          amount=400.0, system_code="FD-APPR-EL-400"):
    return UseCase(id="FD_TC_001", regime="APPR", verdict="ELIGIBLE", system_code=system_code,
                   title="", third_party=False, checkpoint_vector=[], customer_intent="",
                   expected_transcript=[],
                   seed=SeedSpec(pnr=pnr, passenger=passenger, route=route,
                                 amount={"currency": "CAD", "value": amount},
                                 system_code=system_code),
                   seed_pending=False)


def test_render_writes_case_identity(tmp_path):
    d = render_case(BASE, tmp_path, _case(), contact_email="x@m.com",
                    flight_date="2026-07-10", index=1)
    pnr = (d / "01_pnr.json").read_text(encoding="utf-8")
    # dataset locator + name present; template's originals gone
    assert "MHGQHS" in pnr and "FDAP36" not in pnr
    assert "THORNENLOW" in pnr and "OKONKWO" not in pnr
    assert "YANNICK" in pnr and "MARA" not in pnr
    assert "x@m.com" in pnr


def test_render_rewrites_route_and_date(tmp_path):
    d = render_case(BASE, tmp_path, _case(route="YUL-YYZ"), contact_email="x@m.com",
                    flight_date="2026-07-10", index=2)
    fdm = (d / "04_fdm_delay_leg1.xml").read_text(encoding="utf-8")
    assert "<departureAirport>YUL</departureAirport>" in fdm
    assert "<arrivalAirport>YYZ</arrivalAirport>" in fdm
    assert "2026-07-10" in fdm and "2026-06-13" not in fdm


def test_render_meta_reflects_case(tmp_path):
    d = render_case(BASE, tmp_path, _case(), contact_email="x@m.com",
                    flight_date="2026-07-10", index=3)
    meta = json.loads((d / "meta.json").read_text(encoding="utf-8"))
    assert meta["locator"] == "MHGQHS"
    assert meta["surname"] == "THORNENLOW" and meta["first"] == "YANNICK"
    assert meta["pnr_id"] == "MHGQHS-2026-07-10"


def test_render_ticket_unique(tmp_path):
    d1 = render_case(BASE, tmp_path, _case(pnr="MHGQHS"), contact_email="x@m.com",
                     flight_date="2026-07-10", index=1)
    d2 = render_case(BASE, tmp_path, _case(pnr="MPGPAW", passenger="PRIYA FAIRINGWYN"),
                     contact_email="x@m.com", flight_date="2026-07-10", index=2)
    t1 = json.loads((d1 / "02_ticket.json").read_text(encoding="utf-8"))
    t2 = json.loads((d2 / "02_ticket.json").read_text(encoding="utf-8"))
    assert t1["processedTicket"]["primaryDocumentNumber"] != \
        t2["processedTicket"]["primaryDocumentNumber"]


def test_render_rewrites_flight_uniquely(tmp_path):
    d = render_case(BASE, tmp_path, _case(), contact_email="x@m.com",
                    flight_date="2026-07-10", index=1, flight_number=8042)
    fdm = (d / "04_fdm_delay_leg1.xml").read_text(encoding="utf-8")
    assert "<fnNumber>8042</fnNumber>" in fdm and "<fnNumber>8002</fnNumber>" not in fdm
    assert "ACA8042" in fdm and "ACA8002" not in fdm
    # ticket number (contains the substring '8002') must NOT be corrupted by the flight rewrite
    tkt = (d / "02_ticket.json").read_text(encoding="utf-8")
    assert "0142000800200" not in tkt  # docnum was rewritten to a run-unique value
    import json as _j
    meta = _j.loads((d / "meta.json").read_text(encoding="utf-8"))
    assert meta["flight"] == 8042
