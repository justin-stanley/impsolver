import datetime as dt
from typing import Any

from hypothesis import given, settings
from hypothesis import strategies as st

from impsolver.model import ChamberCalendar, Portfolio
from impsolver.portfolio import (
    Loaded,
    WorkCalendar,
    make_ctx,
    schedule_order,
    search,
    solve,
)

D = dt.date


def pf(cands: list[dict[str, Any]], **kw: Any) -> Portfolio:
    data: dict[str, Any] = {
        "schema_version": 1,
        "start": "2027-01-04",
        "deadline": "2027-12-17",
        "draws": 200,
        "candidates": cands,
    }
    data.update(kw)
    return Portfolio.model_validate(data)


def run(p: Portfolio, exhaustive: bool = False):  # type: ignore[no-untyped-def]
    return solve(Loaded(p, {}, {c.id: c.p or 0.0 for c in p.candidates}), exhaustive, joint=False)


def c(cid: str, p: float, h: int = 10, s: int = 10, **kw: Any) -> dict[str, Any]:
    return {"id": cid, "p": p, "house_days": h, "senate_days": s, **kw}


def test_calendar_skips_weekends_and_recess() -> None:
    cal = WorkCalendar(
        ChamberCalendar(recess=[(D(2027, 1, 11), D(2027, 1, 15))]), D(2027, 1, 4), D(2027, 3, 1)
    )
    assert cal.nth_from(D(2027, 1, 4), 5) == D(2027, 1, 8)
    assert cal.nth_from(D(2027, 1, 4), 6) == D(2027, 1, 18)  # recess week skipped
    sat = WorkCalendar(ChamberCalendar(), D(2027, 1, 4), D(2027, 3, 1), (5,))
    assert sat.nth_from(D(2027, 1, 4), 6) == D(2027, 1, 9)


def test_trials_never_overlap_and_concurrency() -> None:
    r = run(pf([c("a", 0.6), c("b", 0.5), c("c", 0.4)], house_concurrency=2))
    slots = sorted(r.plans[0].slots, key=lambda s: s.trial_start)
    assert len(slots) == 3
    for x, y in zip(slots, slots[1:], strict=False):
        assert x.trial_end < y.trial_start
    starts = sorted(s.house_start for s in slots)
    assert starts[0] == starts[1]  # two House lanes run at once
    one = run(pf([c("a", 0.6), c("b", 0.5)], house_concurrency=1))
    s1 = sorted(one.plans[0].slots, key=lambda s: s.house_start)
    assert s1[0].house_end < s1[1].house_start


def test_no_fit_and_low_p() -> None:
    r = run(pf([c("big", 0.9, h=400), c("tiny", 0.01), c("ok", 0.5)]))
    reasons = {d.id: d.reason for d in r.dropped}
    assert reasons == {"big": "NO_FIT", "tiny": "LOW_P"}


def test_value_beats_count() -> None:
    # Only room for one long case or two short ones.
    p = pf(
        [c("long", 0.9, h=100, s=40), c("s1", 0.3, h=50, s=20), c("s2", 0.3, h=50, s=20)],
        deadline="2027-07-30",
        house_concurrency=1,
    )
    r = run(p)
    assert sorted(r.plans[1].order) == ["s1", "s2"]  # two removals attempted, lower value
    assert r.plans[0].order == ["long"] and abs(r.plans[0].expected_removals - 0.9) < 1e-9


def test_excludes_and_after() -> None:
    r = run(pf([c("a", 0.6, excludes=["b"]), c("b", 0.5), c("d", 0.4, after=["a"])]))
    best = r.plans[0]
    assert "b" not in best.order and {d.id: d.reason for d in r.dropped}["b"] == "EXCLUDED"
    slots = {s.id: s for s in best.slots}
    assert slots["d"].house_start > slots["a"].trial_end


def test_fatigue() -> None:
    r = run(pf([c("a", 0.6), c("b", 0.6)], fatigue_delta=0.5))
    second = max(r.plans[0].slots, key=lambda s: s.attempt)
    assert second.attempt == 1 and second.p < second.p0


