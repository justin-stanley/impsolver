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


# Counts from the existing flip tests, recorded on PuLP 2.9 (bundled CBC) before the PuLP 4 port
# (issue #9). The port must not move any of them.
PINNED_FLIPS = [
    ("plain", {}, "OK", 12, 0),
    ("cap R<=11", {"constraints": ["R<=11"]}, "INFEASIBLE", 0, 0),
    ("exclude", {"exclude": ["R-001", "R-002"]}, "OK", 12, 0),
    ("absence", {"allow_absence": True}, "OK", 12, 0),
    ("cheap absence", {"allow_absence": True, "absence_cost": 0.3}, "OK", 0, 18),
    ("H2 only", {"gate": "H2"}, "ALREADY_PASSING", 0, 0),
]
PINNED_RANDOM_ILP = [19, 18, 18, 19, 20, 21, 20, 21, 21, 19]


@pytest.mark.parametrize(("label", "kw", "status", "n_flips", "n_absences"), PINNED_FLIPS)
def test_pinned_flip_counts(  # type: ignore[no-untyped-def]
    prep, label: str, kw: dict[str, object], status: str, n_flips: int, n_absences: int
) -> None:
    r = find_flips(prep, method="ilp", **kw)  # type: ignore[arg-type]
    assert (r.status, r.n_flips, r.n_absences) == (status, n_flips, n_absences), label


def test_pinned_flip_counts_per_gate_and_random(rules: RuleSet) -> None:
    import numpy as np

    prep = make_prep(
        rules,
        make_comp({"D": 240, "R": 195}, {"D": 45, "R": 55}),
        party_priors={"D": {"*": 0.95}, "R": {"*": 0.05, "S1": 0.5}},
    )
    for per_gate in (False, True):
        r = find_flips(prep, per_gate_stance=per_gate)
        assert (r.status, r.n_flips, r.n_absences) == ("OK", 22, 0)
    rng = np.random.default_rng(0)
    got = []
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
        counts = {find_flips(p, per_gate_stance=pg).n_flips for pg in (False, True)}
        assert len(counts) == 1
        got.append(counts.pop())
    assert got == PINNED_RANDOM_ILP


def test_cbc_solver_selection(monkeypatch: pytest.MonkeyPatch) -> None:
    import pulp

    from impsolver import flips

    # PuLP < 4 bundles CBC as PULP_CBC_CMD; prefer it when present.
    monkeypatch.setattr(pulp, "PULP_CBC_CMD", lambda msg: ("bundled", msg), raising=False)
    assert flips._cbc() == ("bundled", False)
    monkeypatch.delattr(pulp, "PULP_CBC_CMD")

    class NoCbc:
        def __init__(self, **kw: object) -> None:
            pass

        def available(self) -> bool:
            return False

    monkeypatch.setattr(pulp, "COIN_CMD", NoCbc)
    with pytest.raises(FlipError, match=r"pulp\[cbc\]"):
        flips._cbc()


def test_optimal_status_across_pulp_versions() -> None:
    from types import SimpleNamespace

    import pulp

    from impsolver.flips import _optimal

    assert _optimal(1) and not _optimal(-1)  # PuLP < 4 returns the status code
    if not hasattr(pulp, "LpSolveStatus"):
        pytest.skip("PuLP < 4 has no LpSolveStats")
    s = pulp.LpSolveStatus
    assert _optimal(SimpleNamespace(status=s.Optimal, has_solution=True))
    assert _optimal(SimpleNamespace(status=s.GapLimit, has_solution=True))
    assert not _optimal(SimpleNamespace(status=s.GapLimit, has_solution=False))
    assert not _optimal(SimpleNamespace(status=s.Infeasible, has_solution=False))
