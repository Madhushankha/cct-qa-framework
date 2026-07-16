from catalog.model import SeedSpec, UseCase
from seed.scenario import delay_minutes, segment_status, temporal_intent


def _uc(title, sc="FD-APPR-EL-400", val=400.0):
    return UseCase(id="X", regime="", verdict="", system_code=sc, title=title, third_party=False,
                   checkpoint_vector=[], customer_intent="", expected_transcript=[],
                   seed=SeedSpec(system_code=sc, amount={"currency": "CAD", "value": val}),
                   seed_pending=False)


def test_temporal_intent():
    assert temporal_intent(_uc("Travel Completed | APPR | Delay 3-<6 hrs")) == "completed"
    assert temporal_intent(_uc("Pending | 72 Hours Not Elapsed | APPR")) == "pending"
    assert temporal_intent(_uc("Pre-Travel | Customer Before Flight Date | Rejected")) == "pre_travel"
    assert temporal_intent(_uc("No Travel Origin | APPR | Controllable | Cash")) == "no_travel"


def test_delay_minutes_from_title_then_amount():
    assert delay_minutes(_uc("... Delay 3-<6 hrs")) == 240
    assert delay_minutes(_uc("... Delay 6-<9 hrs", sc="FD-APPR-EL-700", val=700)) == 400
    assert delay_minutes(_uc("Travel Completed | APPR", val=1000, sc="FD-APPR-EL-1000")) == 600


def test_segment_status():
    assert segment_status(_uc("No Travel Origin | APPR")) == "UN"
    assert segment_status(_uc("Travel Completed | APPR")) == "HK"
