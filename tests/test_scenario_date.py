import datetime

from catalog.model import SeedSpec, UseCase
from seed.scenario import flight_date_for, scenario_date

NOW = datetime.datetime(2026, 7, 17, tzinfo=datetime.timezone.utc)


def test_scenario_date_by_intent():
    assert scenario_date("completed", NOW) == "2026-07-10"
    assert scenario_date("pending", NOW) == "2026-07-16"      # within 72h
    assert scenario_date("pre_travel", NOW) == "2026-07-20"   # future
    assert scenario_date("no_travel", NOW) == "2026-07-10"


def test_flight_date_for_case():
    uc = UseCase(id="X", regime="", verdict="", system_code="FD-APPR-PE-01",
                 title="Pending | 72 Hours Not Elapsed | APPR", third_party=False,
                 checkpoint_vector=[], customer_intent="", expected_transcript=[],
                 seed=SeedSpec(), seed_pending=False)
    assert flight_date_for(uc, NOW) == "2026-07-16"
