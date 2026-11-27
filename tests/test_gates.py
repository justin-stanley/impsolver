from impsolver.gates import evaluate_gate
from impsolver.model import RuleSet


def test_no_quorum(rules: RuleSet) -> None:
    g = evaluate_gate(rules.stage("H2"), 100, 50, 0, 285, 435)
    assert g.outcome == "NO_QUORUM"


def test_fail_direction_counts_nay_as_pro(rules: RuleSet) -> None:
    s1 = rules.stage("S1")
    assert evaluate_gate(s1, 50, 50, 0, 0, 100).outcome == "PASS"
    assert evaluate_gate(s1, 49, 51, 0, 0, 100).outcome == "FAIL"


def test_conviction_shortfall(rules: RuleSet) -> None:
    g = evaluate_gate(rules.stage("S2"), 57, 43, 0, 0, 100)
    assert (g.outcome, g.required, g.short) == ("FAIL", 67, 10)


def test_vacancies_shrink_quorum(rules: RuleSet) -> None:
    g = evaluate_gate(rules.stage("H2"), 150, 60, 0, 0, 435, vacancies=20)
    assert g.outcome == "PASS"
