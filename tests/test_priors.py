# SPDX-FileCopyrightText: 2026 Justin Stanley
# SPDX-License-Identifier: MIT
import numpy as np
import pytest

from impsolver.model import AlignedMember, Alignment, AlignmentBody, DefectionPrior, RuleSet
from impsolver.priors import PriorError, Propensity, adjust, apply_defection_prior, fit_beta
from tests.conftest import make_comp, make_scenario

LOAD = [0.0, 0.0]


def _alignment(breaks: dict[str, int | None], votes: int = 200) -> Alignment:
    ms = [
        AlignedMember(id=i, name=i, party="R", bloc="R", n_votes=votes, breaks=b, loadings=LOAD)
        for i, b in breaks.items()
    ]
    body = AlignmentBody(
        k=2,
        n_contested=votes,
        members=ms,
        bloc_mean_loadings={"R": LOAD},
        bloc_break_rate={"R": 0.05},
    )
    return Alignment(
        schema_version=1,
        encoding="unsigned_breaks",
        source="t",
        congresses=[116],
        kappa=50,
        min_shared=10,
        bodies={"house": body},
    )


def _comp():  # type: ignore[no-untyped-def]
    house = [{"id": i, "name": i, "party": "R"} for i in ("HI", "LO", "OWN", "NEW")]
    house[2]["p_pro"] = {"*": 0.3}
    return make_comp(house, {"R": 1})


def test_direction_and_untouched(rules: RuleSet) -> None:
    scen = make_scenario(
        party_priors={"R": {"*": 0.1}}, alignment="a.json", defection_prior={"beta": 1.0}
    )
    comp = apply_defection_prior(
        scen.defection_prior,
        scen,
        _comp(),
        rules,  # type: ignore[arg-type]
        _alignment({"HI": 40, "LO": 0, "OWN": 40}),
    )
    by = {m.id: m for m in comp.bodies["house"].roster}
    assert by["HI"].p_pro["H2"] > 0.1 > by["LO"].p_pro["H2"]
    assert by["HI"].p_source == "defection_rate"
    assert by["OWN"].p_pro == {"*": 0.3}  # own probability is untouched
    assert by["NEW"].p_pro == {}  # no history is untouched


def test_toward_party_when_party_leans_pro() -> None:
    prop = Propensity(40, 200, 0.05, "t")
    assert adjust(0.9, prop, 1.0, 20) < 0.9 < adjust(0.9, Propensity(0, 200, 0.05, "t"), 1.0, 20)


def test_beta_zero_and_half_are_no_ops() -> None:
    prop = Propensity(40, 200, 0.05, "t")
    assert adjust(0.2, prop, 0.0, 20) == 0.2
    assert adjust(0.5, prop, 3.0, 20) == 0.5


def test_shrinkage_with_pseudo_votes() -> None:
    few = Propensity(2, 4, 0.05, "t")
    many = Propensity(100, 200, 0.05, "t")
    assert few.excess(20) < many.excess(20)
    assert few.rate(20) == pytest.approx((2 + 20 * 0.05) / 24)


def test_stage_filter(rules: RuleSet) -> None:
    scen = make_scenario(
        party_priors={"R": {"*": 0.1}}, alignment="a.json", defection_prior={"stages": ["H2"]}
    )
    comp = apply_defection_prior(
        DefectionPrior(stages=["H2"]), scen, _comp(), rules, _alignment({"HI": 40})
    )
    hi = next(m for m in comp.bodies["house"].roster if m.id == "HI")
    assert set(hi.p_pro) == {"H2"}


def test_fails_loudly(rules: RuleSet) -> None:
    scen = make_scenario(party_priors={"R": {"*": 0.1}}, alignment="a.json", defection_prior={})
    with pytest.raises(PriorError, match="break counts"):
        apply_defection_prior(DefectionPrior(), scen, _comp(), rules, _alignment({"HI": None}))
    with pytest.raises(PriorError, match="matched no members"):
        apply_defection_prior(DefectionPrior(), scen, _comp(), rules, _alignment({"ZZ": 3}))


def test_fit_beta_recovers_slope() -> None:
    rng = np.random.default_rng(0)
    x = rng.normal(size=4000)
    y = (rng.random(4000) < 1 / (1 + np.exp(-(-1 + 1.5 * x)))).astype(int)
    beta, se = fit_beta(list(x), list(y))
    assert beta == pytest.approx(1.5, abs=3 * se) and se < 0.1
    with pytest.raises(PriorError):
        fit_beta([0.1, 0.2], [0, 0])