def test_candidate_deadline() -> None:
    r = run(pf([c("a", 0.6, deadline="2027-01-20")]))
    assert {d.id: d.reason for d in r.dropped}["a"] == "NO_FIT"


def test_recess_delays_house() -> None:
    cal = {"house": {"recess": [["2027-01-04", "2027-01-29"]]}}
    r = run(pf([c("a", 0.6)], calendar=cal))
    assert r.plans[0].slots[0].house_end > D(2027, 2, 1)


def test_sensitivity_rows() -> None:
    r = run(pf([c("a", 0.6), c("b", 0.5)]))
    assert len(r.sensitivity) == 6 and not r.fragile


@st.composite
def portfolios(draw: st.DrawFn) -> Portfolio:
    """Random portfolios with dependencies, exclusions, release dates and deadlines."""
    n = draw(st.integers(1, 6))
    cands = []
    for i in range(n):
        kw: dict[str, Any] = {}
        earlier = [f"c{j}" for j in range(i)]
        if earlier and draw(st.booleans()):
            kw["after"] = [draw(st.sampled_from(earlier))]
        if earlier and draw(st.integers(0, 3)) == 0:
            kw["excludes"] = [draw(st.sampled_from(earlier))]
        if draw(st.integers(0, 2)) == 0:
            kw["release"] = (
                D(2027, 1, 4) + dt.timedelta(days=draw(st.integers(0, 120)))
            ).isoformat()
        if draw(st.integers(0, 2)) == 0:
            kw["deadline"] = (
                D(2027, 3, 1) + dt.timedelta(days=draw(st.integers(0, 200)))
            ).isoformat()
        if draw(st.integers(0, 3)) == 0:
            kw["weight"] = draw(st.sampled_from([0.5, 2.0]))
        cands.append(
            c(
                f"c{i}",
                draw(st.floats(0.06, 0.99)),
                h=draw(st.integers(5, 60)),
                s=draw(st.integers(5, 40)),
                **kw,
            )
        )
    return pf(
        cands,
        deadline="2027-09-30",
        house_concurrency=draw(st.integers(1, 2)),
        fatigue_delta=draw(st.sampled_from([0.0, 0.3, -0.2])),
    )


@settings(max_examples=60, deadline=None)
@given(portfolios())
def test_pruned_equals_exhaustive(p: Portfolio) -> None:
    ctx, _ = make_ctx(p, {x.id: x.p or 0 for x in p.candidates})
    a = search(ctx)[0]
    b = search(ctx, exhaustive=True)[0]
    assert abs(a.value - b.value) < 1e-9
    assert abs(schedule_order(ctx, a.order).value - a.value) < 1e-9


def _random_pf(n: int, seed: int, **kw: Any) -> Portfolio:
    import numpy as np

    rr = np.random.default_rng(seed)
    cands = [
        c(
            f"c{i}",
            float(rr.uniform(0.1, 0.9)),
            h=int(rr.integers(10, 60)),
            s=int(rr.integers(5, 30)),
        )
        for i in range(n)
    ]
    return pf(cands, fatigue_delta=0.1, **kw)


def test_beam_matches_exact_on_ten_candidates() -> None:
    exact = _random_pf(10, 105, deadline="2027-07-30")
    beam = _random_pf(10, 105, deadline="2027-07-30", exact_limit=1)
    a = search(make_ctx(exact, {x.id: x.p or 0 for x in exact.candidates})[0])[0]
    b = search(make_ctx(beam, {x.id: x.p or 0 for x in beam.candidates})[0])[0]
    assert abs(a.value - b.value) < 1e-9


def test_sixteen_candidates_finish_quickly() -> None:
    import time

    p = _random_pf(16, 16, deadline="2028-12-15")
    t = time.time()
    plans = search(make_ctx(p, {x.id: x.p or 0 for x in p.candidates})[0])
    assert time.time() - t < 30 and plans[0].order
