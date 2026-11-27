# SPDX-FileCopyrightText: 2026 Justin Stanley
# SPDX-License-Identifier: MIT
"""The report contract: lanes, date reasons, budgets, drop numbers and gate details."""

import datetime as dt
import json
from pathlib import Path

from impsolver.cli import SCHEMAS
from impsolver.contract import REPORT_SCHEMA_VERSION, days_between, rule_sentence
from impsolver.deterministic import default_path
from impsolver.paths import path_for
from impsolver.portfolio import Loaded, PortfolioResult, load, make_calendars, solve
from impsolver.prepare import prepare
from tests.test_portfolio import c, pf

REPO = Path(__file__).resolve().parents[1]
EXAMPLE = REPO / "examples" / "portfolio-example.yaml"


def _solve(cands, **kw):  # type: ignore[no-untyped-def]
    p = pf(cands, **kw)
    return p, solve(Loaded(p, {}, {x.id: x.p or 0 for x in p.candidates}), joint=False)


def _example() -> PortfolioResult:
    return solve(load(EXAMPLE), joint=False, sensitivities=False)


def test_version_meta_and_inputs() -> None:
    res = _example()
    assert res.schema_version == REPORT_SCHEMA_VERSION == 2
    assert res.meta is not None and res.meta.portfolio_file == "portfolio-example.yaml"
    assert res.meta.scenarios["official-a"].file == "scenario-cabinet-a.yaml"
    assert res.inputs is not None and res.inputs.house_concurrency == 2
    # The page must be drawable from the JSON alone.
    data = json.loads(res.model_dump_json())
    assert data["inputs"]["calendar"]["house"]["recess"]
    assert PortfolioResult.model_validate(data).schema_version == 2
    assert "report" in SCHEMAS


def test_lanes_never_overlap_and_match_concurrency() -> None:
    res = _example()
    for plan in res.plans:
        by_lane: dict[int, list[tuple[dt.date, dt.date]]] = {}
        for s in plan.slots:
            assert s.house_lane in (1, 2)
            by_lane.setdefault(s.house_lane, []).append((s.house_start, s.house_end))
        for spans in by_lane.values():
            spans.sort()
            assert all(a[1] < b[0] for a, b in zip(spans, spans[1:], strict=False))


def test_example_plan_reasons_waits_and_budget() -> None:
    plan = _example().plans[0]
    s = {x.id: x for x in plan.slots}
    assert plan.order == ["official-f", "official-c", "official-a", "official-b"]
    assert s["official-f"].house_start_reason == "window_start"
    assert (s["official-b"].house_start_reason, s["official-b"].house_start_after) == (
        "lane_free",
        "official-f",
    )
    # official-b is ready on Mar 20 but the floor is trying official-a until Apr 24.
    assert s["official-b"].ready == dt.date(2027, 3, 20)
    assert (s["official-b"].trial_start_reason, s["official-b"].trial_start_after) == (
        "floor_busy",
        "official-a",
    )
    assert s["official-b"].wait_trial_days == 31
    assert s["official-a"].wait_trial_days == 0 and s["official-a"].trial_start_reason == "ready"
    # official-c goes through a Senate committee first.
    assert s["official-c"].committee_start == dt.date(2027, 1, 30)
    assert s["official-c"].committee_end == dt.date(2027, 2, 12)
    assert [x.house_days for x in plan.slots] == [25, 20, 40, 30]
    assert [x.trial_days for x in plan.slots] == [12, 2, 25, 15]
    budget = {b.resource: (b.available, b.used) for b in plan.budget}
    assert budget == {
        "house_lanes": (860, 115),
        "senate_committee": (458, 10),
        "senate_floor": (549, 54),
    }
    assert all(x.slack_days is not None and x.slack_days > 0 for x in plan.slots)


def test_days_between_counts_session_days() -> None:
    p, _ = _solve([c("a", 0.5)])
    cals = make_calendars(p)
    d = p.start
    assert days_between(cals.house, d, d - dt.timedelta(days=1)) == 0
    week = days_between(cals.house, d, d + dt.timedelta(days=6))
    assert week == sum(
        1 for i in range(7) if (d + dt.timedelta(days=i)).weekday() in p.calendar.house.weekdays
    )


def test_drop_numbers_for_each_reason() -> None:
    res = _example()
    d = {x.id: x for x in res.dropped}
    assert d["official-e"].numbers == {"p": 0.02, "p_floor": 0.05}
    ex = d["official-d"].numbers
    assert ex["by"] == ["official-c"]
    assert ex["value"] == res.plans[0].expected_removals
    assert isinstance(ex["swap_value"], float) and ex["swap_value"] < ex["value"]


def test_no_fit_reports_the_earliest_finish() -> None:
    _, res = _solve([c("a", 0.6), c("late", 0.9, house_days=400, senate_days=400)])
    d = {x.id: x for x in res.dropped}
    assert d["late"].reason == "NO_FIT"
    n = d["late"].numbers
    assert n["deadline"] is not None
    if n["earliest_end"] is not None:
        assert isinstance(n["days_over"], int) and n["days_over"] > 0
        assert str(n["earliest_end"]) > str(n["deadline"])


def test_sensitivity_rows_carry_schedules() -> None:
    res = solve(load(EXAMPLE), joint=False, sensitivities=False)
    for row in res.sensitivity:
        assert [s.id for s in row.slots] == res.plans[0].order
        assert all(s.house_lane is not None for s in row.slots)
    short = next(r for r in res.sensitivity if r.label == "durations x0.75")
    long = next(r for r in res.sensitivity if r.label == "durations x1.25")
    assert short.slots[-1].trial_end < res.plans[0].slots[-1].trial_end < long.slots[-1].trial_end


def test_gate_details_agree_with_the_deterministic_bounds() -> None:
    res = _example()
    for cid, art in res.pivots.items():
        case = res.gates[cid]
        assert case.article == art.article and case.path == art.path
        for g, det in zip(case.gates, art.gates, strict=True):
            n = len(case.rosters[g.chamber].ids)
            assert len(g.p) == len(g.source) == len(g.cls) == n
            assert g.stage == det.stage and g.required == det.required
            assert sum(b.pro for b in g.blocs) == det.pro_min == g.cls.count("P")
            assert sum(b.uncertain for b in g.blocs) == det.uncertain == g.cls.count("U")
            assert sum(b.seats for b in g.blocs) + g.vacancies == g.seats
            assert g.present == n - g.cls.count("A")
    s2 = next(g for g in res.gates["official-a"].gates if g.stage == "S2")
    assert s2.required == 67 and s2.rank_pivot == "R-020"
    assert s2.rule.sentence == "Two thirds of the members present. With 100 present, PRO needs 67."
    assert {b.bloc: b.expected_pro for b in s2.blocs} == {"R": 15.9, "D": 43.65, "I": 1.9}


def test_rule_sentences_cover_each_rule_kind() -> None:
    prep = prepare(str(REPO / "examples" / "scenario-cabinet-a.yaml"))
    path = path_for(prep.rules, prep.scenario, default_path(prep))
    st = {s.id: s for s in path.all_stages}
    assert "PRO votes nay" in rule_sentence(st["H1"], 433, 433, 217, "none")
    assert "A tie defeats the motion" in rule_sentence(st["S1"], 100, 100, 50, "none")
    assert "PRO votes yea" in rule_sentence(st["H2"], 433, 433, 217, "none")
    assert "go to CON" in rule_sentence(st["S3"], 100, 100, 51, "con")
    assert "tie defeats" not in rule_sentence(st["S3"], 100, 100, 50, "pro")
