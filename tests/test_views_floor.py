# SPDX-FileCopyrightText: 2026 Justin Stanley
# SPDX-License-Identifier: MIT
"""The Floor time tab: lane calendar, day budget, date reasons and left-out numbers."""

import datetime as dt
from pathlib import Path

import pytest

from impsolver.portfolio import Loaded, PortfolioResult, load, solve
from impsolver.report import render
from impsolver.views_floor import (
    budget_table,
    calendar_summary,
    date_reasons,
    drop_numbers_text,
    floor_ready,
    lane_calendar,
    left_out_table,
)
from tests.test_portfolio import c, pf

REPO = Path(__file__).resolve().parents[1]
EXAMPLE = REPO / "examples" / "portfolio-example.yaml"


@pytest.fixture(scope="module")
def loaded() -> Loaded:
    return load(EXAMPLE)


@pytest.fixture(scope="module")
def res(loaded: Loaded) -> PortfolioResult:
    return solve(loaded, joint=False, sensitivities=False)


def test_summary_names_floor_use_and_the_longest_wait(res: PortfolioResult) -> None:
    assert calendar_summary(res.plans[0]) == (
        "4 case(s) across the House lanes and the Senate floor. The Senate floor is used on 54 "
        "of 549 trial days. Longest wait for the floor: official-b, 31 trial days."
    )


def test_lane_calendar_has_a_row_per_resource(loaded: Loaded, res: PortfolioResult) -> None:
    svg = lane_calendar(loaded.pf, res.plans[0], res)
    for row in ("House lane 1", "House lane 2", "Waiting for the floor", "Senate committee"):
        assert f">{row}</text>" in svg
    assert 'style="font-weight:600">Senate floor</text>' in svg
    assert 'role="img"' in svg and "Longest wait for the floor: official-b" in svg
    assert (
        "official-b: ready 2027-03-20, waits 31 trial days for the floor (in use by official-a)"
        in svg
    )
    assert "Senate floor idle 2027-02-23 to 2027-03-26" in svg
    assert "is past the right edge" in svg
    # The whole-window drawing shows the deadline and the recesses of each chamber.
    full = lane_calendar(loaded.pf, res.plans[0], res, full=True)
    assert "deadline 2028-12-15</text>" in full
    assert full.count("House recess") == 3 and full.count("Senate recess") == 2


def test_no_committee_row_without_committee_cases() -> None:
    p = pf([c("a", 0.6), c("b", 0.4)])
    r = solve(Loaded(p, {}, {x.id: x.p or 0 for x in p.candidates}), joint=False)
    assert "Senate committee" not in lane_calendar(p, r.plans[0], r)


def test_budget_table_rows(loaded: Loaded, res: PortfolioResult) -> None:
    html = budget_table(loaded.pf, res.plans[0])
    assert "House lanes (2)" in html
    assert "<td class=num>549</td><td class=num>54</td><td class=num>495</td>" in html
    assert "Trial days include Saturdays." in html


def test_date_reasons_explain_each_date(loaded: Loaded, res: PortfolioResult) -> None:
    s = {x.id: x for x in res.plans[0].slots}
    b = date_reasons(loaded.pf, s["official-b"])
    assert b[0] == (
        "House start Feb 6, 2027, in lane 1: lane 1 became free when official-f's House work ended."
    )
    assert b[1] == "House end Mar 19, 2027: 30 House session days."
    assert b[2] == (
        "Trial start Apr 25, 2027: ready on Mar 20, 2027, but the floor was in use by official-a. "
        "It waited 31 trial days."
    )
    assert b[3] == "Trial end May 12, 2027: 15 trial days, Saturdays included."
    assert b[-1] == "Chance: 14.5% alone, 11.1% as trial 4 in this order."
    cc = date_reasons(loaded.pf, s["official-c"])
    assert any(line.startswith("Senate committee Jan 30, 2027 to Feb 12, 2027") for line in cc)
    assert floor_ready(s["official-c"]) == dt.date(2027, 2, 13)
    f = date_reasons(loaded.pf, s["official-f"])
    assert f[0].endswith("the window opens that day.") and f[-1].startswith(
        "Chance: 45.0%, the same"
    )


def test_left_out_numbers_in_words(res: PortfolioResult) -> None:
    d = {x.id: x for x in res.dropped}
    assert "Chance 2.0% is under the floor of 5.0%." in drop_numbers_text(d["official-e"])
    text = drop_numbers_text(d["official-d"])
    assert "It cannot run alongside official-c, which the plan keeps." in text
    assert "1.38 with this plan and 1.28 for the best plan without official-c" in text
    table = left_out_table(res)
    assert "LOW_P" in table and "EXCLUDED" in table


def test_no_fit_and_not_selected_sentences() -> None:
    p = pf([c("a", 0.6), c("late", 0.9, house_days=400, senate_days=400)])
    r = solve(Loaded(p, {}, {x.id: x.p or 0 for x in p.candidates}), joint=False)
    late = next(x for x in r.dropped if x.id == "late")
    text = drop_numbers_text(late)
    assert "deadline of" in text and ("days after" in text or "three years" in text)
    assert "Every candidate is in the recommended plan." in left_out_table(
        r.model_copy(update={"dropped": []})
    )


def test_page_uses_the_floor_views(loaded: Loaded, res: PortfolioResult) -> None:
    html = render(res, loaded.pf)
    assert "Day budget" in html and "Why these dates" in html
    assert "Show the whole window to the deadline" in html
    assert "Timeline of House and Senate work per candidate" not in html
