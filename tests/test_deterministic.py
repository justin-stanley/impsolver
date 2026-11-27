import pytest

from impsolver.deterministic import evaluate
from impsolver.members import ResolutionError, shifted
from impsolver.model import RuleSet
from tests.conftest import make_comp, make_prep


def test_clear_fail_at_conviction(rules: RuleSet) -> None:
    prep = make_prep(rules, make_comp({"D": 240, "R": 195}, {"D": 55, "R": 45}))
    a = evaluate(prep).articles[0]
    gates = {g.stage: g for g in a.gates}
    assert gates["H2"].verdict == "PASS" and gates["S1"].verdict == "PASS"
    assert gates["S2"].verdict == "FAIL" and gates["S2"].short_at_min == 12
    assert a.verdict == "FAIL" and a.ends_at == "S2" and a.binding_gate == "S2"
    assert a.controlling_coalition[0].bloc == "R"


def test_contested_when_uncertain(rules: RuleSet) -> None:
    prep = make_prep(
        rules,
        make_comp({"D": 200, "R": 235}, {"D": 70, "R": 30}),
        party_priors={"D": {"*": 0.95}, "R": {"*": 0.5}},
    )
    a = evaluate(prep).articles[0]
    assert a.verdict == "CONTESTED"
    assert {g.stage: g.verdict for g in a.gates}["H2"] == "CONTESTED"


def test_resolution_order(rules: RuleSet) -> None:
    house = [
        {"id": "M1", "name": "a", "party": "R", "p_pro": {"H2": 0.7, "*": 0.6}},
        {"id": "M2", "name": "b", "party": "R", "p_pro": {"*": 0.6}},
        {"id": "M3", "name": "c", "party": "R"},
    ]
    prep = make_prep(
        rules,
        make_comp(house, {"D": 1}),
        party_priors={"R": {"H2": 0.3, "*": 0.2}, "D": {"*": 0.5}},
        overrides={"M2": {"H2": 0.99}},
    )
    r = prep.resolver
    m1, m2, m3 = prep.members("house")
    assert r.resolve(m1, "H2", "I") == 0.7 and r.resolve(m1, "H1", "I") == 0.6
    assert r.resolve(m2, "H2", "I") == 0.99 and r.resolve(m2, "H1", "I") == 0.6
    assert r.resolve(m3, "H2", "I") == 0.3 and r.resolve(m3, "H1", "I") == 0.2


def test_missing_probability_raises(rules: RuleSet) -> None:
    prep = make_prep(rules, make_comp({"G": 3}, {"D": 1}))
    with pytest.raises(ResolutionError):
        evaluate(prep)


def test_shifts_and_fixed_points(rules: RuleSet) -> None:
    assert shifted(0.0, 3) == 0.0 and shifted(1.0, -3) == 1.0
    prep = make_prep(
        rules,
        make_comp({"R": 1}, {"D": 1}),
        party_priors={"R": {"*": 0.5}, "D": {"*": 0.5}},
        shifts=[
            {"label": "a", "bloc": "R", "delta": 1.0, "stage": "H2"},
            {"label": "b", "bloc": "*", "delta": 1.0, "article": "I"},
        ],
    )
    m = prep.members("house")[0]
    assert prep.resolver.resolve(m, "H2", "I") == pytest.approx(shifted(0.5, 2.0))
    assert prep.resolver.resolve(m, "H1", "II") == 0.5


def test_presiding_officer(rules: RuleSet) -> None:
    comp = make_comp({"D": 3}, {"D": 3})
    pres = make_prep(rules, comp, target={"name": "T", "office": "president"})
    other = make_prep(rules, comp)
    s2 = [g for g in evaluate(pres).articles[0].gates if g.stage == "S2"][0]
    s2o = [g for g in evaluate(other).articles[0].gates if g.stage == "S2"][0]
    assert s2.presiding_officer == "chief_justice"
    assert s2o.presiding_officer == "president_pro_tempore_or_vp"


def test_binding_gate_is_first_unwinnable(rules: RuleSet) -> None:
    # H1/H2 are contested but winnable; S2 cannot be won even if every uncertain member votes PRO.
    prep = make_prep(
        rules,
        make_comp({"D": 190, "R": 245}, {"D": 45, "R": 55}),
        party_priors={"D": {"*": 0.95}, "R": {"*": 0.5, "S2": 0.02}},
    )
    a = evaluate(prep).articles[0]
    gates = {g.stage: g for g in a.gates}
    assert gates["H1"].short_at_min > gates["S2"].short_at_min
    assert a.ends_at == "S2" and a.binding_gate == "S2"
