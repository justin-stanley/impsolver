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
from typing import Any

import numpy as np
from pydantic import BaseModel

from .deterministic import default_path
from .loader import load_portfolio, resolve
from .members import logit, sigmoid
from .model import ChamberCalendar, Portfolio, PortfolioCandidate
from .paths import path_for
from .prepare import Prepared, prepare
from .simulate import p_complete, run_raw

FAR = dt.date(9999, 12, 31)
MAX_BRANCH_TRIGGERS = 3
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


def place(ctx: Ctx, cid: str, st: LaneState, attempt: int) -> tuple[Slot, LaneState] | None:
    """Schedule candidate ``cid`` after everything in ``st``; None if it misses its deadline."""
    c = ctx.cands[cid]
    earliest = max(ctx.pf.start, c.release or ctx.pf.start)
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
    new = LaneState(
        tuple(sorted(lanes)), t_end + dt.timedelta(days=1), st.trial_end + ((cid, t_end),)
    )
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
    at: str
    p_removed: float
    removed: TreeNode | None = None
    not_removed: TreeNode | None = None
    value: float
    schedule: list[str]


def _dependents(ctx: Ctx, trigger: str, rest: list[str]) -> dict[str, str | None]:
    base = ctx.cands[trigger].variant_of or trigger
    out: dict[str, str | None] = {}
    for cid in rest:
        for s in ctx.cands[cid].succession:
            if s.on_removal_of in (trigger, base):
                out[cid] = s.becomes
    return out


def evaluate_branching(ctx: Ctx, order: tuple[str, ...]) -> tuple[float, TreeNode | None]:
    """Expected value of a fixed order when removals at trigger trials change later candidates."""

    def run(
        rest: list[str], st: LaneState, attempt: int, depth: int, done: list[str]
    ) -> tuple[float, TreeNode | None, list[str]]:
        value = 0.0
        sched: list[str] = []
        while rest:
            cid, rest = rest[0], rest[1:]
            if any(excluded_pair(ctx, cid, o) for o in done):
                continue
            got = place(ctx, cid, st, attempt)
            if got is None:
                continue
            slot, st = got
            done = done + [cid]
            value += slot.weight * slot.p
            sched.append(f"{cid} trial {slot.trial_start}..{slot.trial_end} p={slot.p:.3f}")
            attempt += 1
            deps = _dependents(ctx, cid, rest)
            if deps and depth < MAX_BRANCH_TRIGGERS:
                removed_rest: list[str] = []
                for r in rest:
                    repl = deps[r] if r in deps else r
                    if repl is not None:
                        removed_rest.append(repl)
                vr, tr, sr = run(removed_rest, st, attempt, depth + 1, done)
                vk, tk, sk = run(rest, st, attempt, depth + 1, done)
                node = TreeNode(
                    at=cid,
                    p_removed=slot.p,
                    value=slot.p * vr + (1 - slot.p) * vk,
                    removed=tr or TreeNode(at="(end)", p_removed=0, value=vr, schedule=sr),
                    not_removed=tk or TreeNode(at="(end)", p_removed=0, value=vk, schedule=sk),
                    schedule=sched,
                )
                return value + node.value, node, sched
        return value, None, sched

    v, tree, _ = run(list(order), initial_state(ctx), 0, 0, [])
    return v, tree


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
    for o in orders:
        v, t = evaluate_branching(ctx, o)
        if v > best[1] + 1e-12:
            best = (o, v, t)
    return best


# ------------------------------------------------------------------------ result


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


# ------------------------------------------------------------------- top level


@dataclass
class Loaded:
    pf: Portfolio
    preps: dict[str, Prepared]
    p0: dict[str, float]


def load(path: str | Path) -> Loaded:
    pf = load_portfolio(path)
    preps: dict[str, Prepared] = {}
    p0: dict[str, float] = {}
    for c in pf.candidates:
        if c.scenario is not None:
            prep = prepare(resolve(c.scenario, path))
            preps[c.id] = prep
            p0[c.id] = p_complete(prep, c.article, draws=pf.draws, seed=prep.scenario.seed)
        else:
            assert c.p is not None
            p0[c.id] = c.p
    return Loaded(pf, preps, p0)


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


def solve(loaded: Loaded, exhaustive: bool = False, joint: bool = True) -> PortfolioResult:
    pf, p0 = loaded.pf, loaded.p0
    ctx, dropped = make_ctx(pf, p0)
    plans = search(ctx, exhaustive)
    best = plans[0]
    chosen = set(best.order)
    for cid in ctx.eligible:
        if cid in chosen:
            continue
        by = [o for o in best.order if excluded_pair(ctx, cid, o)]
        if by:
            dropped.append(
                Dropped(id=cid, reason="EXCLUDED", detail=f"excluded by {', '.join(by)}")
            )
    tops: list[PlanOut] = []
    seen: set[tuple[str, ...]] = set()
    for p in plans:
        if p.order in seen or not p.order:
            continue
        seen.add(p.order)
        tops.append(PlanOut(order=list(p.order), expected_removals=p.value, slots=list(p.slots)))
        if len(tops) >= pf.top:
            break
    sens = sensitivity(pf, p0, best.order, exhaustive)
    fragile = any(r.fragile for r in sens)
    res = PortfolioResult(
        plans=tops, dropped=dropped, sensitivity=sens, fragile=fragile, exhaustive=exhaustive, p0=p0
    )
    order = best.order
    if has_succession(ctx):
        o, v, tree = best_with_succession(ctx, plans)
        res.succession_order, res.succession_value, res.decision_tree = list(o), v, tree
        order = o
    if joint and order:
        res.removals_dist = removals_dist(loaded, ctx, order)
    return res


