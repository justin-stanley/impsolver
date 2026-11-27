# SPDX-FileCopyrightText: 2026 Justin Stanley
# SPDX-License-Identifier: MIT
import pytest

from impsolver.flips import FlipError, find_flips, parse_constraints
from impsolver.model import RuleSet
from tests.conftest import make_comp, make_prep


@pytest.fixture
def prep(rules: RuleSet):  # type: ignore[no-untyped-def]
    return make_prep(rules, make_comp({"D": 220, "R": 215}, {"D": 55, "R": 45}))


def test_greedy_and_ilp_agree(prep) -> None:  # type: ignore[no-untyped-def]
    g = find_flips(prep, method="greedy")
    i = find_flips(prep, method="ilp")
    assert g.status == i.status == "OK"
    assert g.n_flips == i.n_flips == 12
    assert all(m.chamber == "senate" for m in i.members)


def test_already_passing(rules: RuleSet) -> None:
    prep = make_prep(rules, make_comp({"D": 300, "R": 135}, {"D": 70, "R": 30}))
    assert find_flips(prep, method="ilp").status == "ALREADY_PASSING"


def test_constraints_tightest_wins_and_infeasible(prep) -> None:  # type: ignore[no-untyped-def]
    assert parse_constraints(["R<=10", "R<=5", "D<=3"]) == {"R": 5, "D": 3}
    assert find_flips(prep, method="ilp", constraints=["R<=11"]).status == "INFEASIBLE"
    assert find_flips(prep, method="greedy", constraints=["R<=11"]).status == "INFEASIBLE"
    with pytest.raises(FlipError):
        parse_constraints(["R<5"])


def test_exclude(prep) -> None:  # type: ignore[no-untyped-def]
    r = find_flips(prep, method="ilp", exclude=["R-001", "R-002"])
    assert {"R-001", "R-002"}.isdisjoint({m.id for m in r.members})


def test_absences_never_beat_flips(prep) -> None:  # type: ignore[no-untyped-def]
    base = find_flips(prep, method="ilp")
    r = find_flips(prep, method="ilp", allow_absence=True)
    assert r.n_flips + r.n_absences <= base.n_flips
    assert r.n_absences == 0  # at equal counts a flip beats an absence
    cheap = find_flips(prep, method="ilp", allow_absence=True, absence_cost=0.3)
    assert cheap.n_absences > 0 and cheap.note and "not a recommendation" in cheap.note


def test_absence_needs_ilp(prep) -> None:  # type: ignore[no-untyped-def]
    with pytest.raises(FlipError):
        find_flips(prep, method="greedy", allow_absence=True)


def test_per_gate_stance(rules: RuleSet) -> None:
    # R senators lean toward letting the trial proceed (S1) but against conviction (S2).
    prep = make_prep(
        rules,
        make_comp({"D": 240, "R": 195}, {"D": 45, "R": 55}),
        party_priors={"D": {"*": 0.95}, "R": {"*": 0.05, "S1": 0.5}},
    )
    shared = find_flips(prep, method="ilp")
    per = find_flips(prep, method="ilp", per_gate_stance=True)
    assert per.status == shared.status == "OK"
    assert per.n_flips == shared.n_flips == 22
    assert all(m.gates == ["S1", "S2"] for m in shared.members)
    assert sum(len(m.gates) for m in per.members) == 22 + 5  # 5 more at S1, 22 more at S2


def test_single_gate(prep) -> None:  # type: ignore[no-untyped-def]
    r = find_flips(prep, method="ilp", gate="H2")
    assert r.status == "ALREADY_PASSING"
    with pytest.raises(FlipError):
        find_flips(prep, gate="Z9")


def test_ilp_is_default_and_never_worse_than_greedy(rules: RuleSet) -> None:
    import numpy as np

    rng = np.random.default_rng(0)
    for _ in range(10):
        house = [
            {
                "id": f"H{i}",
                "name": "x",
                "party": "R",
                "p_pro": {"H1": float(rng.uniform(0, 0.95)), "H2": float(rng.uniform(0, 0.95))},
            }
            for i in range(41)
        ]
        sen = [{"id": f"S{i}", "name": "x", "party": "R", "p_pro": {"*": 0.95}} for i in range(9)]
        p = make_prep(rules, make_comp(house, sen))
        d = find_flips(p)
        assert d.method == "ilp"
        assert d.n_flips <= find_flips(p, method="greedy").n_flips


def test_unknown_exclude_and_bloc_rejected(prep) -> None:  # type: ignore[no-untyped-def]
    with pytest.raises(FlipError, match="unknown member"):
        find_flips(prep, exclude=["NOPE"])
    with pytest.raises(FlipError, match="unknown bloc"):
        find_flips(prep, constraints=["Rr<=3"])
