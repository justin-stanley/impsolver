# SPDX-FileCopyrightText: 2026 Justin Stanley
# SPDX-License-Identifier: MIT
"""Schedule a user-supplied portfolio of candidates to maximize expected removals.

The House works on up to ``house_concurrency`` cases at once. The Senate holds one trial at a
time. Time is counted conservatively in whole working days, and each phase starts the working
day after the previous one ends. The objective is E[removals] = sum of w_i * P_i over the
candidates that finish by their deadline.
"""

from __future__ import annotations

import bisect
import datetime as dt
import itertools
import math
from dataclasses import dataclass, field, replace
from pathlib import Path

import numpy as np
from pydantic import BaseModel

from .deterministic import default_path, evaluate_article
from .loader import load_portfolio, resolve
from .members import logit, sigmoid
from .model import ChamberCalendar, Portfolio, PortfolioCandidate
from .paths import path_for
from .prepare import Prepared, prepare
from .results import DeterministicArticle, SimArticle
from .simulate import (
    any_complete,
    p_any_complete,
    p_complete,
    run_raw_articles,
    simulate_article,
)

FAR = dt.date(9999, 12, 31)
MAX_BRANCH_TRIGGERS = 3
ADAPTIVE_REORDER = 6  # re-order a branch exhaustively when at most this many cases remain
EXHAUSTIVE_SUCCESSION = 7
RESCORE_TOP = 2000
SENS_DELTAS = (-0.2, 0.0, 0.2, 0.5)
SENS_SCALES = (0.75, 1.25)


class PortfolioError(Exception):
    pass


def _fatigued(p0: float, delta: float, m: int) -> float:
    if p0 <= 0.0 or p0 >= 1.0 or delta == 0.0 or m == 0:
        return p0
    return sigmoid(logit(p0) - delta * m)


# --------------------------------------------------------------------- calendars


class WorkCalendar:
    """Working days for one chamber between start and an horizon."""

    def __init__(
        self,
        cal: ChamberCalendar,
        start: dt.date,
        horizon: dt.date,
        extra_weekdays: tuple[int, ...] = (),
    ) -> None:
        wd = set(cal.weekdays) | set(extra_weekdays)
        days: list[int] = []
        d = start
        while d <= horizon:
            if d.weekday() in wd and not any(a <= d <= b for a, b in cal.recess):
                days.append(d.toordinal())
            d += dt.timedelta(days=1)
        self.days = days

    def nth_from(self, start: dt.date, n: int) -> dt.date:
        """Date of the n-th working day on or after ``start`` (n >= 1)."""
        if n <= 0:
            return start - dt.timedelta(days=1)
        i = bisect.bisect_left(self.days, start.toordinal()) + n - 1
        return dt.date.fromordinal(self.days[i]) if i < len(self.days) else FAR


@dataclass(frozen=True)
class Calendars:
    house: WorkCalendar
    senate: WorkCalendar
    trial: WorkCalendar


def make_calendars(pf: Portfolio) -> Calendars:
    horizon = max(pf.deadline, pf.start) + dt.timedelta(days=3 * 365)
    sat = (5,) if pf.calendar.trial_saturdays else ()
    return Calendars(
        WorkCalendar(pf.calendar.house, pf.start, horizon),
        WorkCalendar(pf.calendar.senate, pf.start, horizon),
        WorkCalendar(pf.calendar.senate, pf.start, horizon, sat),
    )


# ---------------------------------------------------------------------- schedule


@dataclass(frozen=True)
class LaneState:
    house_free: tuple[dt.date, ...]  # sorted
    senate_free: dt.date
    trial_end: tuple[tuple[str, dt.date], ...] = ()

    def end_of(self, cid: str) -> dt.date | None:
        for k, v in self.trial_end:
            if k == cid:
                return v
        return None


class Slot(BaseModel):
    id: str
    house_start: dt.date
    house_end: dt.date
    trial_start: dt.date
    trial_end: dt.date
    p0: float
    p: float
    weight: float
    attempt: int


@dataclass
class Ctx:
    pf: Portfolio
    cands: dict[str, PortfolioCandidate]
    p0: dict[str, float]
    cals: Calendars
    delta: float
    scale: float = 1.0
    eligible: list[str] = field(default_factory=list)

    def days(self, n: int) -> int:
        return max(1, math.ceil(n * self.scale)) if n > 0 else 0

    def deadline(self, c: PortfolioCandidate) -> dt.date:
        own = c.deadline or FAR
        return own if self.pf.trial_carryover else min(own, self.pf.deadline)


