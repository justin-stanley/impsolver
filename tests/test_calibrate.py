from pathlib import Path

import numpy as np
import pytest

from impsolver.calibrate import calibrate
from impsolver.loader import load_alignment, load_crossovers
from impsolver.model import Alignment, CrossoverFixture
from tests import synth
from tests.test_alignment import _alignment

REPO = Path(__file__).resolve().parents[1]


def test_synthetic_crossers_are_aligned() -> None:
    ms = synth.members(80, 60)
    crossers = [f"R{i:03d}" for i in range(8)]
    a = _alignment(ms, synth.votes(ms, 300, np.random.default_rng(2), groups=[(crossers, 0.3)]))
    a = Alignment.model_validate({**a.model_dump(), "congresses": [116]})
    fx = CrossoverFixture.model_validate(
        {
            "schema_version": 1,
            "case": "synthetic",
            "history_congress": 116,
            "party": "R",
            "bodies": {
                "house": {
                    "crossed": [{"id": c, "name": c} for c in crossers]
                    + [{"id": None, "name": "not seated"}]
                }
            },
        }
    )
    c = calibrate(fx, a, min_votes=100, permutations=500)
    b = c.bodies[0]
    assert b.permutation_p < 0.01 and b.crossed_break_rate > b.party_break_rate
    assert b.unmatched == ["not seated"] and b.beta is not None and b.beta > 0


def test_real_2021_crossovers() -> None:
    al = REPO / "alignment" / "us-116.json"
    if not al.exists():
        pytest.skip("alignment/us-116.json not generated (needs Voteview data)")
    fx = load_crossovers(REPO / "fixtures" / "members" / "trump-2021-crossovers.yaml")
    c = calibrate(fx, load_alignment(al), permutations=5000, seed=0)
    house, senate = (next(b for b in c.bodies if b.body == n) for n in ("house", "senate"))
    assert house.n_crossed == 8 and set(house.unmatched) == {"Peter Meijer", "David Valadao"}
    assert house.crossed_mean_alignment == pytest.approx(0.33, abs=0.03)
    assert house.random_mean_alignment == pytest.approx(0.20, abs=0.03)
    assert house.permutation_p < 0.05
    assert house.beta == pytest.approx(1.34, abs=0.1)
    assert senate.permutation_p > 0.5
    assert senate.beta == pytest.approx(0.89, abs=0.1)
