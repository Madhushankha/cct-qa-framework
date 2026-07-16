import datetime

from catalog.model import SeedSpec, UseCase
from seed import scenario


def _uc(title):
    return UseCase(id="X", regime="", verdict="", system_code="FD-APPR-EL-400", title=title,
                   third_party=False, checkpoint_vector=[], customer_intent="",
                   expected_transcript=[], seed=SeedSpec(pnr="ZQ", passenger="A B",
                   amount={"currency": "CAD", "value": 400.0}), seed_pending=False)


def test_pending_gets_within_72h_and_completed_gets_7d():
    now = datetime.datetime(2026, 7, 17, tzinfo=datetime.timezone.utc)
    assert scenario.flight_date_for(_uc("Pending | 72 Hours Not Elapsed"), now) == "2026-07-16"
    assert scenario.flight_date_for(_uc("Travel Completed | APPR"), now) == "2026-07-10"
