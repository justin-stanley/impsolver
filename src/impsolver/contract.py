# SPDX-FileCopyrightText: 2026 Justin Stanley
# SPDX-License-Identifier: MIT
"""Report contract: the extra fields that let a page draw from the JSON report alone.

``extend`` adds to a :class:`~impsolver.portfolio.PortfolioResult`:

* ``meta`` and ``inputs``: what was run, and the portfolio as given;
* on every slot: its House lane, the rule that set each date, waiting and slack;
* on every plan: a session-day budget per resource;
* on every dropped candidate: the numbers behind its reason;
* ``gates``: per scenario candidate and gate, the rule, the tally by bloc and every member's
  supplied probability and classification.

Everything here restates the inputs or the schedule. Nothing is simulated.
"""

from __future__ import annotations

import bisect
import datetime as dt
from dataclasses import replace
from pathlib import Path as FsPath
from typing import TYPE_CHECKING, Literal

import numpy as np
from pydantic import BaseModel

from . import __version__
from .deterministic import default_path
from .model import Stage, TieBreak
from .paths import path_for
from .prepare import Prepared
from .thresholds import membership_base, required_pro, tie_mode
from .uncertainty import has_uncertainty

if TYPE_CHECKING:
    from .portfolio import Ctx, Dropped, Loaded, PlanOut, PortfolioResult, Slot, WorkCalendar

REPORT_SCHEMA_VERSION = 2

Resource = Literal["house_lanes", "senate_committee", "senate_floor"]
HouseReason = Literal["window_start", "lane_free", "release", "after", "not_before"]
TrialReason = Literal["ready", "committee", "floor_busy"]
MemberClass = Literal["PRO", "CON", "UNCERTAIN", "ABSENT"]
CLASS_CODE: dict[MemberClass, str] = {"PRO": "P", "CON": "C", "UNCERTAIN": "U", "ABSENT": "A"}


class ScenarioMeta(BaseModel):
    file: str
    target: str
    seed: int
    rho: float
    cutoffs: tuple[float, float]
    attendance: str
    uncertainty_draws: int
    uncertain_priors: bool = False  # a prior is a range or a Beta, so bounds differ from p


class ReportMeta(BaseModel):
    impsolver_version: str
    draws: int
    portfolio_file: str | None = None
    scenarios: dict[str, ScenarioMeta] = {}


class BudgetRow(BaseModel):
    """Session days of one resource between the window's start and deadline."""

    resource: Resource
    available: int
    used: int


class RuleOut(BaseModel):
    kind: str
    p: int
    q: int
    direction: str
    present_in_denominator: bool
    tie_break: TieBreak
    sentence: str


class BlocTally(BaseModel):
    bloc: str
    seats: int
    pro: int
    con: int
    uncertain: int
    absent: int
    expected_pro: float


class GateDetail(BaseModel):
    """One gate of one article: the rule, the count by bloc, and every member.

    The member columns (``p``, ``source``, ``cls``) line up with the chamber roster in
    ``ChamberRoster``. ``source`` holds indexes into ``sources``; ``cls`` has one letter per
    member: P (counted PRO), C (counted CON), U (uncertain), A (absent).
    """

    stage: str
    chamber: str
    article: str
    label: str
    optional: bool
    seats: int
    vacancies: int
    present: int
    base: int  # membership base, for rules that are a fraction of the membership
    required: int
    rule: RuleOut
    blocs: list[BlocTally]
    p: list[float]
    source: list[int]
    sources: list[str]
    cls: str
    rank_pivot: str | None = None


class ChamberRoster(BaseModel):
    ids: list[str]
    names: list[str]
    blocs: list[str]


class CaseGates(BaseModel):
    article: str
    path: str
    rosters: dict[str, ChamberRoster]
    gates: list[GateDetail]


# ------------------------------------------------------------------------ meta


def _basename(source: str | None) -> str | None:
    if not source or source.startswith("<"):
        return None
    return FsPath(source).name


