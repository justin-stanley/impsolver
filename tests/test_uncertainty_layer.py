# SPDX-FileCopyrightText: 2026 Justin Stanley
# SPDX-License-Identifier: MIT
"""Simulation detail for the planning page, and how the page words uncertainty."""

from pathlib import Path

import numpy as np
import pytest

from impsolver.deterministic import default_path
from impsolver.paths import path_for
from impsolver.portfolio import load, solve
from impsolver.prepare import prepare
from impsolver.report import removals_sentence, render
from impsolver.simulate import histogram, run_raw, simulate_article
from impsolver.views_votes import count_curve, pct

REPO = Path(__file__).resolve().parents[1]
SCEN = REPO / "examples" / "scenario-cabinet-a.yaml"
DRAWS = 4000


def _sims():  # type: ignore[no-untyped-def]
    prep = prepare(str(SCEN))
    path = path_for(prep.rules, prep.scenario, default_path(prep))
    args = (prep, "I", path, DRAWS, prep.scenario.seed, prep.scenario.rho)
    return prep, path, simulate_article(*args), simulate_article(*args, detail=True)


def test_detail_changes_no_result() -> None:
    _, _, plain, detail = _sims()
    assert plain.p_complete == detail.p_complete
    for a, b in zip(plain.gates, detail.gates, strict=True):
        assert (a.p_reached, a.p_pass_given_reached, a.pro_count) == (
            b.p_reached,
            b.p_pass_given_reached,
            b.pro_count,
        )
        assert a.pro_hist is None and a.decisive_share is None and a.n_reached is None


def test_histogram_covers_the_draws_that_reach_the_gate() -> None:
    _, _, _, detail = _sims()
    for g in detail.gates:
        assert g.pro_hist is not None and g.n_reached is not None
        assert sum(g.pro_hist.counts) == g.n_reached == round(g.p_reached * DRAWS)
        assert g.pro_hist.counts[0] > 0 and g.pro_hist.counts[-1] > 0
        assert g.pass_se is not None and 0 <= g.pass_se < 0.02
        assert g.present_count is None  # fixed attendance
    assert histogram(np.array([], dtype=np.int64)).counts == []
    h = histogram(np.array([3, 5, 5], dtype=np.int64))
    assert (h.start, h.counts) == (3, [1, 0, 2])


def test_decisive_share_matches_a_direct_count() -> None:
    prep, path, _, detail = _sims()
    raw = run_raw(prep, "I", path, DRAWS, prep.scenario.seed, prep.scenario.rho, decisive=True)
    assert raw.decisive is not None
    s2 = next(g for g in detail.gates if g.stage == "S2")
    k = [st.id for st in raw.stages].index("S2")
    assert s2.decisive_share is not None and len(s2.decisive_share) == 100
    # Two thirds of 100: a PRO voter is decisive when the count is exactly 67, anyone else when
    # it is 66. Summing over members gives 67 per draw at 67 and 34 per draw at 66.
    at67 = int((raw.pro[k] == 67).sum())
    at66 = int((raw.pro[k] == 66).sum())
    assert int(raw.decisive["S2"].sum()) == 67 * at67 + 34 * at66
    assert all(0 <= x <= 1 for x in s2.decisive_share)


def test_percentages_round_to_what_the_error_supports() -> None:
    assert pct(0.3968) == "39.7%"
    assert pct(0.3968, 0.0083) == "40%"
    assert pct(0.3968, 0.004) == "39.7%"


def test_removals_sentence() -> None:
    assert removals_sentence([0.1854, 0.4152, 0.28, 0.0884, 0.031]) == (
        "Most likely 1. None in 19 of 100 runs. 3 or more in 12 of 100."
    )
    assert removals_sentence([0.7, 0.3]) == "Most likely 0."
    assert removals_sentence([]) == ""


@pytest.fixture(scope="module")
def page() -> str:
    loaded = load(REPO / "examples" / "portfolio-example.yaml")
    return render(solve(loaded), loaded.pf)


def test_page_words_uncertainty(page: str) -> None:
    assert "How often the count gets there" in page
    assert "about 40 in 100 get there" in page and "about 60 in 100 fall short" in page
    assert "Inputs are taken as exact" in page
    assert "standard error 0.6 points" in page
    assert '<span class="src simulated">simulated</span>' in page
    assert '<span class="src counted">counted</span>' in page
    assert '<span class="src supplied">supplied</span>' in page
    assert "Decisive share</th>" in page
    assert "Most likely 1. None in 19 of 100 runs." in page
    assert "seed 21, rho 0.6" in page and "5,000 draws per scenario case" in page
    assert "no range is drawn around them" in page


def test_curve_needs_detail() -> None:
    loaded = load(REPO / "examples" / "portfolio-example.yaml")
    res = solve(loaded, joint=False, sensitivities=False)
    g = res.gates["official-a"].gates[3]
    sim = res.gate_paths["official-a"].gates[3]
    assert 'role="img"' in count_curve(g, sim)
    assert count_curve(g, sim.model_copy(update={"pro_hist": None})) == ""
    assert count_curve(g, None) == ""