def place_house(
    ctx: Ctx, cid: str, st: LaneState, not_before: dt.date | None = None
) -> tuple[dt.date, dt.date, tuple[dt.date, ...]] | None:
    """House phase only: (start, end, new sorted lane free dates), or None if it cannot fit."""
    c = ctx.cands[cid]
    earliest = max(ctx.pf.start, c.release or ctx.pf.start, not_before or ctx.pf.start)
    for dep in c.after:
        end = st.end_of(dep)
        if end is None:
            return None
        earliest = max(earliest, end + dt.timedelta(days=1))
    lanes = list(st.house_free)
    lane = min(range(len(lanes)), key=lambda i: (max(lanes[i], earliest), i))
    h_start = max(lanes[lane], earliest)
    h_end = ctx.cals.house.nth_from(h_start, ctx.days(c.house_days))
    if h_end >= FAR or h_end > ctx.pf.deadline:
        return None
    lanes[lane] = h_end + dt.timedelta(days=1)
    return h_start, h_end, tuple(sorted(lanes))


def place(
    ctx: Ctx, cid: str, st: LaneState, attempt: int, not_before: dt.date | None = None
) -> tuple[Slot, LaneState] | None:
    """Schedule candidate ``cid`` after everything in ``st``; None if it misses its deadline.

    ``not_before`` is the earliest day its House work may start (used when a plan is revised
    after a verdict).
    """
    c = ctx.cands[cid]
    house = place_house(ctx, cid, st, not_before)
    if house is None:
        return None
    h_start, h_end, lanes = house
    ready = h_end + dt.timedelta(days=1)
    if c.senate_committee:
        com_end = ctx.cals.senate.nth_from(ready, ctx.days(c.senate_days))
        t_start = max(com_end + dt.timedelta(days=1), st.senate_free)
        t_end = (
            ctx.cals.trial.nth_from(t_start, c.committee_floor_days)
            if c.committee_floor_days
            else max(com_end, t_start - dt.timedelta(days=1))
        )
    else:
        t_start = max(ready, st.senate_free)
        t_end = ctx.cals.trial.nth_from(t_start, ctx.days(c.senate_days))
    if t_end >= FAR or t_end > ctx.deadline(c):
        return None
    p = _fatigued(ctx.p0[cid], ctx.delta, attempt)
    slot = Slot(
        id=cid,
        house_start=h_start,
        house_end=h_end,
        trial_start=t_start,
        trial_end=t_end,
        p0=ctx.p0[cid],
        p=p,
        weight=c.weight,
        attempt=attempt,
    )
    new = LaneState(lanes, t_end + dt.timedelta(days=1), st.trial_end + ((cid, t_end),))
    return slot, new


def initial_state(ctx: Ctx) -> LaneState:
    return LaneState(tuple([ctx.pf.start] * ctx.pf.house_concurrency), ctx.pf.start)


def excluded_pair(ctx: Ctx, a: str, b: str) -> bool:
    return b in ctx.cands[a].excludes or a in ctx.cands[b].excludes


# ------------------------------------------------------------------------ search


@dataclass(frozen=True)
class Plan:
    order: tuple[str, ...]
    slots: tuple[Slot, ...]
    value: float
    state: LaneState


def _dominates(a: Plan, b: Plan, watched: frozenset[str]) -> bool:
    """True if ``a`` is at least as good as ``b`` for every possible continuation.

    Both plans cover the same subset, so future value depends only on when the House lanes and the
    Senate free up, and on the trial ends that a still-unscheduled candidate's ``after`` can read
    (``watched``). Other trial ends cannot affect anything that follows.
    """
    if a.value < b.value - 1e-12 or a.state.senate_free > b.state.senate_free:
        return False
    if any(x > y for x, y in zip(a.state.house_free, b.state.house_free, strict=True)):
        return False
    if not watched:
        return True
    ea, eb = dict(a.state.trial_end), dict(b.state.trial_end)
    return all(ea[k] <= eb[k] for k in watched if k in ea)


def _watched(ctx: Ctx, subset: frozenset[str]) -> frozenset[str]:
    """Scheduled candidates whose trial end some unscheduled candidate depends on."""
    out: set[str] = set()
    for cid in ctx.eligible:
        if cid not in subset:
            out.update(d for d in ctx.cands[cid].after if d in subset)
    return frozenset(out)


def _p_max(ctx: Ctx, cid: str, attempt: int) -> float:
    """Highest fatigued P this candidate can still reach from attempt number ``attempt`` on."""
    last = max(attempt, len(ctx.eligible) - 1)
    return max(_fatigued(ctx.p0[cid], ctx.delta, attempt), _fatigued(ctx.p0[cid], ctx.delta, last))


def _kth_best(found: list[Plan], k: int) -> float:
    vals = sorted({round(p.value, 12) for p in found}, reverse=True)
    return vals[k - 1] if len(vals) >= k else -math.inf


