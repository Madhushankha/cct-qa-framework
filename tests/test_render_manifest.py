"""render_from_manifest is a thin wrapper: it runs the manifest's `identity` block through the
engine (today-relative date via seed.scenario.flight_date_for) then delegates to render_case, so
FD behavior stays identical to Task 3 — only the date now flows through the engine/manifest."""
import datetime
import json
from pathlib import Path

from catalog.model import SeedSpec, UseCase
from seed.render import render_from_manifest

NOW = datetime.datetime(2026, 7, 17, tzinfo=datetime.timezone.utc)


def _case(pnr="MHGQHS", pax="YANNICK THORNENLOW", route="YUL-YYZ",
          title="Pending | 72 Hours Not Elapsed | APPR"):
    return UseCase(id="FD_TC_060", regime="", verdict="", system_code="FD-APPR-PE-01", title=title,
                   third_party=False, checkpoint_vector=[], customer_intent="", expected_transcript=[],
                   seed=SeedSpec(pnr=pnr, passenger=pax, route=route,
                                 amount={"currency": "CAD", "value": 400.0},
                                 system_code="FD-APPR-PE-01"), seed_pending=False)


def test_manifest_render_uses_scenario_date(tmp_path):
    d = render_from_manifest("fd", _case(), out_root=tmp_path, contact_email="x@m.com",
                             now=NOW, index=1, flight_number=8001)
    meta = json.loads((d / "meta.json").read_text(encoding="utf-8"))
    assert meta["locator"] == "MHGQHS"
    assert meta["pnr_id"] == "MHGQHS-2026-07-16"      # pending -> now-1d
    pnr = (d / "01_pnr.json").read_text(encoding="utf-8")
    assert "THORNENLOW" in pnr and "x@m.com" in pnr
