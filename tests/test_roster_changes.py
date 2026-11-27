# SPDX-FileCopyrightText: 2026 Justin Stanley
# SPDX-License-Identifier: MIT
"""Seat changes during a portfolio window (``roster_changes``). Placeholder members only."""

import datetime as dt
import random
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from impsolver.cli import main
from impsolver.model import Body, Composition, Member, Portfolio, RosterChange
from impsolver.portfolio import (
    Loaded,
    PortfolioError,
    _dominates,
    _slack,
    apply_changes,
    epoch_of,
    load,
    make_ctx,
    search,
    solve,
)
from impsolver.report import render

D = dt.date

# The Senate splits 66 pro / 34 con. S2 needs two thirds of those present: 66 of 100 falls one
# short (67 needed), 66 of 99 is exactly two thirds and convicts.
COMP = """schema_version: 1
name: placeholder
as_of: 2027-01-01
bodies:
  house: {seats: 435, party_shorthand: {A: 300, B: 135}}
  senate: {seats: 100, party_shorthand: {A: 66, B: 34}}
"""
SCEN = """schema_version: 1
target: {name: Official X, office: judge}
rules: us-federal
composition: comp.yaml
party_priors: {A: {"*": 1.0}, B: {"*": 0.0}}
seed: 1
"""


def _write(tmp: Path, changes: str, extra: str = "") -> Path:
    (tmp / "comp.yaml").write_text(COMP)
    (tmp / "s.yaml").write_text(SCEN)
    pf = tmp / "pf.yaml"
    # Start Monday 2027-01-04. Two House lanes; five-day phases; trials sit on Saturdays.
    # s2 first: its trial starts Saturday 2027-01-09. filler first: s2's starts 2027-01-15.
    pf.write_text(f"""schema_version: 1
start: 2027-01-04
deadline: 2027-12-17
draws: 200
roster_changes:
{changes}
candidates:
  - {{id: filler, p: 0.5, house_days: 5, senate_days: 5}}
  - {{id: s2, scenario: s.yaml, house_days: 5, senate_days: 5}}
{extra}""")
    return pf


VACATE_CON = "  - {date: 2027-01-13, chamber: senate, vacate: B-001}\n"


def _comp() -> Composition:
    return Composition(
        schema_version=1,
        name="c",
        as_of=D(2027, 1, 1),
        bodies={"senate": Body(seats=3, vacancies=1, party_shorthand={"A": 1, "B": 1})},
    )


def test_change_needs_vacate_or_seat() -> None:
    with pytest.raises(ValidationError):
        RosterChange.model_validate({"date": "2027-01-01", "chamber": "senate"})


def test_apply_changes_vacate_seat_and_replace() -> None:
    new = Member(id="N-1", name="New member", party="A")
    rc = RosterChange.model_validate
    out = apply_changes(
        _comp(),
        [
            rc({"date": "2027-02-01", "chamber": "senate", "seat": new.model_dump()}),
            rc({"date": "2027-03-01", "chamber": "senate", "vacate": "B-001"}),
            rc(
                {
                    "date": "2027-03-01",
                    "chamber": "senate",
                    "vacate": "A-001",
                    "seat": {"id": "N-2", "name": "Second", "party": "B"},
                }
            ),
        ],
        "t",
    )
    s = out.bodies["senate"]
    assert [m.id for m in s.roster] == ["N-1", "N-2"]
    assert s.vacancies == 1 and out.as_of == D(2027, 3, 1)
    assert apply_changes(_comp(), [], "t").name == "c"


@pytest.mark.parametrize(
    ("change", "msg"),
    [
        ({"chamber": "senate", "vacate": "Z-9"}, "does not hold"),
        ({"chamber": "house", "vacate": "A-001"}, "has no house"),
        ({"chamber": "senate", "seat": {"id": "A-001", "name": "x", "party": "A"}}, "already"),
    ],
)
def test_apply_changes_errors(change: dict[str, Any], msg: str) -> None:
    rc = RosterChange.model_validate({"date": "2027-01-01", **change})
    with pytest.raises(PortfolioError, match=msg):
        apply_changes(_comp(), [rc], "t")