def search(ctx: Ctx, exhaustive: bool = False) -> list[Plan]:
    """Every reachable plan (exhaustive) or the non-dominated ones; best first.

    Every partial plan is itself a valid plan, so the k-th best value seen so far is a lower
    bound on what the reported top plans will be worth. A plan is not extended when its value plus
    an optimistic bound on what could still be added cannot reach that (branch and bound).
    """
    root = Plan((), (), 0.0, initial_state(ctx))
    frontier = [root]
    found: list[Plan] = [root]
    use_beam = not exhaustive and len(ctx.eligible) > ctx.pf.exact_limit
    k = max(1, ctx.pf.top)
    while frontier:
        nxt: list[Plan] = []
        thresh = -math.inf if exhaustive else _kth_best(found, k)
        for pl in frontier:
            children: list[Plan] = []
            bound = 0.0
            for cid in ctx.eligible:
                if cid in pl.order or any(excluded_pair(ctx, cid, o) for o in pl.order):
                    continue
                got = place(ctx, cid, pl.state, len(pl.order))
                if got is None:
                    # A candidate that misses its deadline now never fits later; one waiting on
                    # an unscheduled dependency might, so count it optimistically.
                    if any(d not in pl.order for d in ctx.cands[cid].after):
                        bound += ctx.cands[cid].weight * _p_max(ctx, cid, len(pl.order))
                    continue
                slot, st = got
                bound += slot.weight * _p_max(ctx, cid, len(pl.order))
                children.append(
                    Plan(pl.order + (cid,), pl.slots + (slot,), pl.value + slot.weight * slot.p, st)
                )
            if not exhaustive and pl.value + bound < thresh - 1e-12:
                continue
            nxt += children
        if not exhaustive:
            groups: dict[frozenset[str], list[Plan]] = {}
            watch: dict[frozenset[str], frozenset[str]] = {}
            for pl in sorted(nxt, key=lambda p: -p.value):
                key = frozenset(pl.order)
                g = groups.setdefault(key, [])
                w = watch.setdefault(key, _watched(ctx, key))
                if not any(_dominates(o, pl, w) for o in g):
                    g.append(pl)
            nxt = [p for g in groups.values() for p in g]
            if use_beam:
                nxt = sorted(nxt, key=lambda p: -p.value)[: ctx.pf.beam]
        found += nxt
        frontier = nxt
    return sorted(found, key=_plan_key)


def _plan_key(p: Plan) -> tuple[float, int, int, tuple[str, ...]]:
    last = max((s.trial_end for s in p.slots), default=dt.date.min).toordinal()
    return (-round(p.value, 12), len(p.order), last, p.order)


def schedule_order(ctx: Ctx, order: tuple[str, ...]) -> Plan:
    """Re-schedule a fixed order, skipping candidates that no longer fit."""
    st = initial_state(ctx)
    slots: list[Slot] = []
    kept: list[str] = []
    value = 0.0
    for cid in order:
        if cid not in ctx.cands or any(excluded_pair(ctx, cid, o) for o in kept):
            continue
        got = place(ctx, cid, st, len(kept))
        if got is None:
            continue
        slot, st = got
        slots.append(slot)
        kept.append(cid)
        value += slot.weight * slot.p
    return Plan(tuple(kept), tuple(slots), value, st)


# -------------------------------------------------------------------- succession


class TreeNode(BaseModel):
    """One segment of a plan. ``tried`` lists the candidates whose trials run in it.

    A node whose ``at`` names a trigger branches after that trigger's verdict; ``(end)`` is a leaf.
    ``order`` is the order this segment works through its remaining candidates; on a branch it
    is the order re-optimized after the verdict, and ``reordered`` says whether it differs from
    the order the branch would otherwise have kept.
    """

    at: str
    p_removed: float
    removed: TreeNode | None = None
    not_removed: TreeNode | None = None
    value: float
    schedule: list[str]
    tried: list[str] = []
    tried_p: list[float] = []
    verdict: dt.date | None = None
    order: list[str] = []
    reordered: bool = False


def _dependents(ctx: Ctx, trigger: str, rest: list[str]) -> dict[str, str | None]:
    """Later candidates whose case changes if ``trigger`` (or its base case) is removed."""
    base = ctx.cands[trigger].variant_of or trigger
    out: dict[str, str | None] = {}
    for cid in rest:
        for s in ctx.cands[cid].succession:
            if s.on_removal_of in (trigger, base):
                out[cid] = s.becomes
    return out


@dataclass(frozen=True)
class _Item:
    cid: str
    not_before: dt.date | None = None
    sunk: bool = False  # House work already begun for a case that no longer exists
    committed: dt.date | None = None  # House start, when it began before the last verdict
    pin: dt.date | None = None  # House start a re-ordered branch must keep


class _Infeasible(Exception):
    """A re-ordered branch would move House work that had already started."""


