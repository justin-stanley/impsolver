from impsolver.model import RuleSet
from impsolver.viability import Case, assess, support_gap
from tests.conftest import make_comp, make_prep


def test_ranking_and_labels(rules: RuleSet) -> None:
    comp = make_comp({"D": 220, "R": 215}, {"D": 50, "R": 50})
    easy = make_prep(rules, comp, party_priors={"D": {"*": 0.99}, "R": {"*": 0.9}})
    mid = make_prep(rules, comp, party_priors={"D": {"*": 0.95}, "R": {"*": 0.3}})
    hard = make_prep(rules, comp, party_priors={"D": {"*": 0.6}, "R": {"*": 0.01}})
    rows = assess([Case("hard", hard), Case("easy", easy), Case("mid", mid)], draws=4000)
    assert [r.scenario for r in rows] == ["easy", "mid", "hard"]
    assert rows[0].label == "viable" and rows[0].support_gap == 0.0
    assert rows[1].label == "reachable" and 0 < (rows[1].support_gap or 0) <= 2
    assert rows[2].label == "out of reach"


def test_gap_none_when_unreachable(rules: RuleSet) -> None:
    prep = make_prep(
        rules,
        make_comp({"D": 1, "R": 434}, {"D": 1, "R": 99}),
        party_priors={"D": {"*": 1.0}, "R": {"*": 0.0}},
    )
    assert support_gap(prep, 0.5, 2000) is None