def sensitivity(
    pf: Portfolio, p0: dict[str, float], base: tuple[str, ...], exhaustive: bool
) -> list[SensRow]:
    rows: list[SensRow] = []
    cases: list[tuple[str, float, float]] = [
        (f"fatigue delta {d:+.1f}", d, 1.0) for d in SENS_DELTAS
    ]
    cases += [(f"durations x{s}", pf.fatigue_delta, s) for s in SENS_SCALES]
    for label, d, s in cases:
        ctx, _ = make_ctx(pf, p0, d, s)
        best = search(ctx, exhaustive)[0].value
        base_v = schedule_order(ctx, base).value
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


def _match_shift(prep: Prepared, article: str | None, target: float, draws: int) -> float:
    """Uniform logit shift that makes P(complete) equal ``target`` (common random numbers)."""
    base = p_complete(prep, article, draws=draws)
    if abs(base - target) < 1e-9:
        return 0.0
    lo, hi = (-8.0, 0.0) if target < base else (0.0, 8.0)
    for _ in range(30):
        mid = (lo + hi) / 2
        if p_complete(prep, article, draws=draws, extra=mid) < target:
            lo = mid
        else:
            hi = mid
        if hi - lo < 1e-3:
            break
    return (lo + hi) / 2


def removals_dist(loaded: Loaded, ctx: Ctx, order: tuple[str, ...]) -> RemovalsDist:
    pf = loaded.pf
    plan = schedule_order(ctx, order)
    slots = {s.id: s for s in plan.slots}
    involved: list[str] = list(plan.order)
    for cid in plan.order:
        for s in ctx.cands[cid].succession:
            if s.becomes and s.becomes not in involved:
                involved.append(s.becomes)
    notes: list[str] = []

    def attempt_of(cid: str) -> int:
        if cid in slots:
            return slots[cid].attempt
        for c in plan.order:
            if any(s.becomes == cid for s in ctx.cands[c].succession):
                return slots[c].attempt
        return 0

    ps = {cid: _fatigued(ctx.p0[cid], ctx.delta, attempt_of(cid)) for cid in involved}
    fixed = [c for c in involved if c not in loaded.preps]
    if not any(c in loaded.preps for c in involved) and not any(
        ctx.cands[c].succession for c in plan.order
    ):
        dist = poisson_binomial([ps[c] for c in plan.order])
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
    for cid in involved:
        prep = loaded.preps.get(cid)
        if prep is None:
            continue
        for ch, body in prep.comp.bodies.items():
            for m in body.roster:
                shared.setdefault((ch, m.bloc), rng.standard_normal(draws))
    outcome: dict[str, np.ndarray] = {}
    for i, cid in enumerate(involved):
        prep = loaded.preps.get(cid)
        if prep is None:
            outcome[cid] = rng.random(draws) < ps[cid]
            continue
        art = ctx.cands[cid].article or prep.scenario.articles[0]
        shift = _match_shift(prep, art, ps[cid], draws)
        path = path_for(prep.rules, prep.scenario, default_path(prep))
        raw = run_raw(prep, art, path, draws, pf.seed + 1000 + i, prep.scenario.rho, shift, shared)
        outcome[cid] = raw.complete
    if fixed:
        notes.append(f"fixed-p candidates drawn independently: {', '.join(fixed)}")
    final = {cid: outcome[cid].copy() for cid in plan.order}
    for j, cid in enumerate(plan.order):
        for later in plan.order[j + 1 :]:
            for s in ctx.cands[later].succession:
                if s.on_removal_of == cid:
                    repl = outcome[s.becomes] if s.becomes else np.zeros(draws, dtype=bool)
                    final[later] = np.where(final[cid], repl, final[later])
    counts = np.sum([final[c] for c in plan.order], axis=0).astype(int)
    freq = np.bincount(counts, minlength=len(plan.order) + 1) / draws
    mean = float(counts.mean())
    sd = float(counts.std())
    marg = [float(final[c].mean()) for c in plan.order]
    ind_sd = math.sqrt(sum(p * (1 - p) for p in marg))
    notes.append("one shared party-swing stream across scenario candidates, plus member noise")
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


def as_dict(res: PortfolioResult) -> dict[str, Any]:
    return res.model_dump(mode="json")
