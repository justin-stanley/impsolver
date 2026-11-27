# SPDX-FileCopyrightText: 2026 Justin Stanley
# SPDX-License-Identifier: MIT
"""Scenario option ``gate_correlation``: how much a member's draw carries from gate to gate."""

from __future__ import annotations

from statistics import NormalDist

import numpy as np
import numpy.typing as npt
import pytest
from pydantic import ValidationError

from impsolver.model import RuleSet
from impsolver.paths import build_path
from impsolver.prepare import Prepared
from impsolver.simulate import ChamberModel, chamber_models, run_raw, simulate
from tests import synth
from tests.conftest import make_comp, make_prep, make_scenario
from tests.test_alignment import _alignment


def _reference_draw(
    cm: ChamberModel, rng: np.random.Generator, m: int, rho: float
) -> npt.NDArray[np.bool_]:
    """The pre-option implementation: one draw reused at every gate."""
    n = len(cm.members)
    z = rng.standard_normal((m, cm.n_blocs))
    e = rng.standard_normal((m, n))
    common = np.sqrt(rho) * z[:, cm.bloc_idx]
    if cm.F is None:
        return np.asarray(u_lt(common + np.sqrt(1 - rho) * e, cm.thresholds))
    assert cm.signs is not None
    w = rng.standard_normal((m, cm.F.shape[1]))
    fw = w @ cm.F.T
    norm2 = (cm.F**2).sum(axis=1)
    out = np.empty((len(cm.stages), m, n), dtype=bool)
    for g in range(len(cm.stages)):
        s = cm.signs[g]
        idio = np.sqrt(np.clip(1.0 - s**2 * norm2, 0.0, 1.0))
        out[g] = common + np.sqrt(1 - rho) * (s * fw + idio * e) < cm.thresholds[g]
    return out


def u_lt(u: npt.NDArray[np.float64], t: npt.NDArray[np.float64]) -> npt.NDArray[np.bool_]:
    res: npt.NDArray[np.bool_] = u[None, :, :] < t[:, None, :]
    return res


def _plain(rules: RuleSet, **kw: object) -> Prepared:
    return make_prep(
        rules,
        make_comp({"D": 218, "R": 217}, {"D": 50, "R": 50}),
        party_priors={"D": {"*": 0.7, "H2": 0.6}, "R": {"*": 0.3, "H1": 0.4}},
        **kw,
    )


def _aligned(rules: RuleSet) -> Prepared:
    ms = synth.members(40, 40)
    group = ["R000", "R001", "R002", "D000", "D001", "D002"]
    al = _alignment(ms, synth.votes(ms, 300, np.random.default_rng(1), groups=[(group, 0.25)]))
    house = [{"id": m.id, "name": m.name, "party": m.party} for m in ms]
    return make_prep(
        rules,
        make_comp(house, {"D": 50, "R": 50}),
        al,
        alignment="x.json",
        party_priors={"D": {"*": 0.8}, "R": {"*": 0.7, "H2": 0.2}},
    )


def _house(prep: Prepared, rules: RuleSet) -> ChamberModel:
    return chamber_models(prep, "I", [rules.stage("H1"), rules.stage("H2")])["house"]


def test_default_is_one_and_bounds_enforced() -> None:
    assert make_scenario().gate_correlation == 1.0
    for bad in (-0.1, 1.1):
        with pytest.raises(ValidationError):
            make_scenario(gate_correlation=bad)


@pytest.mark.parametrize("aligned", [False, True])
@pytest.mark.parametrize("rho", [0.0, 0.6])
def test_c_one_identical_to_reference(rules: RuleSet, aligned: bool, rho: float) -> None:
    cm = _house(_aligned(rules) if aligned else _plain(rules), rules)
    assert (cm.F is not None) == aligned
    new = cm.draw_pro(np.random.default_rng(5), 3000, rho)
    explicit = cm.draw_pro(np.random.default_rng(5), 3000, rho, gate_correlation=1.0)
    ref = _reference_draw(cm, np.random.default_rng(5), 3000, rho)
    assert np.array_equal(new, ref)
    assert np.array_equal(explicit, ref)