def _later(a: dt.date | None, b: dt.date | None) -> dt.date | None:
    if a is None:
        return b
    if b is None:
        return a
    return max(a, b)


def _preview_starts(
    ctx: Ctx, items: list[_Item], st: LaneState, attempt: int, done: list[str]
) -> dict[str, dt.date]:
    """House start dates if ``items`` ran with no further branching."""
    out: dict[str, dt.date] = {}
    for it in items:
        if it.sunk or any(excluded_pair(ctx, it.cid, o) for o in done):
            continue
        got = place(ctx, it.cid, st, attempt, it.not_before)
        if got is None:
            continue
        slot, st = got
        out[it.cid] = slot.house_start
        done = done + [it.cid]
        attempt += 1
    return out


def _free_slots(items: list[_Item]) -> list[int]:
    """Positions of the cases whose House work has not started."""
    return [i for i, x in enumerate(items) if not x.sunk and x.committed is None]


def _reorderings(items: list[_Item]) -> list[list[_Item]]:
    """Every order a branch may re-plan to, in a canonical sequence.

    Committed and sunk items keep their positions and are pinned to their House start; the free
    (not yet started) items fill the other positions in every order. Returns no orders when fewer
    than two or more than ``ADAPTIVE_REORDER`` items are free.
    """
    free = _free_slots(items)
    if len(free) < 2 or len(free) > ADAPTIVE_REORDER:
        return []
    fixed = [replace(x, pin=x.committed) if x.committed else x for x in items]
    pool = sorted((items[i] for i in free), key=lambda x: (x.cid, x.not_before or dt.date.min))
    out = []
    for perm in itertools.permutations(pool):
        cand = list(fixed)
        for i, x in zip(free, perm, strict=True):
            cand[i] = x
        out.append(cand)
    return out


