from hypothesis import given
from hypothesis import strategies as st

from impsolver.model import ThresholdRule
from impsolver.thresholds import ceil_div, has_quorum, pro_wins, required_pro

MAJ = ThresholdRule(kind="majority_of_votes_cast")
TWO_THIRDS = ThresholdRule(kind="fraction_of_present", p=2, q=3)


def test_two_thirds_examples() -> None:
    assert required_pro(TWO_THIRDS, "pass", 100) == 67
    assert required_pro(TWO_THIRDS, "pass", 54) == 36
    assert required_pro(TWO_THIRDS, "pass", 99) == 66


def test_ceil_div() -> None:
    assert ceil_div(200, 3) == 67
    assert ceil_div(198, 3) == 66


def test_majority_pass_and_fail_direction_tie() -> None:
    assert not pro_wins(MAJ, "pass", 50, 50, 0, 0)  # a tie fails an adopting motion
    assert pro_wins(MAJ, "fail", 50, 50, 0, 0)  # a tie defeats the motion to table
    assert required_pro(MAJ, "pass", 100) == 51
    assert required_pro(MAJ, "fail", 100) == 50


def test_present_in_denominator() -> None:
    assert not pro_wins(TWO_THIRDS, "pass", 66, 33, 1, 0)
    off = ThresholdRule(kind="fraction_of_present", p=2, q=3, present_in_denominator=False)
    assert pro_wins(off, "pass", 66, 33, 1, 0)


def test_membership_base() -> None:
    r = ThresholdRule(kind="fraction_of_membership", p=2, q=3)
    assert required_pro(r, "pass", 80, base=100) == 67


def test_quorum() -> None:
    assert has_quorum(51, 100) and not has_quorum(50, 100)


rules = st.sampled_from(
    [
        (MAJ, "pass"),
        (MAJ, "fail"),
        (TWO_THIRDS, "pass"),
        (ThresholdRule(kind="fraction_of_present", p=3, q=5), "pass"),
        (ThresholdRule(kind="fraction_of_present", p=2, q=3), "fail"),
    ]
)


@given(rules, st.integers(1, 500), st.integers(0, 5))
def test_required_pro_is_minimal(rd: tuple[ThresholdRule, str], voting: int, present: int) -> None:
    rule, d = rd
    need = required_pro(rule, d, voting, present)  # type: ignore[arg-type]
    if need <= voting:
        assert pro_wins(rule, d, need, voting - need, present, 0)  # type: ignore[arg-type]
    if 0 < need <= voting + 1:
        assert not pro_wins(rule, d, need - 1, voting - need + 1, present, 0)  # type: ignore[arg-type]
