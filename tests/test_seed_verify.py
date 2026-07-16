from catalog.model import UseCase, SeedSpec
from seed.source import FakeSource
from seed.verify import verify_case
from seed.model import VerifyReport


def _uc(pnr="GQWKRH", passenger="OONA BROOKINGDALE"):
    return UseCase(
        id="FD_TC_089", regime="EU", verdict="Eligible", system_code="FD-EU-EL-27",
        title="t", third_party=False, checkpoint_vector=[], customer_intent="",
        expected_transcript=[],
        seed=SeedSpec(pnr=pnr, pnr_id=f"{pnr}-2026-06-15", passenger=passenger,
                      ticket="014581008901", status="ELIGIBLE", system_code="FD-EU-EL-27"),
        seed_pending=False, content_hash="h",
    )


AREAS = ["eds_pnr_output", "eds_contact_email", "trip_active", "passenger", "ticket",
         "dds_endpoint_systemcode_match"]

MAIL = "lahiru@ae-qa1-aircanada.mailinator.com"


def _good_source(pnr="GQWKRH", email=MAIL, last="BROOKINGDALE"):
    return FakeSource({pnr: {
        "eds": {"emails": [email]},
        "trip": {"last_name": last, "status": "ACTIVE"},
        "tickets": ["014581008901"],
        "passengers": ["OONA BROOKINGDALE"],
    }})


def test_all_checkpoints_pass_when_seeded_correctly():
    rep = verify_case(_uc(), _good_source(), expected_email=MAIL, areas=AREAS)
    assert isinstance(rep, VerifyReport)
    assert rep.all_ok  # every verifiable checkpoint passed
    # DDS is reported skipped (not a failure)
    dds = next(c for c in rep.checks if c.area == "dds_endpoint_systemcode_match")
    assert dds.ok is None


def test_wrong_contact_email_fails_the_otp_gate():
    src = _good_source(email="lahiru.premathilake@aircanada.ca")  # corporate, not mailinator
    rep = verify_case(_uc(), src, expected_email=MAIL, areas=AREAS)
    assert not rep.all_ok
    failed = [c.area for c in rep.failed]
    assert "eds_contact_email" in failed


def test_name_mismatch_fails_passenger_check():
    # the BOUCHARD-class bug: trip.last_name != the passenger's real last name
    src = _good_source(last="BOUCHARD")
    rep = verify_case(_uc(passenger="LAURENT GOSSELIN"), src, expected_email=MAIL, areas=AREAS)
    assert "passenger" in [c.area for c in rep.failed]


def test_missing_booking_fails():
    rep = verify_case(_uc(pnr="NOPE01"), FakeSource({}), expected_email=MAIL, areas=AREAS)
    assert not rep.all_ok
    assert "eds_pnr_output" in [c.area for c in rep.failed]


def test_summary_counts():
    rep = verify_case(_uc(), _good_source(), expected_email=MAIL, areas=AREAS)
    s = rep.summary()
    assert "pass" in s and "skipped" in s
