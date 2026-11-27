# SPDX-FileCopyrightText: 2026 Justin Stanley
# SPDX-License-Identifier: MIT
"""Any-article removal for portfolio candidates with multi-article scenarios."""

from pathlib import Path

import numpy as np
import pytest

from impsolver.deterministic import default_path
from impsolver.paths import path_for
from impsolver.portfolio import load, run_portfolio, solve
from impsolver.prepare import prepare
from impsolver.report import gate_paths
from impsolver.simulate import (
    any_complete,
    p_any_complete,
    p_complete,
    run_raw,
    run_raw_articles,
    simulate_article,
)

COMP = """schema_version: 1
name: t
as_of: 2027-01-01
bodies:
  house: {seats: 435, party_shorthand: {D: 218, R: 217}}
  senate: {seats: 100, party_shorthand: {D: 50, R: 50}}
"""
SCEN = """schema_version: 1
target: {name: Official A, office: judge}
articles: %s
rules: us-federal
composition: comp.yaml
party_priors: {D: {"*": 0.97}, R: {"*": 0.45}}
rho: 0.6
seed: 1
shifts: %s
"""
# Article II is weaker with bloc D and stronger with bloc R, so neither article dominates.
OPPOSING = (
    "[{label: a, bloc: D, delta: -1.0, article: II}, {label: b, bloc: R, delta: 0.3, article: II}]"
)
DRAWS = 3000


def _scen(tmp: Path, shifts: str = "[]", articles: str = "[I, II]") -> Path:
    (tmp / "comp.yaml").write_text(COMP)
    s = tmp / "s.yaml"
    s.write_text(SCEN % (articles, shifts))
    return s


def _pf(tmp: Path, cands: str) -> Path:
    pf = tmp / "pf.yaml"
    pf.write_text(f"""schema_version: 1
start: 2027-01-04
deadline: 2028-12-15
draws: {DRAWS}
candidates:
{cands}""")
    return pf


ONE = "  - {id: a, scenario: s.yaml, house_days: 5, senate_days: 5}\n"


def test_articles_share_random_numbers(tmp_path: Path) -> None:
    prep = prepare(_scen(tmp_path))
    path = path_for(prep.rules, prep.scenario, default_path(prep))
    raws = run_raw_articles(prep, ["I", "II"], path, 2000, 7, prep.scenario.rho)
    assert np.array_equal(raws["I"].complete, raws["II"].complete)
    assert np.array_equal(raws["I"].pro, raws["II"].pro)
    single = run_raw(prep, "I", path, 2000, 7, prep.scenario.rho)
    assert np.array_equal(single.complete, raws["I"].complete)


def test_any_article_is_union_of_coupled_draws(tmp_path: Path) -> None:
    prep = prepare(_scen(tmp_path, OPPOSING))
    path = path_for(prep.rules, prep.scenario, default_path(prep))
    raws = run_raw_articles(prep, ["I", "II"], path, DRAWS, 1, prep.scenario.rho)
    hit = any_complete(raws)
    assert np.array_equal(hit, raws["I"].complete | raws["II"].complete)
    pi, pii = float(raws["I"].complete.mean()), float(raws["II"].complete.mean())
    p = float(hit.mean())
    assert max(pi, pii) < p < pi + pii
    assert p_any_complete(prep, draws=DRAWS, seed=1) == pytest.approx(p)


def test_single_article_matches_p_complete(tmp_path: Path) -> None:
    prep = prepare(_scen(tmp_path, articles="[I]"))
    assert p_any_complete(prep, draws=DRAWS) == p_complete(prep, "I", draws=DRAWS)


def test_load_uses_any_article_and_reports_likeliest(tmp_path: Path) -> None:
    _scen(tmp_path, OPPOSING)
    loaded = load(_pf(tmp_path, ONE))
    prep = loaded.preps["a"]
    pi = p_complete(prep, "I", draws=DRAWS)
    pii = p_complete(prep, "II", draws=DRAWS)
    assert max(pi, pii) < loaded.p0["a"] < pi + pii
    assert loaded.p0["a"] == pytest.approx(p_any_complete(prep, draws=DRAWS))
    best = "I" if pi >= pii else "II"
    assert loaded.gates["a"].article == best
    assert loaded.gates["a"].p_complete == pytest.approx(max(pi, pii))


@pytest.mark.parametrize(("delta", "best"), [(-1.0, "I"), (1.0, "II")])
def test_dominated_article_adds_nothing(tmp_path: Path, delta: float, best: str) -> None:
    _scen(tmp_path, f"[{{label: x, bloc: '*', delta: {delta}, article: II}}]")
    loaded = load(_pf(tmp_path, ONE))
    prep = loaded.preps["a"]
    # Under common random numbers the easier article's wins contain the harder one's.
    assert loaded.p0["a"] == pytest.approx(p_complete(prep, best, draws=DRAWS))
    assert loaded.gates["a"].article == best


def test_explicit_article_keeps_single_article(tmp_path: Path) -> None:
    _scen(tmp_path, OPPOSING)
    cands = "  - {id: a, scenario: s.yaml, article: II, house_days: 5, senate_days: 5}\n"
    loaded = load(_pf(tmp_path, cands))
    prep = loaded.preps["a"]
    assert loaded.p0["a"] == p_complete(prep, "II", draws=DRAWS)
    assert loaded.gates["a"].article == "II"


def test_single_article_scenario_unchanged(tmp_path: Path) -> None:
    _scen(tmp_path, articles="[I]")
    loaded = load(_pf(tmp_path, ONE))
    prep = loaded.preps["a"]
    path = path_for(prep.rules, prep.scenario, default_path(prep))
    sim = simulate_article(prep, "I", path, DRAWS, prep.scenario.seed, prep.scenario.rho)
    assert loaded.p0["a"] == sim.p_complete
    assert loaded.gates["a"] == sim


def test_removals_dist_uses_any_article(tmp_path: Path) -> None:
    _scen(tmp_path, OPPOSING)
    cands = ONE + "  - {id: b, scenario: s.yaml, house_days: 5, senate_days: 5}\n"
    r = run_portfolio(_pf(tmp_path, cands))
    d = r.removals_dist
    assert d is not None and d.method == "joint_monte_carlo"
    assert d.mean == pytest.approx(r.plans[0].expected_removals, abs=0.05)


def test_report_shows_any_article_probability(tmp_path: Path) -> None:
    _scen(tmp_path, OPPOSING)
    loaded = load(_pf(tmp_path, ONE))
    res = solve(loaded, joint=False)
    html = gate_paths(res, loaded.pf)
    assert "removal on any article" in html
    assert f"P(removal) {100 * loaded.p0['a']:.1f}%" in html
    assert f"({100 * loaded.gates['a'].p_complete:.1f}% alone)" in html


def test_match_shift_targets_any_article(tmp_path: Path) -> None:
    from impsolver.portfolio import _match_shift

    _scen(tmp_path, OPPOSING)
    loaded = load(_pf(tmp_path, ONE))
    prep = loaded.preps["a"]
    p0 = loaded.p0["a"]
    # The any-article P0 needs no shift; matching article I alone to it would need one.
    assert _match_shift(prep, None, p0, DRAWS) == 0.0
    assert _match_shift(prep, "I", p0, DRAWS) > 0.0
    target = p0 - 0.1
    shift = _match_shift(prep, None, target, DRAWS)
    assert shift < 0.0
    assert p_any_complete(prep, draws=DRAWS, extra=shift) == pytest.approx(target, abs=0.01)
