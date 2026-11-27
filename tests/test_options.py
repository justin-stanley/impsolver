"""Scenario options added after the audit: tie-break, national swing, per-chamber alignment."""

import numpy as np
import pytest

from impsolver.deterministic import evaluate
from impsolver.flips import find_flips
from impsolver.model import RuleSet
from impsolver.paths import build_path
from impsolver.simulate import chamber_models, run_raw
from tests import synth
from tests.conftest import make_comp, make_prep
from tests.test_alignment import _alignment


def _tied(rules: RuleSet, tie: str, p: float = 0.99):  # type: ignore[no-untyped-def]
    return make_prep(
        rules,
        make_comp({"D": 300, "R": 135}, {"D": 50, "R": 50}),
        party_priors={"D": {"*": p}, "R": {"*": 1 - p}},
        senate_tie_break=tie,
    )


@pytest.mark.parametrize(
    ("tie", "s1", "s3"),
    [("none", "PASS", "FAIL"), ("pro", "PASS", "PASS"), ("con", "FAIL", "FAIL")],
)
def test_senate_tie_break_deterministic(rules: RuleSet, tie: str, s1: str, s3: str) -> None:
    gates = {g.stage: g.verdict for g in evaluate(_tied(rules, tie)).articles[0].gates}
    assert (gates["S1"], gates["S3"]) == (s1, s3)
    assert gates["S2"] == "FAIL"  # two-thirds is unaffected


def test_senate_tie_break_ilp_and_simulation_agree(rules: RuleSet) -> None:
    assert find_flips(_tied(rules, "none"), gate="S1").status == "ALREADY_PASSING"
    r = find_flips(_tied(rules, "con"), gate="S1")
    assert r.status == "OK" and r.n_flips == 1
    for tie, expect in (("none", 1.0), ("con", 0.0)):
        prep = _tied(rules, tie, p=1.0)  # certain votes: an exact 50-50 tie every draw
        raw = run_raw(prep, "I", build_path(rules, "A"), 2000, 0, 0.0)
        s1 = [s.id for s in raw.stages].index("S1")
        assert raw.passed[s1].mean() == pytest.approx(expect)


def test_national_swing_links_chambers(rules: RuleSet) -> None:
    def corr(national: bool) -> float:
        prep = make_prep(
            rules,
            make_comp({"D": 218, "R": 217}, {"D": 50, "R": 50}),
            party_priors={"D": {"*": 0.9}, "R": {"*": 0.3}},
            rho=0.8,
            national_swing=national,
        )
        raw = run_raw(prep, "I", build_path(rules, "A"), 20_000, 3, 0.8)
        ids = [s.id for s in raw.stages]
        return float(np.corrcoef(raw.pro[ids.index("H2")], raw.pro[ids.index("S2")])[0, 1])

    assert abs(corr(False)) < 0.05
    assert corr(True) > 0.5


def test_senate_alignment_off_by_default(rules: RuleSet) -> None:
    ms = synth.members(30, 30)
    al = _alignment(ms, synth.votes(ms, 100, np.random.default_rng(0)))
    al.bodies["senate"] = al.bodies["house"]
    house = [{"id": m.id, "name": m.name, "party": m.party} for m in ms]
    comp = make_comp(house, [{"id": m.id, "name": m.name, "party": m.party} for m in ms[:50]] + [])
    stages = list(build_path(rules, "A").stages)
    default = chamber_models(make_prep(rules, comp, al, alignment="x.json"), "I", stages)
    opted = chamber_models(
        make_prep(
            rules,
            comp,
            al,
            alignment="x.json",
            alignment_chamber_weight={"house": 1.0, "senate": 1.0},
        ),
        "I",
        stages,
    )
    assert default["house"].F is not None and default["senate"].F is None
    assert opted["senate"].F is not None


def test_partial_chamber_weight_keeps_senate_default(rules: RuleSet) -> None:
    prep = make_prep(
        rules,
        make_comp({"D": 1}, {"D": 1}),
        alignment="x.json",
        party_priors={"D": {"*": 0.5}},
        alignment_chamber_weight={"house": 0.5},
    )
    assert prep.scenario.alignment_chamber_weight == {"house": 0.5, "senate": 0.0}