def evaluate_branching(
    ctx: Ctx,
    order: tuple[str, ...],
    adaptive: bool = True,
    cache: dict[object, object] | None = None,
) -> tuple[float, TreeNode]:
    """Expected value of a fixed order when a removal at a trigger's trial changes later cases.

    The plan is causal: the branches after a trigger may differ only in work that starts after
    the trigger's verdict. House work already begun on a dependent is kept as it was; if that
    dependent is cancelled, its House lane stays used through the end of its House phase. A
    variant (for example a successor now holding the office) needs fresh House time, starting the
    day after the verdict. Everything else that has not started is re-planned from that day.

    With ``adaptive`` (the default), each branch also re-optimizes the order of the candidates
    whose House work has not started, over every permutation when at most ``ADAPTIVE_REORDER``
    remain; work already started keeps its dates. ``cache`` may be shared between calls on the
    same ``ctx`` (``best_with_succession`` does this).
    """
    memo: dict[object, object] = {} if cache is None else cache

    def best(
        items: list[_Item], st: LaneState, attempt: int, depth: int, done: list[str]
    ) -> tuple[float, TreeNode]:
        """The kept order, or the best re-ordering when it is strictly better."""
        kept: tuple[float, TreeNode] | None = None
        try:
            kept = run(items, st, attempt, depth, done)
        except _Infeasible:
            pass
        alt = best_reordering(items, st, attempt, depth, done) if adaptive else None
        if alt is not None and (kept is None or alt[0] > kept[0] + 1e-12):
            return alt[0], alt[1].model_copy(update={"reordered": True})
        if kept is None:
            raise _Infeasible
        return kept

    def best_reordering(
        items: list[_Item], st: LaneState, attempt: int, depth: int, done: list[str]
    ) -> tuple[float, TreeNode] | None:
        """Best feasible re-ordering of the free items (first in canonical order on ties).

        It depends only on which items are free, not on their order, so it is cached on that set.
        """
        free = set(_free_slots(items))
        shape = tuple(None if i in free else x for i, x in enumerate(items))
        key = ("reorder", shape, frozenset(items[i] for i in free), st, attempt, depth, tuple(done))
        if key not in memo:
            found: tuple[float, TreeNode] | None = None
            for cand in _reorderings(items):
                try:
                    v, t = run(cand, st, attempt, depth, done)
                except _Infeasible:
                    continue
                if found is None or v > found[0] + 1e-12:
                    found = (v, t)
            memo[key] = found
        return memo[key]  # type: ignore[return-value]

    def run(
        items: list[_Item], st: LaneState, attempt: int, depth: int, done: list[str]
    ) -> tuple[float, TreeNode]:
        key = ("run", tuple(items), st, attempt, depth, tuple(done))
        if key in memo:
            hit = memo[key]
            if hit is None:
                raise _Infeasible
            return hit  # type: ignore[return-value]
        try:
            out = _run(items, st, attempt, depth, done)
        except _Infeasible:
            memo[key] = None
            raise
        memo[key] = out
        return out

    def _run(
        items: list[_Item], st: LaneState, attempt: int, depth: int, done: list[str]
    ) -> tuple[float, TreeNode]:
        value = 0.0
        planned = [x.cid for x in items if not x.sunk]
        sched: list[str] = []
        tried: list[str] = []
        tried_p: list[float] = []
        while items:
            it, items = items[0], items[1:]
            if it.sunk:
                house = place_house(ctx, it.cid, st, it.not_before)
                if it.pin is not None and (house is None or house[0] != it.pin):
                    raise _Infeasible
                if house is not None:
                    h_start, h_end, lanes = house
                    st = LaneState(lanes, st.senate_free, st.trial_end)
                    sched.append(f"{it.cid} House {h_start}..{h_end} (cancelled, time lost)")
                continue
            if any(excluded_pair(ctx, it.cid, o) for o in done):
                continue
            got = place(ctx, it.cid, st, attempt, it.not_before)
            if it.pin is not None and (got is None or got[0].house_start != it.pin):
                raise _Infeasible
            if got is None:
                continue
            slot, st = got
            done = done + [it.cid]
            tried.append(it.cid)
            tried_p.append(slot.p)
            value += slot.weight * slot.p
            sched.append(
                f"{it.cid} House {slot.house_start}..{slot.house_end}, "
                f"trial {slot.trial_start}..{slot.trial_end} p={slot.p:.3f}"
            )
            attempt += 1
            deps = _dependents(ctx, it.cid, [x.cid for x in items if not x.sunk])
            if not deps or depth >= MAX_BRANCH_TRIGGERS:
                continue
            verdict = slot.trial_end
            after = verdict + dt.timedelta(days=1)
            starts = _preview_starts(ctx, items, st, attempt, done)
            removed: list[_Item] = []
            kept: list[_Item] = []
            for x in items:
                if x.sunk:
                    removed.append(x)
                    kept.append(x)
                    continue
                began = starts.get(x.cid)
                if began is not None and began <= verdict:
                    fixed = replace(x, committed=began)
                    kept.append(fixed)
                    if x.cid not in deps:
                        removed.append(fixed)
                    else:
                        removed.append(replace(fixed, sunk=True))
                else:
                    free = replace(x, not_before=_later(x.not_before, after), committed=None)
                    kept.append(free)
                    if x.cid not in deps:
                        removed.append(free)
                if x.cid in deps and deps[x.cid] is not None:
                    removed.append(_Item(str(deps[x.cid]), _later(x.not_before, after)))
            vr, tr = best(removed, st, attempt, depth + 1, done)
            vk, tk = best(kept, st, attempt, depth + 1, done)
            node = TreeNode(
                at=it.cid,
                p_removed=slot.p,
                value=slot.p * vr + (1 - slot.p) * vk,
                removed=tr,
                not_removed=tk,
                schedule=sched,
                tried=tried,
                tried_p=tried_p,
                verdict=verdict,
                order=planned,
            )
            return value + node.value, node
        return value, TreeNode(
            at="(end)",
            p_removed=0.0,
            value=value,
            schedule=sched,
            tried=tried,
            tried_p=tried_p,
            order=planned,
        )

    return run([_Item(c) for c in order], initial_state(ctx), 0, 0, [])


def has_succession(ctx: Ctx) -> bool:
    return any(ctx.cands[c].succession for c in ctx.eligible)


def best_with_succession(
    ctx: Ctx, plans: list[Plan]
) -> tuple[tuple[str, ...], float, TreeNode | None]:
    if len(ctx.eligible) <= EXHAUSTIVE_SUCCESSION:
        orders: list[tuple[str, ...]] = []
        for r in range(1, len(ctx.eligible) + 1):
            orders += list(itertools.permutations(ctx.eligible, r))
    else:
        orders = [p.order for p in plans[:RESCORE_TOP]]
    best: tuple[tuple[str, ...], float, TreeNode | None] = ((), 0.0, None)
    cache: dict[object, object] = {}
    for o in orders:
        v, t = evaluate_branching(ctx, o, cache=cache)
        if v > best[1] + 1e-12:
            best = (o, v, t)
    return best


# ------------------------------------------------------------------------ result


REASON_TEXT = {
    "LOW_P": "Chance of removal is below p_floor.",
    "NO_FIT": "Cannot finish by its deadline.",
    "EXCLUDED": "Cannot run alongside a case in the plan.",
    "DEPENDENCY_DROPPED": "Depends on a case that is not in the plan.",
    "NOT_SELECTED": "Left out to maximize expected removals.",
}


def excluded_reason_text(reason: str) -> str:
    return REASON_TEXT.get(reason, "")


class Dropped(BaseModel):
    id: str
    reason: str
    detail: str


