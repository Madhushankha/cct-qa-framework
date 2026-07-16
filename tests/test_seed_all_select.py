"""seed --all case selection: every FD disruption verdict (EL/NE/ND/PE/DB across APPR/EU/ASL) is
seedable from the one base template via canonicalize_verdict; currency/delay derive from the case."""
from catalog.model import SeedSpec, UseCase
from seed.cli import _case_currency, _case_delay, _seedable_verdict


def _c(sc, cur=None, val=400.0):
    amount = {"currency": cur, "value": val} if cur else {"value": val}
    return UseCase(id="X", regime="", verdict="", system_code=sc, title="", third_party=False,
                   checkpoint_vector=[], customer_intent="", expected_transcript=[],
                   seed=SeedSpec(pnr="MHGQHS", passenger="A B", system_code=sc, amount=amount),
                   seed_pending=False)


def test_all_disruption_verdicts_seedable():
    for sc in ("FD-APPR-EL-400", "FD-APPR-NE-05", "FD-APPR-ND-02", "FD-APPR-PE-01",
               "FD-EU-EL-600", "FD-ASL-NE-01", "FD-MIXED-EL-1", "FD-DUP-NE-1"):
        assert _seedable_verdict(_c(sc)), sc


def test_currency_from_regime_when_amount_has_none():
    assert _case_currency(_c("FD-APPR-EL-400")) == "CAD"
    assert _case_currency(_c("FD-EU-EL-600")) == "EUR"
    assert _case_currency(_c("FD-ASL-EL-3580")) == "ILS"
    # explicit amount currency wins
    assert _case_currency(_c("FD-EU-EL-600", cur="GBP")) == "GBP"


def test_delay_tier_from_amount():
    assert _case_delay(_c("FD-APPR-EL-400", val=400)) == 240
    assert _case_delay(_c("FD-APPR-EL-700", val=700)) == 400
    assert _case_delay(_c("FD-APPR-EL-1000", val=1000)) == 600