def test_apply_changes_needs_a_vacancy() -> None:
    seat = {"id": "N", "name": "n", "party": "A"}
    rc = RosterChange.model_validate({"date": "2027-01-01", "chamber": "senate", "seat": seat})
    two = rc.model_copy(update={"seat": Member(id="M", name="m", party="A")})
    with pytest.raises(PortfolioError, match="no vacant senate seat"):
        apply_changes(_comp(), [rc, two], "t")


def test_epoch_boundary_is_inclusive() -> None:
    dates = (D(2027, 1, 13), D(2027, 2, 1))
    assert epoch_of(dates, D(2027, 1, 12)) == 0
    assert epoch_of(dates, D(2027, 1, 13)) == 1
    assert epoch_of(dates, D(2027, 2, 1)) == 2


def test_vacancy_flips_s2_and_the_schedule(tmp_path: Path) -> None:
    loaded = load(_write(tmp_path, VACATE_CON))
    assert loaded.p0["s2"] == 0.0
    assert loaded.p0_epochs["s2"] == [0.0, 1.0]
    res = solve(loaded)
    assert not any(d.id == "s2" for d in res.dropped)  # best case is P=1, so not LOW_P
    best = res.plans[0]
    assert best.order == ["filler", "s2"]
    assert best.expected_removals == pytest.approx(1.5)
    slot = {s.id: s for s in best.slots}["s2"]
    assert slot.trial_start == D(2027, 1, 15) and slot.epoch == 1 and slot.p == 1.0
    # Trying s2 first puts its trial before the vacancy, under the old roster.
    other = next(p for p in res.plans if p.order[0] == "s2")
    assert other.slots[0].epoch == 0 and other.slots[0].p == 0.0
    assert res.epochs == [D(2027, 1, 13)]
    # The joint distribution simulates s2 against the epoch-1 roster.
    assert res.removals_dist is not None
    assert res.removals_dist.mean == pytest.approx(1.5, abs=0.1)
    html = render(res, loaded.pf)
    assert "roster from 2027-01-13" in html


def test_change_on_trial_start_day_applies(tmp_path: Path) -> None:
    on_day = "  - {date: 2027-01-15, chamber: senate, vacate: B-001}\n"
    res = solve(load(_write(tmp_path, on_day)), joint=False)
    assert res.plans[0].order == ["filler", "s2"]
    assert res.plans[0].slots[1].epoch == 1
    later = "  - {date: 2027-01-16, chamber: senate, vacate: B-001}\n"
    res = solve(load(_write(tmp_path, later)), joint=False)
    assert res.plans[0].expected_removals == pytest.approx(0.5)


