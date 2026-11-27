# SPDX-FileCopyrightText: 2026 Justin Stanley
# SPDX-License-Identifier: MIT
"""Pivot list at the binding gate: ordering, length, members included, and neutral wording."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest

from impsolver.cli import PIVOT_HEADING, main, render_evaluation
from impsolver.deterministic import PIVOT_CAP, PIVOT_EXTRA, evaluate
from impsolver.model import RuleSet
from impsolver.portfolio import Loaded, load, solve
from impsolver.report import render
from tests.conftest import make_comp, make_prep
from tests.test_portfolio import c, pf

REPO = Path(__file__).resolve().parents[1]
FORBIDDEN = (
    "target these",
    "targets",
    "targeting",
    "pressure",
    "recommend",
    "persuade",
    "lobby",
    "should",
)


def _m(mid: str, party: str, p: float | None = None, **kw: Any) -> dict[str, Any]:
    d: dict[str, Any] = {"id": mid, "name": f"Name {mid}", "party": party, **kw}
    if p is not None:
        d["p_pro"] = {"*": p}
    return d


def _senate(n_pro: int = 50) -> list[dict[str, Any]]:
    return [_m(f"S{i:03d}", "D") for i in range(n_pro)] + [
        _m(f"S{i:03d}", "R") for i in range(n_pro, 100)
    ]


def test_house_pivots_ordered_by_p_then_id(rules: RuleSet) -> None:
    # 214 PRO; 221 R with distinct p for a few. Need 218 of 435: short 4 at the minimum.
    house = [_m(f"D{i:03d}", "D") for i in range(214)]
    special = {"R005": 0.6, "R002": 0.6, "R010": 0.4, "R000": 0.01}
    house += [_m(f"R{i:03d}", "R", special.get(f"R{i:03d}")) for i in range(221)]
    prep = make_prep(
        rules,
        make_comp(house, _senate(70)),
        committee_reports=True,
        overrides={"R007": {"*": 0.7}},
    )
    art = evaluate(prep).articles[0]
    assert art.binding_gate == "H2"
    gate = next(g for g in art.gates if g.stage == "H2")
    assert gate.short_at_min == 4
    assert len(art.pivots) == 4 + PIVOT_EXTRA
    ids = [m.id for m in art.pivots]
    assert ids[:4] == ["R007", "R002", "R005", "R010"]  # 0.7, then 0.6 tie by id, then 0.4
    ps = [m.p for m in art.pivots]
    assert ps == sorted(ps, reverse=True)
    assert art.pivots[0].source == "override"
    assert art.pivots[1].source == "member"
    assert art.pivots[-1].source == "party_prior"
    assert "R000" not in ids
    assert all(m.bloc == "R" for m in art.pivots)
    assert art.pivots[0].name == "Name R007"


def test_short_zero_gives_extra_only(rules: RuleSet) -> None:
    prep = make_prep(
        rules,
        make_comp({"D": 300, "R": 135}, {"D": 70, "R": 30}),
        party_priors={"D": {"*": 0.95}, "R": {"*": 0.5}},
        committee_reports=True,
    )
    art = evaluate(prep).articles[0]
    gate = next(g for g in art.gates if g.stage == art.binding_gate)
    assert gate.short_at_min == 0
    assert len(art.pivots) == PIVOT_EXTRA


def test_large_shortfall_is_capped(rules: RuleSet) -> None:
    # Senate: 40 D PRO, 20 R uncertain, 40 R CON. S1 is contested; S2 needs 67, short 27.
    senate = [_m(f"D{i:02d}", "D") for i in range(40)]
    senate += [_m(f"U{i:02d}", "R", 0.5) for i in range(20)]
    senate += [_m(f"R{i:02d}", "R") for i in range(40)]
    prep = make_prep(rules, make_comp({"D": 300, "R": 135}, senate), committee_reports=True)
    art = evaluate(prep).articles[0]
    assert art.binding_gate == "S2"
    gate = next(g for g in art.gates if g.stage == "S2")
    assert gate.short_at_min == 27
    assert len(art.pivots) == PIVOT_CAP
    ids = [m.id for m in art.pivots]
    # The Senate roster is used at a Senate gate: uncertain members first, then CON by id.
    assert ids == [f"U{i:02d}" for i in range(20)] + [f"R{i:02d}" for i in range(5)]


def test_fewer_eligible_than_wanted_and_absent_excluded(rules: RuleSet) -> None:
    # A 12-seat test Senate: 3 PRO, 3 uncertain, 3 CON, 3 absent. S2 needs 6 of 9: short 3,
    # so 8 are wanted but only the 6 present non-PRO members can be listed.
    senate = [_m(f"D{i}", "D") for i in range(3)]
    senate += [_m(f"U{i}", "R", 0.5) for i in range(3)]
    senate += [_m(f"R{i}", "R") for i in range(3)]
    senate += [_m(f"A{i}", "R", 0.5, attendance="absent") for i in range(3)]
    prep = make_prep(rules, make_comp({"D": 300, "R": 135}, senate), committee_reports=True)
    art = evaluate(prep).articles[0]
    assert art.binding_gate == "S2"
    gate = next(g for g in art.gates if g.stage == "S2")
    assert gate.short_at_min == 3
    assert [m.id for m in art.pivots] == ["U0", "U1", "U2", "R0", "R1", "R2"]


def test_cli_text_lists_pivots_neutrally(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["evaluate", str(REPO / "examples" / "scenario-example.yaml")]) == 0
    out = capsys.readouterr().out
    assert PIVOT_HEADING in out
    assert "R-001" in out
    section = out[out.index(PIVOT_HEADING) :].lower()
    for word in FORBIDDEN:
        assert word not in section, word


def test_render_evaluation_without_pivots(rules: RuleSet) -> None:
    e = evaluate(make_prep(rules, make_comp({"D": 300, "R": 135}, {"D": 47, "R": 53})))
    e.articles[0].pivots = []
    assert PIVOT_HEADING not in render_evaluation(e)


def _votes_section(html: str) -> str:
    m = re.search(
        r'<section class="tabpanel[^"]*" id="panel-votes".*?</section>\s*<section class="tabpanel',
        html,
        re.S,
    )
    assert m is not None
    return m.group(0)


def test_html_pivots_for_scenario_candidates_only() -> None:
    loaded = load(REPO / "examples" / "portfolio-example.yaml")
    res = solve(loaded, joint=False)
    assert set(res.pivots) == set(loaded.preps)
    html = render(res, loaded.pf)
    section = _votes_section(html)
    assert "Members nearest the threshold (by the supplied probabilities)" in section
    for cid, art in res.pivots.items():
        assert cid in section
        assert art.pivots and art.pivots[0].id in section
    text = re.sub(r"<[^>]+>", " ", section).lower()
    for word in FORBIDDEN:
        assert word not in text, word


def test_html_has_no_member_lists_without_scenarios() -> None:
    p = pf([c("a", 0.6), c("b", 0.4)])
    res = solve(Loaded(p, {}, {x.id: x.p or 0 for x in p.candidates}), joint=False)
    assert res.pivots == {}
    html = render(res, p)
    assert "Members nearest the threshold" not in html
    assert "supplied directly; no gate breakdown" in html
