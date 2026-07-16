import datetime

from seed.engine import eval_formula, evaluate_identity, set_dotpath

NOW = datetime.datetime(2026, 7, 17, tzinfo=datetime.timezone.utc)


def test_eval_formula_dates_and_vars():
    assert eval_formula("{{ today() }}", {}, NOW) == "2026-07-17"
    assert eval_formula("{{ date(-7) }}", {}, NOW) == "2026-07-10"
    assert eval_formula("{{ $loc }}-{{ date(-1) }}", {"loc": "ZQ0001"}, NOW) == "ZQ0001-2026-07-16"


def test_evaluate_identity_ordered():
    out = evaluate_identity({"$loc": "MHGQHS", "$pnrId": "{{ $loc }}-{{ date(-7) }}"}, {}, NOW)
    assert out["pnrId"] == "MHGQHS-2026-07-10"


def test_set_dotpath():
    d = {"a": {"b": [{"c": 1}, {"c": 2}]}}
    assert set_dotpath(d, "a.b[*].c", 9) and d["a"]["b"][0]["c"] == 9 and d["a"]["b"][1]["c"] == 9
    assert set_dotpath(d, "a.x", 5) is False  # missing path -> not applied