class PlanOut(BaseModel):
    order: list[str]
    expected_removals: float
    slots: list[Slot]


class SensRow(BaseModel):
    label: str
    best: float
    base_rescheduled: float
    regret: float
    fragile: bool


class RemovalsDist(BaseModel):
    probabilities: list[float]
    mean: float
    sd: float
    independent_sd: float
    spread_ratio: float
    draws: int
    method: str
    notes: list[str]


class PortfolioResult(BaseModel):
    plans: list[PlanOut]
    dropped: list[Dropped]
    sensitivity: list[SensRow]
    fragile: bool
    succession_value: float | None = None
    succession_order: list[str] | None = None
    decision_tree: TreeNode | None = None
    removals_dist: RemovalsDist | None = None
    exhaustive: bool
    p0: dict[str, float]
    gate_paths: dict[str, SimArticle] = {}
    pivots: dict[str, DeterministicArticle] = {}
    labels: dict[str, str] = {}


# ------------------------------------------------------------------- top level


@dataclass
class Loaded:
    pf: Portfolio
    preps: dict[str, Prepared]
    p0: dict[str, float]
    gates: dict[str, SimArticle] = field(default_factory=dict)


def deterministic_articles(loaded: Loaded) -> dict[str, DeterministicArticle]:
    """Deterministic bounds (with the binding-gate pivot list) for each scenario candidate."""
    out: dict[str, DeterministicArticle] = {}
    for c in loaded.pf.candidates:
        prep = loaded.preps.get(c.id)
        if prep is None:
            continue
        art = c.article or prep.scenario.articles[0]
        out[c.id] = evaluate_article(
            prep, art, path_for(prep.rules, prep.scenario, default_path(prep))
        )
    return out


def load(path: str | Path) -> Loaded:
    pf = load_portfolio(path)
    preps: dict[str, Prepared] = {}
    p0: dict[str, float] = {}
    gates: dict[str, SimArticle] = {}
    for c in pf.candidates:
        if c.scenario is not None:
            prep = prepare(resolve(c.scenario, path))
            preps[c.id] = prep
            path_ = path_for(prep.rules, prep.scenario, default_path(prep))
            seed, rho = prep.scenario.seed, prep.scenario.rho
            if c.article is not None or len(prep.scenario.articles) == 1:
                art = c.article or prep.scenario.articles[0]
                sim = simulate_article(prep, art, path_, pf.draws, seed, rho)
                gates[c.id] = sim
                p0[c.id] = sim.p_complete
            else:
                # Removal happens if any article convicts: one joint simulation over articles.
                arts = list(prep.scenario.articles)
                raws = run_raw_articles(prep, arts, path_, pf.draws, seed, rho)
                p0[c.id] = float(any_complete(raws).mean())
                best = max(arts, key=lambda a: float(raws[a].complete.mean()))
                gates[c.id] = simulate_article(prep, best, path_, pf.draws, seed, rho)
        else:
            assert c.p is not None
            p0[c.id] = c.p
    return Loaded(pf, preps, p0, gates)


def make_ctx(
    pf: Portfolio, p0: dict[str, float], delta: float | None = None, scale: float = 1.0
) -> tuple[Ctx, list[Dropped]]:
    cands = {c.id: c for c in pf.candidates}
    ctx = Ctx(
        pf, cands, p0, make_calendars(pf), pf.fatigue_delta if delta is None else delta, scale
    )
    dropped: list[Dropped] = []
    for c in pf.candidates:
        if c.variant_of is not None:
            continue
        if p0[c.id] < pf.p_floor:
            dropped.append(
                Dropped(id=c.id, reason="LOW_P", detail=f"P={p0[c.id]:.3f} < p_floor {pf.p_floor}")
            )
            continue
        alone = replace(ctx, eligible=[c.id])
        if place(alone, c.id, initial_state(alone), 0) is None and not c.after:
            dropped.append(
                Dropped(
                    id=c.id,
                    reason="NO_FIT",
                    detail="cannot finish by its deadline even if scheduled first",
                )
            )
            continue
        ctx.eligible.append(c.id)
    return ctx, dropped


def _left_out(ctx: Ctx, order: tuple[str, ...]) -> list[Dropped]:
    """A reason for every eligible candidate that the recommended order does not try."""
    out: list[Dropped] = []
    chosen = set(order)
    for cid in ctx.eligible:
        if cid in chosen:
            continue
        by = [o for o in order if excluded_pair(ctx, cid, o)]
        missing = [d for d in ctx.cands[cid].after if d not in chosen]
        if by:
            out.append(Dropped(id=cid, reason="EXCLUDED", detail=f"excluded by {', '.join(by)}"))
        elif missing:
            out.append(
                Dropped(
                    id=cid,
                    reason="DEPENDENCY_DROPPED",
                    detail=f"waits on {', '.join(missing)}, which is not in the plan",
                )
            )
        else:
            out.append(
                Dropped(
                    id=cid,
                    reason="NOT_SELECTED",
                    detail="fits on its own, but the best plan has more expected value without it",
                )
            )
    return out


