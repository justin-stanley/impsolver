import numpy as np
import pytest

from impsolver.model import RuleSet
from impsolver.simulate import p_complete, simulate
from tests.conftest import make_comp, make_prep


@pytest.fixture
def prep(rules: RuleSet):  # type: ignore[no-untyped-def]
    return make_prep(
        rules,
        make_comp({"D": 220, "R": 215}, {"D": 50, "R": 50}),
        party_priors={"D": {"*": 0.9}, "R": {"*": 0.4}},
        seed=3,
    )


def test_marginals_preserved(prep) -> None:  # type: ignore[no-untyped-def]
    s = simulate(prep, draws=40_000).articles[0]
    h2 = next(g for g in s.gates if g.stage == "H2")
    assert h2.pro_count.mean == pytest.approx(220 * 0.9 + 215 * 0.4, rel=0.01)


def test_reproducible_and_seeded(prep) -> None:  # type: ignore[no-untyped-def]
    a = simulate(prep, draws=10_000)
    b = simulate(prep, draws=10_000)
    c = simulate(prep, draws=10_000, seed=99)
    assert a == b and a.seed == 3 and c.seed == 99


def test_rho_widens_spread(prep) -> None:  # type: ignore[no-untyped-def]
    lo = simulate(prep, draws=20_000, rho=0.0).articles[0].gates[1].pro_count
    hi = simulate(prep, draws=20_000, rho=0.8).articles[0].gates[1].pro_count
    assert (hi.p95 - hi.p5) > 3 * (lo.p95 - lo.p5)


def test_conditional_pass_and_complete(prep) -> None:  # type: ignore[no-untyped-def]
    s = simulate(prep, draws=20_000).articles[0]
    reached = 1.0
    for g in s.gates[:4]:
        assert g.p_reached == pytest.approx(reached, abs=1e-9)
        reached *= g.p_pass_given_reached
    assert s.p_complete == pytest.approx(reached, abs=1e-9)
    assert 0 < s.mc_se < 0.01


def test_shift_is_monotone_with_common_random_numbers(prep) -> None:  # type: ignore[no-untyped-def]
    ps = [p_complete(prep, draws=5000, extra=d) for d in np.linspace(0, 3, 7)]
    assert all(b >= a for a, b in zip(ps, ps[1:], strict=False))
