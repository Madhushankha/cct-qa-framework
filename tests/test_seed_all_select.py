"""seed --all case selection: DDS family derived from systemCode (regime is blank on gap-doc
cases), and only families with a registered template are seedable today."""
from catalog.model import SeedSpec, UseCase
from seed.cli import _dds_family, _templated_family

TEMPLATES = {"APPR_CAD_400", "APPR_CAD_700", "APPR_CAD_1000"}


def _c(sc, cur="CAD", val=400.0):
    return UseCase(id="X", regime="", verdict="", system_code=sc, title="", third_party=False,
                   checkpoint_vector=[], customer_intent="", expected_transcript=[],
                   seed=SeedSpec(pnr="MHGQHS", passenger="A B", system_code=sc,
                                 amount={"currency": cur, "value": val}),
                   seed_pending=False)


def test_appr_cad_tiers():
    assert _dds_family(_c("FD-APPR-EL-400", val=400)) == "APPR_CAD_400"
    assert _dds_family(_c("FD-APPR-EL-700", val=700)) == "APPR_CAD_700"
    assert _dds_family(_c("FD-APPR-EL-1000", val=1000)) == "APPR_CAD_1000"


def test_non_appr_and_non_cad_have_no_template_today():
    assert _dds_family(_c("FD-EU-EL-250", cur="EUR", val=250)) is None
    assert _dds_family(_c("FD-ASL-EL-1", cur="ILS", val=1)) is None
    assert _dds_family(_c("FD-APPR-NE-BT")) is None  # not eligible -> no template yet


def test_templated_family_gate():
    assert _templated_family(_c("FD-APPR-EL-400", val=400), TEMPLATES) == "APPR_CAD_400"
    assert _templated_family(_c("FD-APPR-EL-400", val=400), set()) is None  # unregistered