def _best_value(ctx: Ctx, exhaustive: bool) -> tuple[tuple[str, ...], float, list[Plan]]:
    plans = search(ctx, exhaustive)
    if has_succession(ctx):
        o, v, _ = best_with_succession(ctx, plans)
        return o, v, plans
    return plans[0].order, plans[0].value, plans


def _order_value(ctx: Ctx, order: tuple[str, ...]) -> float:
    if has_succession(ctx):
        return evaluate_branching(ctx, order)[0]
    return schedule_order(ctx, order).value


def solve(loaded: Loaded, exhaustive: bool = False, joint: bool = True) -> PortfolioResult:
    """Best plans, the recommended order and its sensitivity.

    With succession rules, the recommended order is the one that is best once removals are
    allowed to change later cases; dropped reasons and sensitivity are reported for that order.
    """
    pf, p0 = loaded.pf, loaded.p0
    ctx, dropped = make_ctx(pf, p0)
    order, _, plans = _best_value(ctx, exhaustive)
    dropped += _left_out(ctx, order)
    tops: list[PlanOut] = []
    seen: set[tuple[str, ...]] = set()
    for p in plans:
        if p.order in seen or not p.order:
            continue
        seen.add(p.order)
        tops.append(PlanOut(order=list(p.order), expected_removals=p.value, slots=list(p.slots)))
        if len(tops) >= pf.top:
            break
    sens = sensitivity(pf, p0, order, exhaustive)
    res = PortfolioResult(
        plans=tops,
        dropped=dropped,
        sensitivity=sens,
        fragile=any(r.fragile for r in sens),
        exhaustive=exhaustive,
        p0=p0,
        gate_paths=loaded.gates,
        pivots=deterministic_articles(loaded),
        labels={cid: prep.scenario.target.name for cid, prep in loaded.preps.items()},
    )
    if has_succession(ctx):
        v, tree = evaluate_branching(ctx, order)
        res.succession_order, res.succession_value, res.decision_tree = list(order), v, tree
    if joint and order:
        res.removals_dist = removals_dist(loaded, ctx, order)
    return res


def sensitivity(
    pf: Portfolio, p0: dict[str, float], base: tuple[str, ...], exhaustive: bool
) -> list[SensRow]:
    """Regret of keeping ``base`` when fatigue or durations differ from the inputs."""
    rows: list[SensRow] = []
    cases: list[tuple[str, float, float]] = [
        (f"fatigue delta {d:+.1f}", d, 1.0) for d in SENS_DELTAS
    ]
    cases += [(f"durations x{s}", pf.fatigue_delta, s) for s in SENS_SCALES]
    for label, d, s in cases:
        ctx, _ = make_ctx(pf, p0, d, s)
        _, best, _ = _best_value(ctx, exhaustive)
        base_v = _order_value(ctx, base)
        regret = max(0.0, best - base_v)
        rows.append(
            SensRow(
                label=label,
                best=best,
                base_rescheduled=base_v,
                regret=regret,
                fragile=regret > max(0.01, 0.05 * best),
            )
        )
    return rows


# --------------------------------------------------------------- joint removals


def poisson_binomial(ps: list[float]) -> list[float]:
    dist = [1.0]
    for p in ps:
        new = [0.0] * (len(dist) + 1)
        for k, v in enumerate(dist):
            new[k] += v * (1 - p)
            new[k + 1] += v * p
        dist = new
    return dist


def _p_removal(prep: Prepared, article: str | None, draws: int, extra: float = 0.0) -> float:
    """P(removal): the given article completes, or (``article`` None) any article does."""
    if article is not None:
        return p_complete(prep, article, draws=draws, extra=extra)
    return p_any_complete(prep, draws=draws, extra=extra)


def _match_shift(prep: Prepared, article: str | None, target: float, draws: int) -> float:
    """Uniform logit shift that makes P(removal) equal ``target`` (common random numbers).

    ``article`` None means removal on any article, matching ``load``.
    """
    base = _p_removal(prep, article, draws)
    if abs(base - target) < 1e-9:
        return 0.0
    lo, hi = (-8.0, 0.0) if target < base else (0.0, 8.0)
    for _ in range(30):
        mid = (lo + hi) / 2
        if _p_removal(prep, article, draws, mid) < target:
            lo = mid
        else:
            hi = mid
        if hi - lo < 1e-3:
            break
    return (lo + hi) / 2