def test_c_one_simulation_unchanged(rules: RuleSet) -> None:
    a = simulate(_plain(rules), draws=5000, seed=2)
    b = simulate(_plain(rules, gate_correlation=1.0), draws=5000, seed=2)
    assert a == b


def _pro_corr(rules: RuleSet, c: float, rho: float) -> float:
    prep = _plain(rules, rho=rho, gate_correlation=c)
    raw = run_raw(prep, "I", build_path(rules, "A"), 20_000, 4, rho)
    ids = [s.id for s in raw.stages]
    return float(np.corrcoef(raw.pro[ids.index("H1")], raw.pro[ids.index("H2")])[0, 1])


def test_c_zero_gates_independent(rules: RuleSet) -> None:
    assert abs(_pro_corr(rules, 0.0, 0.0)) < 0.03
    assert abs(_pro_corr(rules, 0.0, 0.6)) < 0.03
    # With c = 1 the same draws drive both gates.
    assert _pro_corr(rules, 1.0, 0.0) > 0.5
    mid = _pro_corr(rules, 0.5, 0.6)
    assert 0.1 < mid < _pro_corr(rules, 1.0, 0.6)


def test_c_zero_senate_gates_independent(rules: RuleSet) -> None:
    prep = _plain(rules, rho=0.6, gate_correlation=0.0)
    raw = run_raw(prep, "I", build_path(rules, "A"), 20_000, 4, 0.6)
    ids = [s.id for s in raw.stages]
    assert abs(np.corrcoef(raw.pro[ids.index("S1")], raw.pro[ids.index("S2")])[0, 1]) < 0.03


@pytest.mark.parametrize("aligned", [False, True])
@pytest.mark.parametrize("c", [0.0, 0.3, 1.0])
def test_marginals_preserved(rules: RuleSet, aligned: bool, c: float) -> None:
    cm = _house(_aligned(rules) if aligned else _plain(rules), rules)
    p = np.vectorize(NormalDist().cdf)(cm.thresholds)
    m = 40_000
    pro = cm.draw_pro(np.random.default_rng(9), m, 0.6, gate_correlation=c)
    got = pro.mean(axis=1)  # [g, n]
    # Individual marginals; the bloc swing correlates members, so the tolerance is generous.
    assert np.all(np.abs(got - p) < 0.02)
    # Expected PRO count per gate matches the sum of probabilities.
    counts = pro.sum(axis=2).mean(axis=1)
    assert np.allclose(counts, p.sum(axis=1), rtol=0.02)


def test_c_zero_aligned_gates_decorrelate(rules: RuleSet) -> None:
    cm = _house(_aligned(rules), rules)
    grp = [0, 1, 2]
    one = cm.draw_pro(np.random.default_rng(3), 20_000, 0.0, gate_correlation=1.0)
    zero = cm.draw_pro(np.random.default_rng(3), 20_000, 0.0, gate_correlation=0.0)

    def corr(pro: npt.NDArray[np.bool_]) -> float:
        return float(np.corrcoef(pro[0][:, grp].mean(axis=1), pro[1][:, grp].mean(axis=1))[0, 1])

    assert abs(corr(one)) > 0.3
    assert abs(corr(zero)) < 0.03


def test_c_zero_with_national_swing_links_only_first_gates(rules: RuleSet) -> None:
    prep = make_prep(
        rules,
        make_comp({"D": 218, "R": 217}, {"D": 50, "R": 50}),
        party_priors={"D": {"*": 0.9}, "R": {"*": 0.3}},
        rho=0.8,
        national_swing=True,
        gate_correlation=0.0,
    )
    raw = run_raw(prep, "I", build_path(rules, "A"), 20_000, 3, 0.8)
    ids = [s.id for s in raw.stages]

    def corr(a: str, b: str) -> float:
        return float(np.corrcoef(raw.pro[ids.index(a)], raw.pro[ids.index(b)])[0, 1])

    assert corr("H1", "S1") > 0.5  # first gates share the national swing
    assert abs(corr("H2", "S2")) < 0.03  # later gates draw their own swing