def meta(loaded: Loaded) -> ReportMeta:
    scen = {
        cid: ScenarioMeta(
            file=_basename(prep.source) or prep.source,
            target=prep.scenario.target.name,
            seed=prep.scenario.seed,
            rho=prep.scenario.rho,
            cutoffs=prep.scenario.cutoffs,
            attendance=prep.scenario.attendance,
            uncertainty_draws=prep.scenario.uncertainty_draws,
            uncertain_priors=has_uncertainty(prep.scenario),
        )
        for cid, prep in loaded.preps.items()
    }
    return ReportMeta(
        impsolver_version=__version__,
        draws=loaded.pf.draws,
        portfolio_file=_basename(loaded.source),
        scenarios=scen,
    )


# -------------------------------------------------------------------- calendar


def days_between(cal: WorkCalendar, a: dt.date, b: dt.date) -> int:
    """Working days of ``cal`` from ``a`` to ``b`` inclusive (0 when ``b`` is before ``a``)."""
    if b < a:
        return 0
    lo = bisect.bisect_left(cal.days, a.toordinal())
    hi = bisect.bisect_right(cal.days, b.toordinal())
    return hi - lo


ONE = dt.timedelta(days=1)


def annotate(ctx: Ctx, slots: list[Slot]) -> list[BudgetRow]:
    """Fill each slot's lane, date reasons, waiting and slack in place; return the day budget.

    ``slots`` must be in the order they were scheduled. The scheduler always gives a case the
    lane that frees first, so replaying that choice recovers the lane each case used.
    """
    pf = ctx.pf
    lanes: list[tuple[dt.date, str | None]] = [(pf.start, None)] * pf.house_concurrency
    floor_last: tuple[dt.date, str] | None = None
    ends: dict[str, dt.date] = {}
    used: dict[Resource, int] = {"house_lanes": 0, "senate_committee": 0, "senate_floor": 0}
    for s in slots:
        c = ctx.cands[s.id]
        lane = min(range(len(lanes)), key=lambda i: (lanes[i][0], i))
        free, prev = lanes[lane]
        s.house_lane = lane + 1
        deps = [d for d in c.after if d in ends and ends[d] + ONE == s.house_start]
        if deps:
            s.house_start_reason, s.house_start_after = "after", deps[0]
        elif c.release is not None and c.release == s.house_start and c.release > pf.start:
            s.house_start_reason = "release"
        elif free == s.house_start and prev is not None:
            s.house_start_reason, s.house_start_after = "lane_free", prev
        elif s.house_start == pf.start:
            s.house_start_reason = "window_start"
        else:
            s.house_start_reason = "not_before"
        lanes[lane] = (s.house_end + ONE, s.id)
        s.house_days = days_between(ctx.cals.house, s.house_start, s.house_end)
        used["house_lanes"] += s.house_days

        s.ready = s.house_end + ONE
        floor_ready = s.ready
        if c.senate_committee:
            s.committee_start = s.ready
            s.committee_end = ctx.cals.senate.nth_from(s.ready, ctx.days(c.senate_days))
            floor_ready = s.committee_end + ONE
            used["senate_committee"] += days_between(
                ctx.cals.senate, s.committee_start, s.committee_end
            )
        if s.trial_start > floor_ready and floor_last is not None:
            s.trial_start_reason, s.trial_start_after = "floor_busy", floor_last[1]
        else:
            s.trial_start_reason = "committee" if c.senate_committee else "ready"
        s.wait_trial_days = days_between(ctx.cals.trial, floor_ready, s.trial_start - ONE)
        s.trial_days = days_between(ctx.cals.trial, s.trial_start, s.trial_end)
        used["senate_floor"] += s.trial_days
        limit = ctx.deadline(c)
        s.slack_days = (
            None
            if limit.year == dt.MAXYEAR
            else days_between(ctx.cals.trial, s.trial_end + ONE, limit)
        )
        floor_last = (s.trial_end, s.id)
        ends[s.id] = s.trial_end
    house = days_between(ctx.cals.house, pf.start, pf.deadline)
    return [
        BudgetRow(
            resource="house_lanes",
            available=house * pf.house_concurrency,
            used=used["house_lanes"],
        ),
        BudgetRow(
            resource="senate_committee",
            available=days_between(ctx.cals.senate, pf.start, pf.deadline),
            used=used["senate_committee"],
        ),
        BudgetRow(
            resource="senate_floor",
            available=days_between(ctx.cals.trial, pf.start, pf.deadline),
            used=used["senate_floor"],
        ),
    ]