def _tree_nodes(node: TreeNode) -> list[TreeNode]:
    out = [node]
    for child in (node.removed, node.not_removed):
        if child is not None:
            out += _tree_nodes(child)
    return out


def removals_dist(loaded: Loaded, ctx: Ctx, order: tuple[str, ...]) -> RemovalsDist:
    """Distribution of the number of removals for a fixed order.

    Each draw follows the same decision tree as ``evaluate_branching``: at a trigger the draw's own
    outcome for that trial picks the branch, so succession is resolved per draw and with the same
    timing and matching rules as the expected-value calculation.
    """
    pf = loaded.pf
    _, tree = evaluate_branching(ctx, order)
    nodes = _tree_nodes(tree)
    keys: list[tuple[str, float]] = []
    for nd in nodes:
        for cid, p in zip(nd.tried, nd.tried_p, strict=True):
            if (cid, p) not in keys:
                keys.append((cid, p))
    if not keys:
        return RemovalsDist(
            probabilities=[1.0],
            mean=0.0,
            sd=0.0,
            independent_sd=0.0,
            spread_ratio=1.0,
            draws=0,
            method="empty",
            notes=[],
        )
    branches = len(nodes) > 1
    fixed = sorted({cid for cid, _ in keys if cid not in loaded.preps})
    if not branches and not any(cid in loaded.preps for cid, _ in keys):
        dist = poisson_binomial(tree.tried_p)
        mean = sum(k * v for k, v in enumerate(dist))
        sd = math.sqrt(sum((k - mean) ** 2 * v for k, v in enumerate(dist)))
        return RemovalsDist(
            probabilities=dist,
            mean=mean,
            sd=sd,
            independent_sd=sd,
            spread_ratio=1.0,
            draws=0,
            method="poisson_binomial",
            notes=["all candidates have fixed p; exact Poisson-binomial"],
        )
    draws = pf.draws
    rng = np.random.Generator(np.random.PCG64(pf.seed))
    shared: dict[tuple[str, str], np.ndarray] = {}
    for cid, _ in keys:
        prep = loaded.preps.get(cid)
        if prep is None:
            continue
        for ch, body in prep.comp.bodies.items():
            for m in body.roster:
                shared.setdefault((ch, m.bloc), rng.standard_normal(draws))
    outcome: dict[tuple[str, float], np.ndarray] = {}
    for i, (cid, p) in enumerate(keys):
        prep = loaded.preps.get(cid)
        if prep is None:
            outcome[(cid, p)] = rng.random(draws) < p
            continue
        art = ctx.cands[cid].article
        arts = [art] if art is not None else list(prep.scenario.articles)
        shift = _match_shift(prep, art, p, draws)
        path = path_for(prep.rules, prep.scenario, default_path(prep))
        raws = run_raw_articles(
            prep, arts, path, draws, pf.seed + 1000 + i, prep.scenario.rho, shift, shared
        )
        outcome[(cid, p)] = any_complete(raws)
    counts = np.zeros(draws, dtype=int)

    def walk(nd: TreeNode, mask: np.ndarray) -> None:
        for cid, p in zip(nd.tried, nd.tried_p, strict=True):
            counts[mask] += outcome[(cid, p)][mask]
        if nd.removed is not None and nd.not_removed is not None:
            hit = outcome[(nd.at, nd.tried_p[nd.tried.index(nd.at)])]
            walk(nd.removed, mask & hit)
            walk(nd.not_removed, mask & ~hit)

    walk(tree, np.ones(draws, dtype=bool))
    notes: list[str] = []
    if fixed:
        notes.append(f"fixed-p candidates drawn independently: {', '.join(fixed)}")
    notes.append("one shared party-swing stream across scenario candidates, plus member noise")
    if branches:
        notes.append("succession resolved per draw along the decision tree")
    freq = np.bincount(counts, minlength=int(counts.max()) + 1) / draws
    mean = float(counts.mean())
    sd = float(counts.std())
    if branches:
        # Which cases are tried depends on earlier outcomes, so there is no simple independent
        # benchmark; report the joint spread against itself.
        ind_sd = sd
        notes.append("no independent benchmark with succession branches; spread_ratio is 1")
    else:
        qs = [
            float(outcome[(cid, p)].mean()) for cid, p in zip(tree.tried, tree.tried_p, strict=True)
        ]
        ind_sd = math.sqrt(sum(q * (1 - q) for q in qs))
    return RemovalsDist(
        probabilities=[float(x) for x in freq],
        mean=mean,
        sd=sd,
        independent_sd=ind_sd,
        spread_ratio=sd / ind_sd if ind_sd > 0 else 1.0,
        draws=draws,
        method="joint_monte_carlo",
        notes=notes,
    )


def run_portfolio(path: str | Path, exhaustive: bool = False) -> PortfolioResult:
    return solve(load(path), exhaustive)
