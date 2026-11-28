# SPDX-FileCopyrightText: 2026 Justin Stanley
# SPDX-License-Identifier: MIT
"""The Votes tab: ladder, tally strip, bloc table, member strip and threshold steps."""

import re
from pathlib import Path

import pytest

from impsolver.portfolio import Loaded, PortfolioResult, load, solve
from impsolver.report import render
from impsolver.views_votes import (
    in_100,
    member_list,
    required_with_absences,
    tally_summary,
    threshold_steps,
    votes_tab,
)
from tests.test_portfolio import c, pf

REPO = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def res() -> PortfolioResult:
    return solve(
        load(REPO / "examples" / "portfolio-example.yaml"), joint=False, sensitivities=False
    )


def _gate(res: PortfolioResult, cid: str, stage: str):  # type: ignore[no-untyped-def]
    case = res.gates[cid]
    return case, next(g for g in case.gates if g.stage == stage)


def test_frequency_wording() -> None:
    assert in_100(0.2786) == "about 28 in 100"
    assert in_100(0.001) == "fewer than 1 in 100"
    assert in_100(0.999) == "more than 99 in 100"
    assert in_100(0.0) == "about 0 in 100" and in_100(1.0) == "about 100 in 100"


def test_tally_summary_states_count_threshold_and_gap(res: PortfolioResult) -> None:
    _, s2 = _gate(res, "official-a", "S2")
    assert tally_summary(s2) == (
        "47 counted PRO, 53 uncertain, 0 counted CON; 67 needed; 20 short at the minimum."
    )
    _, h1 = _gate(res, "official-a", "H1")
    assert "2 vacant" in tally_summary(h1)


def test_threshold_moves_with_absences(res: PortfolioResult) -> None:
    _, s2 = _gate(res, "official-a", "S2")
    assert [required_with_absences(s2, k) for k in range(4)] == [67, 66, 66, 65]
    _, s1 = _gate(res, "official-a", "S1")
    # Fail direction: a tie defeats the motion, so half of the votes is enough for PRO.
    assert [required_with_absences(s1, k) for k in range(3)] == [50, 50, 49]
    assert "PRO votes needed" in threshold_steps(s2)


def test_member_list_folds_identical_rows_and_marks_the_pivot(res: PortfolioResult) -> None:
    case, s2 = _gate(res, "official-a", "S2")
    html = member_list(s2, case)
    assert "R-001 to R-053: 53 members. Rank pivot: R-020, vote 67." in html
    assert "<td class=num>48 to 100</td>" in html
    assert html.count("class=pivotrow") == 1
    # Every member is still named inside the folded row.
    assert "R-053 R member 53" in html and "D-001 D member 1" in html


def test_page_has_tabs_ladder_and_one_panel_per_gate(res: PortfolioResult) -> None:
    loaded = load(REPO / "examples" / "portfolio-example.yaml")
    html = render(res, loaded.pf)
    assert html.count('role="tab"') == 4 and html.count('role="tabpanel"') == 4
    assert (
        'id="tab-votes" data-tab="votes" aria-controls="panel-votes" aria-selected="true"' in html
    )
    tab = votes_tab(res)
    assert tab.count('class="gatebtn"') == 10 and tab.count('class="gatepanel') == 10
    # The binding gate is the one open at first, and it is labelled in words, not by colour.
    assert re.search(r'data-gate="S2" aria-pressed="true"[^>]*><b>S2<span class="tag">binding', tab)
    assert "then passes: 40% (under 50%)" in tab
    assert "Optional, after conviction" in tab
    assert "Two thirds of the members present. With 100 present, PRO needs 67." in tab
    # Each drawing carries a text alternative.
    assert tab.count("<svg") - tab.count('aria-hidden="true"') * 4 == tab.count('role="img"')
    assert "P 60.0% supplied directly; no gate breakdown" in tab


def test_page_opens_on_floor_time_without_scenarios() -> None:
    p = pf([c("a", 0.6), c("b", 0.4)])
    r = solve(Loaded(p, {}, {x.id: x.p or 0 for x in p.candidates}), joint=False)
    html = render(r, p)
    assert (
        'id="tab-floor" data-tab="floor" aria-controls="panel-floor" aria-selected="true"' in html
    )


def test_user_text_in_the_votes_tab_is_escaped() -> None:
    p = pf([c("<i>x</i>", 0.6)])
    r = solve(Loaded(p, {}, {x.id: x.p or 0 for x in p.candidates}), joint=False)
    tab = votes_tab(r)
    assert "<i>x</i>" not in tab and "&lt;i&gt;x&lt;/i&gt;" in tab


def test_plan_buttons_and_scroll_regions_are_reachable(res: PortfolioResult) -> None:
    html = render(res, load(REPO / "examples" / "portfolio-example.yaml").pf)
    # The plan picker is a group of toggle buttons, not tabs without a tablist.
    assert '<div class="tabs" role="group" aria-label="Plans">' in html
    assert 'data-plan="plan1" aria-controls="plan1" aria-pressed="true"' in html
    # Regions that can scroll sideways take keyboard focus.
    assert '<div class="scrollx">' not in html and '<div class="scrollx" tabindex="0">' in html
    assert "<th></th>" not in html