def annotate_plan(ctx: Ctx, plan: PlanOut) -> None:
    plan.budget = annotate(ctx, plan.slots)


# --------------------------------------------------------------------- dropped


def _earliest_alone(ctx: Ctx, cid: str) -> Slot | None:
    """Where ``cid`` would land if it were scheduled first with no deadline at all."""
    from .portfolio import FAR, initial_state, make_calendars, place

    horizon = ctx.pf.deadline + dt.timedelta(days=3 * 365 - 1)
    cands = [
        c.model_copy(update={"deadline": None, "after": []}) if c.id == cid else c
        for c in ctx.pf.candidates
    ]
    pf = ctx.pf.model_copy(update={"deadline": horizon, "candidates": cands})
    alone = replace(
        ctx, pf=pf, cands={c.id: c for c in cands}, cals=make_calendars(pf), eligible=[cid]
    )
    got = place(alone, cid, initial_state(alone), 0)
    if got is None or got[0].trial_end >= FAR:
        return None
    return got[0]


def drop_numbers(
    ctx: Ctx, order: tuple[str, ...], dropped: list[Dropped], exhaustive: bool
) -> None:
    """Attach the numbers behind each dropped candidate's reason, in place."""
    from .portfolio import _best_value, _order_value, excluded_pair

    base = _order_value(ctx, order) if order else 0.0
    for d in dropped:
        c = ctx.cands[d.id]
        if d.reason == "LOW_P":
            d.numbers = {"p": ctx.p0_range(d.id)[1], "p_floor": ctx.pf.p_floor}
        elif d.reason == "NO_FIT":
            limit = ctx.deadline(c)
            slot = _earliest_alone(ctx, d.id)
            d.numbers = {
                "deadline": limit.isoformat(),
                "earliest_end": slot.trial_end.isoformat() if slot else None,
                "days_over": (slot.trial_end - limit).days if slot else None,
            }
        elif d.reason == "EXCLUDED":
            by = [o for o in order if excluded_pair(ctx, d.id, o)]
            without = replace(ctx, eligible=[e for e in ctx.eligible if e not in by])
            d.numbers = {
                "by": by,
                "value": base,
                "swap_value": _best_value(without, exhaustive)[1],
            }
        elif d.reason == "DEPENDENCY_DROPPED":
            d.numbers = {"waits_on": [x for x in c.after if x not in order]}
        elif d.reason == "NOT_SELECTED":
            tries = [
                _order_value(ctx, (*order[:i], d.id, *order[i:])) for i in range(len(order) + 1)
            ]
            d.numbers = {"value_without": base, "value_with": max(tries)}


# ----------------------------------------------------------------------- gates


def _fraction(p: int, q: int) -> str:
    return {(2, 3): "Two thirds", (1, 2): "Half", (3, 5): "Three fifths"}.get((p, q), f"{p}/{q}")


def rule_sentence(st: Stage, voting: int, base: int, need: int, tie: TieBreak) -> str:
    """The gate's rule in one or two plain sentences, with the count it implies."""
    rule = st.rule
    if rule.kind == "majority_of_votes_cast":
        if st.pass_direction == "pass":
            text = f"The motion needs more yeas than nays. PRO votes yea; with {voting} voting, "
            text += f"PRO needs {need}."
            if tie == "none":
                text += " A tie defeats it."
        else:
            text = "The motion carries only with more yeas than nays, and PRO wants it to fail. "
            text += f"PRO votes nay; with {voting} voting, PRO needs {need}."
            if tie == "none":
                text += " A tie defeats the motion, which is enough for PRO."
        if tie != "none":
            text += f" A tie is taken to go to {tie.upper()}, as set by senate_tie_break."
        return text
    frac = _fraction(rule.p, rule.q)
    if rule.kind == "fraction_of_present":
        return f"{frac} of the members present. With {voting} present, PRO needs {need}."
    return f"{frac} of the membership. With a base of {base}, PRO needs {need}."