def test_new_seat_counts_and_cli_text(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    # Replacing a con senator with a pro one gives 67 of 100.
    swap = (
        "  - {date: 2027-01-13, chamber: senate, vacate: B-001,\n"
        "     seat: {id: N-001, name: Placeholder successor, party: A}}\n"
    )
    pf = _write(tmp_path, swap)
    assert load(pf).p0_epochs["s2"] == [0.0, 1.0]
    assert main(["portfolio", str(pf)]) == 0
    assert "roster from 2027-01-13" in capsys.readouterr().out


def test_validate_checks_every_epoch(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    pf = _write(tmp_path, VACATE_CON)
    assert main(["validate", "--portfolio", str(pf)]) == 0
    bad = _write(tmp_path, "  - {date: 2027-01-13, chamber: senate, vacate: Q-404}\n")
    assert main(["validate", "--portfolio", str(bad)]) != 0
    assert "Q-404" in capsys.readouterr().err
    no_prior = (
        "  - {date: 2027-01-13, chamber: senate, vacate: B-001,\n"
        "     seat: {id: N-001, name: Placeholder, party: C}}\n"
    )
    assert main(["validate", "--portfolio", str(_write(tmp_path, no_prior))]) != 0
    assert "N-001" in capsys.readouterr().err


# ------------------------------------------------------------------ search soundness


def _pf(n: int, rng: random.Random, n_dates: int) -> Portfolio:
    start = D(2027, 1, 4)
    dates = sorted({start + dt.timedelta(days=rng.randint(1, 60)) for _ in range(n_dates)})
    return Portfolio.model_validate(
        {
            "schema_version": 1,
            "start": "2027-01-04",
            "deadline": "2027-05-28",
            "draws": 100,
            "top": 1,
            "house_concurrency": rng.choice([1, 2]),
            "fatigue_delta": rng.choice([-0.2, 0.0, 0.3]),
            "roster_changes": [
                {"date": d.isoformat(), "chamber": "senate", "vacate": "placeholder"} for d in dates
            ],
            "candidates": [
                {
                    "id": f"c{i}",
                    "p": 0.5,
                    "house_days": rng.randint(2, 12),
                    "senate_days": rng.randint(2, 12),
                    "weight": rng.choice([1.0, 2.0]),
                }
                for i in range(n)
            ],
        }
    )


@pytest.mark.parametrize("seed", range(120))
def test_pruned_search_matches_exhaustive(seed: int) -> None:
    rng = random.Random(seed)
    p = _pf(rng.randint(3, 6), rng, rng.randint(1, 3))
    n_ep = len({rc.date for rc in p.roster_changes}) + 1
    p0e = {c.id: [rng.choice([0.0, 0.1, 0.5, 0.9, 1.0]) for _ in range(n_ep)] for c in p.candidates}
    p0 = {k: v[0] for k, v in p0e.items()}
    ctx, _ = make_ctx(p, p0, p0e=p0e)
    pruned = search(ctx)[0].value
    full = search(ctx, exhaustive=True)[0].value
    assert pruned == pytest.approx(full, abs=1e-9)


def test_earlier_lanes_need_slack_to_dominate() -> None:
    # A change on Jan 15 makes c worth more afterwards. Plan a frees the Senate on Jan 5 and
    # plan b on Jan 12 (same epoch), yet b's continuation reaches the better epoch.
    p = Portfolio.model_validate(
        {
            "schema_version": 1,
            "start": "2027-01-04",
            "deadline": "2027-12-17",
            "roster_changes": [{"date": "2027-01-15", "chamber": "senate", "vacate": "x"}],
            "candidates": [{"id": "c", "p": 0.2, "house_days": 1, "senate_days": 2}],
        }
    )
    ctx, _ = make_ctx(p, {"c": 0.2}, p0e={"c": [0.2, 0.9]})
    assert _slack(ctx, frozenset(), 0) == pytest.approx(0.7)
    assert _slack(ctx, frozenset(), 1) == 0.0
    assert _slack(make_ctx(p, {"c": 0.2})[0], frozenset(), 0) == 0.0
    # Starting earlier never loses anything when P only falls later.
    falling, _ = make_ctx(p, {"c": 0.9}, p0e={"c": [0.9, 0.2]})
    assert _slack(falling, frozenset(), 0) == 0.0


def test_dominance_with_identical_states() -> None:
    from impsolver.portfolio import LaneState, Plan

    st = LaneState((D(2027, 1, 4),), D(2027, 1, 4))
    a, b = Plan(("x",), (), 1.0, st), Plan(("x",), (), 0.5, st)
    assert _dominates(a, b, frozenset(), slack=5.0)
    assert not _dominates(b, a, frozenset(), slack=0.0)


def test_epoch_row_length_is_checked() -> None:
    p = Portfolio.model_validate(
        {
            "schema_version": 1,
            "start": "2027-01-04",
            "deadline": "2027-12-17",
            "roster_changes": [{"date": "2027-01-15", "chamber": "senate", "vacate": "x"}],
            "candidates": [{"id": "c", "p": 0.2, "house_days": 1, "senate_days": 2}],
        }
    )
    with pytest.raises(PortfolioError, match="epoch P0"):
        make_ctx(p, {"c": 0.2}, p0e={"c": [0.2]})


def test_low_p_uses_best_epoch() -> None:
    p = Portfolio.model_validate(
        {
            "schema_version": 1,
            "start": "2027-01-04",
            "deadline": "2027-12-17",
            "roster_changes": [{"date": "2027-01-15", "chamber": "senate", "vacate": "x"}],
            "candidates": [{"id": "c", "p": 0.0, "house_days": 1, "senate_days": 2}],
        }
    )
    res = solve(Loaded(p, {}, {"c": 0.0}, p0_epochs={"c": [0.0, 0.01]}), joint=False)
    assert res.dropped[0].reason == "LOW_P" and "under any roster" in res.dropped[0].detail
