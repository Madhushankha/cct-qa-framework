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


# --- soc vocabulary: "Transit Delay >=2h" / "Delay Below 2h", not fd's 3/6/9-hour bands ----------

def test_temporal_intent_soc_titles():
    assert temporal_intent(_uc("APPR – Eligible – Transit Delay ≥2h – Within Carrier Control")) == "completed"
    assert temporal_intent(_uc("APPR – Pending – 72 Hours")) == "pending"
    assert temporal_intent(_uc("APPR – Not Eligible – No Travel Origin – Outside Carrier Control")) == "no_travel"
    assert temporal_intent(_uc("EU – Eligible – No Travel Return – Delay ≥2h")) == "no_travel"


def test_delay_minutes_soc_two_hour_threshold():
    assert delay_minutes(_uc("APPR – Eligible – Transit Delay ≥2h – Within Carrier Control")) == 120
    assert delay_minutes(_uc("APPR – Not Eligible – Transit Delay Below 2 Hours")) == 60
    assert delay_minutes(_uc("APPR – Not Eligible – No Travel Origin – Delay Below 2h")) == 60
    assert delay_minutes(_uc("EU – Eligible – No Travel Origin – Delay ≥2h")) == 120