def gate_detail(prep: Prepared, st: Stage, article: str) -> GateDetail:
    lo, hi = prep.scenario.cutoffs
    body = prep.comp.bodies[st.chamber]
    members = body.roster
    uncertain = has_uncertainty(prep.scenario)
    p = prep.probs(st.chamber, st.id, article)
    p_low = prep.probs(st.chamber, st.id, article, bound="low") if uncertain else p
    p_high = prep.probs(st.chamber, st.id, article, bound="high") if uncertain else p
    present = prep.present_mask(st.chamber)
    is_pro = present & (p_low >= hi)
    is_con = present & (p_high <= lo)
    voting = int(present.sum())
    base = membership_base(st.rule, body.seats, body.vacancies)
    tie = tie_mode(st, prep.scenario.senate_tie_break)
    need = required_pro(st.rule, st.pass_direction, voting, 0, base, tie)

    classes: list[MemberClass] = [
        "ABSENT" if not present[i] else "PRO" if is_pro[i] else "CON" if is_con[i] else "UNCERTAIN"
        for i in range(len(members))
    ]
    sources: list[str] = []
    source_idx: list[int] = []
    for m in members:
        src = prep.resolver.base(m, st.id)[1]
        if src not in sources:
            sources.append(src)
        source_idx.append(sources.index(src))

    blocs: dict[str, BlocTally] = {}
    for m, k, pi in zip(members, classes, p, strict=True):
        b = blocs.setdefault(
            m.bloc,
            BlocTally(bloc=m.bloc, seats=0, pro=0, con=0, uncertain=0, absent=0, expected_pro=0.0),
        )
        b.seats += 1
        if k == "PRO":
            b.pro += 1
        elif k == "CON":
            b.con += 1
        elif k == "UNCERTAIN":
            b.uncertain += 1
        else:
            b.absent += 1
        if k != "ABSENT":
            b.expected_pro += float(pi)
    for b in blocs.values():
        b.expected_pro = round(b.expected_pro, 6)

    # The member at position ``need`` when present members are sorted by supplied p.
    ranked = sorted(
        (i for i in range(len(members)) if present[i]), key=lambda i: (-float(p[i]), members[i].id)
    )
    pivot = members[ranked[need - 1]].id if 1 <= need <= len(ranked) else None
    return GateDetail(
        stage=st.id,
        chamber=st.chamber,
        article=article,
        label=st.label,
        optional=st.optional,
        seats=body.seats,
        vacancies=body.vacancies,
        present=voting,
        base=base,
        required=need,
        rule=RuleOut(
            kind=st.rule.kind,
            p=st.rule.p,
            q=st.rule.q,
            direction=st.pass_direction,
            present_in_denominator=st.rule.present_in_denominator,
            tie_break=tie,
            sentence=rule_sentence(st, voting, base, need, tie),
        ),
        blocs=sorted(blocs.values(), key=lambda b: (-b.seats, b.bloc)),
        p=[round(float(x), 6) for x in np.asarray(p)],
        source=source_idx,
        sources=sources,
        cls="".join(CLASS_CODE[k] for k in classes),
        rank_pivot=pivot,
    )


def case_gates(prep: Prepared, article: str) -> CaseGates:
    path = path_for(prep.rules, prep.scenario, default_path(prep))
    chambers = sorted({st.chamber for st in path.all_stages})
    rosters = {
        str(ch): ChamberRoster(
            ids=[m.id for m in prep.members(ch)],
            names=[m.name for m in prep.members(ch)],
            blocs=[m.bloc for m in prep.members(ch)],
        )
        for ch in chambers
    }
    return CaseGates(
        article=article,
        path=path.name,
        rosters=rosters,
        gates=[gate_detail(prep, st, article) for st in path.all_stages],
    )


# ---------------------------------------------------------------------- extend


def extend(
    res: PortfolioResult, loaded: Loaded, ctx: Ctx, order: tuple[str, ...], exhaustive: bool
) -> None:
    """Add the report-contract fields to ``res`` in place."""
    res.schema_version = REPORT_SCHEMA_VERSION
    res.meta = meta(loaded)
    res.inputs = loaded.pf
    for plan in res.plans:
        annotate_plan(ctx, plan)
    drop_numbers(ctx, order, res.dropped, exhaustive)
    for cid, art in res.pivots.items():
        res.gates[cid] = case_gates(loaded.preps[cid], art.article)
