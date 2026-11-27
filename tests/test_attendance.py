# SPDX-FileCopyrightText: 2026 Justin Stanley
# SPDX-License-Identifier: MIT
"""Random attendance in the Monte Carlo (``attendance: random``)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from pydantic import ValidationError

from impsolver.alignment import VVMember, fit_body, missed_votes, to_alignment_body
from impsolver.loader import load_alignment
from impsolver.model import AlignedMember, Alignment, RuleSet
from impsolver.paths import build_path
from impsolver.simulate import chamber_models, run_raw, simulate
from tests import synth
from tests.conftest import REPO, make_comp, make_prep
from tests.test_alignment import _alignment

PATH_A = "A"


def _senators(n_pro: int, n_con: int, **con_extra: Any) -> list[dict[str, Any]]:
    out = [{"id": f"P{i:02d}", "name": f"P {i}", "party": "D"} for i in range(n_pro)]
    out += [{"id": f"C{i:02d}", "name": f"C {i}", "party": "R", **con_extra} for i in range(n_con)]
    return out


def _raw(rules: RuleSet, prep: Any, draws: int = 20_000, seed: int = 0) -> Any:
    return run_raw(prep, "I", build_path(rules, PATH_A), draws, seed, prep.scenario.rho)


def _row(raw: Any, stage: str) -> int:
    return [s.id for s in raw.stages].index(stage)


# ------------------------------------------------------------------ default is unchanged


def test_default_is_fixed_and_bitwise_unchanged(rules: RuleSet) -> None:
    comp = make_comp({"D": 220, "R": 215}, {"D": 50, "R": 50})
    priors = {"D": {"*": 0.9}, "R": {"*": 0.4}}
    base = make_prep(rules, comp, party_priors=priors, seed=3)
    assert base.scenario.attendance == "fixed" and base.scenario.absence_rate == 0.0
    # Random attendance with every rate at zero is the same model and the same draws.
    zero = make_prep(rules, comp, party_priors=priors, seed=3, attendance="random")
    a, b = _raw(rules, base, 5000), _raw(rules, zero, 5000)
    assert np.array_equal(a.pro, b.pro) and np.array_equal(a.passed, b.passed)
    assert (a.present[_row(a, "H2")] == 435).all() and (a.present[_row(a, "S2")] == 100).all()
    assert simulate(base, draws=5000) == simulate(zero, draws=5000)


def test_fixed_attendance_ignores_rates(rules: RuleSet) -> None:
    comp = make_comp({"D": 218, "R": 217}, _senators(50, 50, p_absent=0.5))
    prep = make_prep(rules, comp, absence_rate=0.3)
    assert "absence_rate has no effect unless attendance is random" in prep.warnings
    stages = list(build_path(rules, PATH_A).all_stages)
    models = chamber_models(prep, "I", stages)
    assert set(models) == {"house", "senate"}
    assert all(cm.p_absent is None for cm in models.values())
    raw = _raw(rules, prep, 2000)
    assert (raw.present[_row(raw, "S2")] == 100).all()


# ---------------------------------------------------------------------------- marginals


def test_absence_marginals(rules: RuleSet) -> None:
    comp = make_comp({"D": 300, "R": 135}, {"D": 60, "R": 40})
    prep = make_prep(
        rules,
        comp,
        party_priors={"D": {"*": 0.8}, "R": {"*": 0.3}},
        attendance="random",
        absence_rate=0.1,
        rho=0.5,
    )
    raw = _raw(rules, prep, 40_000)
    h2, s2 = _row(raw, "H2"), _row(raw, "S2")
    assert raw.present[h2].mean() == pytest.approx(435 * 0.9, rel=0.002)
    assert raw.present[s2].mean() == pytest.approx(100 * 0.9, rel=0.005)
    # PRO needs the member to be there and to vote PRO; the two are independent.
    assert raw.pro[h2].mean() == pytest.approx(0.9 * (300 * 0.8 + 135 * 0.3), rel=0.01)
    # One attendance draw covers every gate in a chamber.
    assert np.array_equal(raw.present[_row(raw, "H1")], raw.present[h2])
    assert np.array_equal(raw.present[_row(raw, "S1")], raw.present[s2])


def test_vote_draws_match_fixed_run(rules: RuleSet) -> None:
    comp = make_comp({"D": 218, "R": 217}, {"D": 50, "R": 50})
    priors = {"D": {"*": 0.7}, "R": {"*": 0.2}}
    fixed = _raw(rules, make_prep(rules, comp, party_priors=priors), 5000)
    rand = _raw(
        rules,
        make_prep(rules, comp, party_priors=priors, attendance="random", absence_rate=0.2),
        5000,
    )
    # Absences only remove PRO votes from the same underlying draws.
    assert (rand.pro <= fixed.pro).all() and (rand.pro < fixed.pro).any()


# ----------------------------------------------------------- S2 threshold and quorum


def test_s2_threshold_moves_with_absences(rules: RuleSet) -> None:
    # 66 certain PRO, 34 certain CON: 66 of 100 falls one short of two-thirds.
    def s2(**kw: Any) -> float:
        comp = make_comp({"D": 435}, _senators(66, 34, **kw))
        prep = make_prep(
            rules, comp, party_priors={"D": {"*": 1.0}, "R": {"*": 0.0}}, attendance="random"
        )
        raw = _raw(rules, prep, 20_000)
        return float(raw.passed[_row(raw, "S2")].mean())

    assert s2() == 0.0
    # One CON absent is enough: 66 of 99 is two-thirds. P(at least one of 34 absent).
    assert s2(p_absent=1.0) == 1.0
    assert s2(p_absent=0.02) == pytest.approx(1 - 0.98**34, abs=0.01)


def test_absences_can_break_quorum(rules: RuleSet) -> None:
    comp = make_comp({"D": 435}, _senators(100, 0))
    prep = make_prep(
        rules,
        comp,
        party_priors={"D": {"*": 1.0}},
        attendance="random",
        absence_rate=0.5,
    )
    raw = _raw(rules, prep, 20_000)
    s2 = _row(raw, "S2")
    quorate = raw.present[s2] >= 51
    # Everyone present votes PRO, so S2 passes exactly when there is a quorum.
    assert np.array_equal(raw.passed[s2], quorate)
    assert 0.4 < quorate.mean() < 0.55


def test_majority_gate_counts_only_votes_cast(rules: RuleSet) -> None:
    # H2: 217 PRO vs 218 CON fails; if CON members are always absent PRO wins every draw.
    house = [{"id": f"P{i}", "name": "p", "party": "D"} for i in range(217)]
    house += [{"id": f"C{i}", "name": "c", "party": "R", "p_absent": 1.0} for i in range(218)]
    comp = make_comp(house, {"D": 100})
    priors = {"D": {"*": 1.0}, "R": {"*": 0.0}}
    fixed = _raw(rules, make_prep(rules, comp, party_priors=priors), 1000)
    rand = _raw(rules, make_prep(rules, comp, party_priors=priors, attendance="random"), 1000)
    assert not fixed.passed[_row(fixed, "H2")].any()
    assert not rand.passed[_row(rand, "H2")].any()  # 217 of 217 present but no quorum (218)
    # Keep 1 CON so there is a quorum: 217-1 passes.
    house[-1] = {"id": "C217", "name": "c", "party": "R"}
    comp = make_comp(house, {"D": 100})
    rand = _raw(rules, make_prep(rules, comp, party_priors=priors, attendance="random"), 1000)
    h2 = _row(rand, "H2")
    assert (rand.present[h2] == 218).all() and rand.passed[h2].all()


def test_roster_absent_members_stay_out(rules: RuleSet) -> None:
    senate = _senators(60, 40)
    senate[0]["attendance"] = "absent"
    senate[0]["p_absent"] = 0.0
    prep = make_prep(rules, make_comp({"D": 435}, senate), attendance="random", absence_rate=0.01)
    raw = _raw(rules, prep, 2000)
    assert raw.present[_row(raw, "S2")].max() == 99


# --------------------------------------------------------------------- rate resolution


def _align_with(rates: dict[str, tuple[int, int]]) -> Alignment:
    members = [
        AlignedMember(
            id=mid,
            name=mid,
            party="R",
            bloc="R",
            n_votes=10,
            breaks=0,
            loadings=[0.0],
            n_missed=nm,
            n_possible=npos,
        )
        for mid, (nm, npos) in rates.items()
    ]
    body = {
        "k": 1,
        "n_contested": 10,
        "members": members,
        "bloc_mean_loadings": {"R": [0.0]},
        "bloc_break_rate": {"R": 0.0},
    }
    return Alignment.model_validate(
        {
            "schema_version": 1,
            "encoding": "unsigned_breaks",
            "source": "synthetic",
            "congresses": [119],
            "kappa": 50.0,
            "min_shared": 10,
            "bodies": {"senate": body},
        },
        strict=False,
    )


def test_rate_resolution_order(rules: RuleSet) -> None:
    senate = _senators(0, 3)
    senate[0]["p_absent"] = 0.5  # member value beats the alignment file
    al = _align_with({"C00": (1, 10), "C01": (1, 4), "C02": (0, 0)})
    prep = make_prep(
        rules,
        make_comp({"D": 3}, senate),
        al,
        alignment="x.json",
        attendance="random",
        absence_rate=0.03,
    )
    # C02 has no possible votes, so the scenario default applies.
    assert prep.absence_rates("senate").tolist() == [0.5, 0.25, 0.03]
    assert prep.absence_rates("house").tolist() == [0.03, 0.03, 0.03]


# ------------------------------------------------------------------ alignment fields


def test_missed_votes_counts_not_voting_only() -> None:
    ms = [
        VVMember("A", "A", "house", "XX", 1, 100, {1}),
        VVMember("B", "B", "house", "XX", 2, 200, {2, 3}),  # party switcher
    ]
    rolls = {
        (119, 1): {1: 1, 2: 9},
        (119, 2): {1: 9, 3: 6},
        (119, 3): {1: 7},  # present counts as attending; B was not serving
        (119, 4): {1: 9, 2: 9},
    }
    assert missed_votes(ms, rolls) == [(2, 4), (2, 3)]


def test_alignment_body_without_missed_votes_keeps_none() -> None:
    ms = synth.members(10, 10)
    al = _alignment(ms, synth.votes(ms, 40, np.random.default_rng(0)))
    assert all(m.n_missed is None and m.missed_rate is None for m in al.bodies["house"].members)
    fit = fit_body(ms, synth.votes(ms, 40, np.random.default_rng(1)), {})
    body = to_alignment_body(fit, 5, [(i, 40) for i in range(20)])
    assert body.members[3].n_missed == 3 and body.members[3].missed_rate == 3 / 40


def test_old_alignment_files_still_load(tmp_path: Path) -> None:
    data = json.loads((REPO / "alignment" / "us-116.json").read_text(encoding="utf-8"))
    for b in data["bodies"].values():
        for m in b["members"]:
            m.pop("n_missed", None)
            m.pop("n_possible", None)
    p = tmp_path / "old.json"
    p.write_text(json.dumps(data), encoding="utf-8")
    al = load_alignment(p)
    assert all(m.missed_rate is None for m in al.bodies["house"].members)


def test_committed_alignment_has_missed_votes() -> None:
    al = load_alignment(REPO / "alignment" / "us-119.json")
    rates = [m.missed_rate for b in al.bodies.values() for m in b.members]
    assert all(r is not None and 0.0 <= r <= 1.0 for r in rates)


@pytest.mark.parametrize(("nm", "npos"), [(1, None), (5, 4), (-1, 3)])
def test_aligned_member_rejects_bad_counts(nm: int, npos: int | None) -> None:
    with pytest.raises(ValidationError):
        AlignedMember(
            id="X",
            name="X",
            party="R",
            bloc="R",
            n_votes=1,
            breaks=None,
            loadings=[0.0],
            n_missed=nm,
            n_possible=npos,
        )
