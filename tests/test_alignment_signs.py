"""Sign conventions of the unsigned-break encoding."""

import numpy as np

from impsolver.alignment import fit_body, pairwise_pearson, unsigned_breaks
from impsolver.model import RuleSet
from impsolver.simulate import chamber_models
from tests import synth
from tests.conftest import make_comp, make_prep
from tests.test_alignment import _alignment

RNG = np.random.default_rng(7)


def _dot(F: np.ndarray, a: list[int], b: list[int]) -> float:
    g = F[a] @ F[b].T
    if a == b:
        n = len(a)
        return float((g.sum() - np.trace(g)) / (n * (n - 1)))
    return float(g.mean())


def test_independent_breakers_near_zero() -> None:
    ms = synth.members(50, 50)
    fit = fit_body(ms, synth.votes(ms, 400, RNG, base_break=0.1), {})
    assert abs(_dot(fit.loadings, list(range(50)), list(range(50)))) < 0.1


def test_cross_bloc_co_breakers_positive() -> None:
    ms = synth.members(50, 50)
    group = ["R000", "R001", "R002", "D000", "D001", "D002"]
    fit = fit_body(ms, synth.votes(ms, 400, RNG, groups=[(group, 0.25)]), {})
    r = [0, 1, 2]
    d = [50, 51, 52]
    assert _dot(fit.loadings, r, d) > 0.4


def test_never_breaker_has_zero_correlation() -> None:
    ms = synth.members(30, 30)
    v = synth.votes(ms, 200, RNG, never={"R000"})
    br = unsigned_breaks(v, [m.party for m in ms])
    corr, _ = pairwise_pearson(br)
    assert np.all(corr[0, 1:] == 0.0)


def _pair_corr(pro: np.ndarray, a: list[int], b: list[int]) -> float:
    x = pro[:, a].mean(axis=1)
    y = pro[:, b].mean(axis=1)
    return float(np.corrcoef(x, y)[0, 1])


def test_co_breakers_break_together_on_partisan_and_bipartisan_gates(rules: RuleSet) -> None:
    ms = synth.members(60, 60)
    group = ["R000", "R001", "R002", "R003", "D000", "D001", "D002", "D003"]
    al = _alignment(ms, synth.votes(ms, 400, RNG, groups=[(group, 0.25)]))
    house = [{"id": m.id, "name": m.name, "party": m.party} for m in ms]
    # H1 is bipartisan (both blocs lean PRO), H2 is partisan (R leans CON).
    prep = make_prep(
        rules,
        make_comp(house, {"D": 60, "R": 40}),
        al,
        alignment="x.json",
        rho=0.0,
        party_priors={"D": {"*": 0.8}, "R": {"*": 0.8, "H2": 0.2}},
    )
    stages = [rules.stage("H1"), rules.stage("H2")]
    cm = chamber_models(prep, "I", stages)["house"]
    pro = cm.draw_pro(np.random.default_rng(0), 20_000, 0.0)
    r_grp, d_grp = [0, 1, 2, 3], [60, 61, 62, 63]
    r_ind = [20, 21, 22, 23]
    # Bipartisan gate: both co-breaking groups break toward CON together.
    assert _pair_corr(pro[0], r_grp, d_grp) > 0.2
    assert abs(_pair_corr(pro[0], r_ind, d_grp)) < 0.05
    # Partisan gate: R breakers go PRO while D breakers go CON, so PRO counts anti-correlate,
    # but both are breaks from their bloc.
    assert _pair_corr(pro[1], r_grp, d_grp) < -0.2
    r_break = pro[1][:, r_grp].mean(axis=1)  # R leans CON (p=.2): a break is PRO
    d_break = (~pro[1][:, d_grp]).mean(axis=1)  # D leans PRO (p=.8): a break is CON
    assert np.corrcoef(r_break, d_break)[0, 1] > 0.2
