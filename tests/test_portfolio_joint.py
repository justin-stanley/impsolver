# SPDX-FileCopyrightText: 2026 Justin Stanley
# SPDX-License-Identifier: MIT
from pathlib import Path

import pytest

from impsolver.portfolio import run_portfolio

COMP = """schema_version: 1
name: t
as_of: 2027-01-01
bodies:
  house: {seats: 435, party_shorthand: {D: 218, R: 217}}
  senate: {seats: 100, party_shorthand: {D: 50, R: 50}}
"""
SCEN = """schema_version: 1
target: {name: T, office: judge}
rules: %s
composition: comp.yaml
party_priors: {D: {"*": 0.97}, R: {"*": 0.45}}
rho: %s
seed: 1
"""
RULES = "us-federal"


def _write(tmp: Path, cands: str, rho: float = 0.95) -> Path:
    (tmp / "comp.yaml").write_text(COMP)
    (tmp / "s.yaml").write_text(SCEN % (RULES, rho))
    pf = tmp / "pf.yaml"
    pf.write_text(f"""schema_version: 1
start: 2027-01-04
deadline: 2028-12-15
draws: 2000
candidates:
{cands}""")
    return pf


def test_shared_swings_widen_spread(tmp_path: Path) -> None:
    cands = "".join(
        f"  - {{id: c{i}, scenario: s.yaml, house_days: 5, senate_days: 5}}\n" for i in range(4)
    )
    r = run_portfolio(_write(tmp_path, cands))
    d = r.removals_dist
    assert d is not None and d.method == "joint_monte_carlo"
    assert d.spread_ratio > 1.5
    assert sum(d.probabilities) == pytest.approx(1.0)


def test_mixed_portfolio_notes_fixed(tmp_path: Path) -> None:
    cands = (
        "  - {id: a, scenario: s.yaml, house_days: 5, senate_days: 5}\n"
        "  - {id: b, p: 0.5, house_days: 5, senate_days: 5}\n"
    )
    d = run_portfolio(_write(tmp_path, cands)).removals_dist
    assert d is not None and any("fixed-p" in n and "b" in n for n in d.notes)


def test_all_fixed_is_poisson_binomial(tmp_path: Path) -> None:
    cands = (
        "  - {id: a, p: 0.5, house_days: 5, senate_days: 5}\n"
        "  - {id: b, p: 0.5, house_days: 5, senate_days: 5}\n"
    )
    d = run_portfolio(_write(tmp_path, cands)).removals_dist
    assert d is not None and d.method == "poisson_binomial"
    assert d.probabilities == pytest.approx([0.25, 0.5, 0.25])


def test_succession_resolved_per_draw(tmp_path: Path) -> None:
    cands = (
        "  - {id: T, p: 0.4, house_days: 5, senate_days: 5}\n"
        "  - {id: X, p: 0.5, house_days: 5, senate_days: 5,"
        " succession: [{on_removal_of: T, becomes: V}]}\n"
        "  - {id: V, p: 0.9, house_days: 5, senate_days: 5, variant_of: X}\n"
    )
    r = run_portfolio(_write(tmp_path, cands))
    assert r.succession_order == ["T", "X"]
    d = r.removals_dist
    assert d is not None and d.mean == pytest.approx(1.06, abs=0.05)


def test_multi_article_pivots_match_reported_article(tmp_path: Path) -> None:
    """The pivot list and the gate-path row describe the same article."""
    from impsolver.portfolio import deterministic_articles, load

    pf = _write(tmp_path, "  - {id: a, scenario: s.yaml, house_days: 5, senate_days: 5}\n")
    scen = tmp_path / "s.yaml"
    scen.write_text(
        scen.read_text(encoding="utf-8")
        + "articles: [I, II]\nshifts: [{label: two, bloc: R, delta: 2.0, article: II}]\n",
        encoding="utf-8",
    )
    loaded = load(pf)
    assert loaded.gates["a"].article == "II"
    assert deterministic_articles(loaded)["a"].article == "II"
