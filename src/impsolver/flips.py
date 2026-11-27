"""Minimal changes that would make every chosen gate pass (greedy and ILP)."""

from __future__ import annotations

import re
from dataclasses import dataclass

import numpy as np
import numpy.typing as npt
import pulp

from .deterministic import default_path
from .model import Chamber, Member, Stage
from .paths import path_for
from .prepare import Prepared
from .results import FlipMember, FlipResult
from .thresholds import has_quorum, membership_base, pro_wins

ABSENCE_NOTE = "absences are procedural sensitivity, not a recommendation"
CHANGE_WEIGHT = 10_000.0
TIE_EPS = 1e-6
# Secondary flip costs are at most 1, so this makes a flip beat an absence at equal counts.
ABSENCE_PENALTY = 2.0
GATE_STANCE_COST = 1e-3


class FlipError(Exception):
    pass


def parse_constraints(specs: list[str]) -> dict[str, int]:
    """Parse 'BLOC<=N' strings. When a bloc appears twice, the tightest bound wins."""
    out: dict[str, int] = {}
    for s in specs:
        m = re.fullmatch(r"\s*([A-Za-z0-9_\-]+)\s*<=\s*(\d+)\s*", s)
        if not m:
            raise FlipError(f"bad constraint {s!r}; expected BLOC<=N")
        bloc, n = m.group(1), int(m.group(2))
        out[bloc] = min(n, out.get(bloc, n))
    return out


@dataclass
class _ChamberData:
    chamber: Chamber
    stages: list[Stage]
    members: list[Member]  # present members only
    p: npt.NDArray[np.float64]  # [gate, member]
    base: npt.NDArray[np.bool_]  # [gate, member], baseline PRO
    seats: int
    vacancies: int


def _chamber_data(prep: Prepared, article: str, stages: list[Stage]) -> list[_ChamberData]:
    hi = prep.scenario.cutoffs[1]
    out: list[_ChamberData] = []
    for chamber in ("house", "senate"):
        sts = [s for s in stages if s.chamber == chamber]
        if not sts:
            continue
        body = prep.comp.bodies[chamber]
        mask = prep.present_mask(chamber)
        members = [m for m, k in zip(body.roster, mask, strict=True) if k]
        p = np.vstack([prep.probs(chamber, s.id, article)[mask] for s in sts])
        out.append(_ChamberData(chamber, sts, members, p, p >= hi, body.seats, body.vacancies))
    return out


def _wins(st: Stage, pro: int, voting: int, absent_extra: int, d: _ChamberData) -> bool:
    base = membership_base(st.rule, d.seats, d.vacancies)
    n = voting - absent_extra
    sworn = d.seats - d.vacancies
    return bool(has_quorum(n, sworn)) and bool(
        pro_wins(st.rule, st.pass_direction, pro, n - pro, 0, base)
    )


def _target_stages(prep: Prepared, path_name: str | None, gate: str | None) -> list[Stage]:
    path = path_for(prep.rules, prep.scenario, path_name or default_path(prep))
    if gate is None:
        return list(path.stages)
    for st in path.all_stages:
        if st.id == gate:
            return [st]
    raise FlipError(f"gate {gate} is not on path {path.name}")


def find_flips(
    prep: Prepared,
    article: str | None = None,
    path_name: str | None = None,
    gate: str | None = None,
    method: str = "ilp",
    constraints: list[str] | None = None,
    exclude: list[str] | None = None,
    allow_absence: bool = False,
    absence_cost: float = 1.0,
    per_gate_stance: bool = False,
) -> FlipResult:
    art = article or prep.scenario.articles[0]
    if art not in prep.scenario.articles:
        raise FlipError(f"unknown article {art}")
    stages = _target_stages(prep, path_name, gate)
    caps = parse_constraints(constraints or [])
    excl = set(exclude or [])
    if allow_absence and method != "ilp":
        raise FlipError("--allow-absence needs the ILP (drop --greedy)")
    data = _chamber_data(prep, art, stages)
    gate_ids = [s.id for s in stages]
    ids = {m.id for d in data for m in d.members}
    all_ids = {m.id for b in prep.comp.bodies.values() for m in b.roster}
    blocs = {m.bloc for d in data for m in d.members}
    missing = sorted(excl - all_ids)
    if missing:
        raise FlipError(f"--exclude: unknown member id(s) {', '.join(missing)}")
    absent = sorted(excl & (all_ids - ids))
    if absent:
        prep.warnings.append(f"--exclude: {', '.join(absent)} not voting in the gates solved")
    bad_caps = sorted(set(caps) - blocs)
    if bad_caps:
        raise FlipError(f"constraint: unknown bloc(s) {', '.join(bad_caps)} in the gates solved")

    already = all(
        _wins(st, int(d.base[g].sum()), len(d.members), 0, d)
        for d in data
        for g, st in enumerate(d.stages)
    )
    if already:
        return FlipResult(
            article=art,
            gates=gate_ids,
            method="ilp" if method == "ilp" else "greedy",
            status="ALREADY_PASSING",
            n_flips=0,
            n_absences=0,
            members=[],
        )
    if method == "ilp":
        return _ilp(art, gate_ids, data, caps, excl, allow_absence, absence_cost, per_gate_stance)
    return _greedy(art, gate_ids, data, caps, excl)


def _greedy(
    art: str, gate_ids: list[str], data: list[_ChamberData], caps: dict[str, int], excl: set[str]
) -> FlipResult:
    chosen: list[FlipMember] = []
    used: dict[str, int] = {}
    for d in data:
        flipped: set[int] = set()
        for g, st in enumerate(d.stages):
            while True:
                pro = int(d.base[g].sum()) + sum(1 for i in flipped if not d.base[g, i])
                if _wins(st, pro, len(d.members), 0, d):
                    break
                best: int | None = None
                for i in np.argsort(1.0 - d.p[g], kind="stable"):
                    i = int(i)
                    m = d.members[i]
                    if d.base[g, i] or i in flipped or m.id in excl:
                        continue
                    if m.bloc in caps and used.get(m.bloc, 0) >= caps[m.bloc]:
                        continue
                    best = i
                    break
                if best is None:
                    return FlipResult(
                        article=art,
                        gates=gate_ids,
                        method="greedy",
                        status="INFEASIBLE",
                        n_flips=0,
                        n_absences=0,
                        members=[],
                    )
                flipped.add(best)
                used[d.members[best].bloc] = used.get(d.members[best].bloc, 0) + 1
        for i in sorted(flipped, key=lambda i: d.members[i].id):
            m = d.members[i]
            chosen.append(
                FlipMember(
                    chamber=d.chamber,
                    id=m.id,
                    name=m.name,
                    bloc=m.bloc,
                    p=float(d.p[:, i].min()),
                    action="flip",
                    gates=[st.id for g, st in enumerate(d.stages) if not d.base[g, i]],
                )
            )
    return FlipResult(
        article=art,
        gates=gate_ids,
        method="greedy",
        status="OK",
        n_flips=len(chosen),
        n_absences=0,
        members=chosen,
    )


def _ilp(
    art: str,
    gate_ids: list[str],
    data: list[_ChamberData],
    caps: dict[str, int],
    excl: set[str],
    allow_absence: bool,
    absence_cost: float,
    per_gate: bool,
) -> FlipResult:
    prob = pulp.LpProblem("flips", pulp.LpMinimize)
    objective: list[pulp.LpAffineExpression] = []
    bloc_terms: dict[str, list[pulp.LpAffineExpression]] = {}
    records: list[
        tuple[
            _ChamberData,
            int,
            dict[int, pulp.LpVariable],
            pulp.LpVariable | None,
            pulp.LpVariable | None,
        ]
    ] = []
    rank = 0
    for ci, d in enumerate(data):
        n_g, n_m = d.base.shape
        pro_terms: list[list[pulp.LpAffineExpression | int]] = [[] for _ in range(n_g)]
        absent_terms: list[pulp.LpVariable] = []
        for i, m in enumerate(d.members):
            frozen = m.id in excl
            xg: dict[int, pulp.LpVariable] = {}
            y: pulp.LpVariable | None = None
            a: pulp.LpVariable | None = None
            needs = [g for g in range(n_g) if not d.base[g, i]]
            if needs and not frozen:
                if per_gate:
                    y = pulp.LpVariable(f"y_{ci}_{i}", cat="Binary")
                    for g in needs:
                        xg[g] = pulp.LpVariable(f"x_{ci}_{g}_{i}", cat="Binary")
                        prob += xg[g] <= y
                        objective.append(GATE_STANCE_COST * xg[g])  # no needless gate flips
                else:
                    y = pulp.LpVariable(f"x_{ci}_{i}", cat="Binary")
                    for g in needs:
                        xg[g] = y
                if allow_absence and len(needs) == n_g:
                    a = pulp.LpVariable(f"a_{ci}_{i}", cat="Binary")
                    prob += y + a <= 1
                    absent_terms.append(a)
            for g in range(n_g):
                pro_terms[g].append(1 if d.base[g, i] else (xg[g] if g in xg else 0))
            rank += 1
            if y is not None:
                cost = float(np.mean(1.0 - d.p[needs, i]))
                objective.append((CHANGE_WEIGHT + cost + TIE_EPS * rank) * y)
                bloc_terms.setdefault(m.bloc, []).append(1 * y)
            if a is not None:
                objective.append(
                    (CHANGE_WEIGHT * absence_cost + ABSENCE_PENALTY + TIE_EPS * rank) * a
                )
                bloc_terms.setdefault(m.bloc, []).append(1 * a)
            records.append((d, i, xg, y, a))
        n_absent = pulp.lpSum(absent_terms) if absent_terms else 0
        sworn = d.seats - d.vacancies
        prob += n_m - n_absent >= sworn // 2 + 1
        for g, st in enumerate(d.stages):
            pro = pulp.lpSum(pro_terms[g])
            voting = n_m - n_absent
            rule = st.rule
            if rule.kind == "majority_of_votes_cast":
                prob += 2 * pro - voting >= (1 if st.pass_direction == "pass" else 0)
            elif st.pass_direction != "pass":
                raise FlipError(f"ILP does not support fail-direction fraction gate {st.id}")
            elif rule.kind == "fraction_of_present":
                prob += rule.q * pro >= rule.p * voting
            else:
                prob += rule.q * pro >= rule.p * membership_base(rule, d.seats, d.vacancies)
    for bloc, terms in bloc_terms.items():
        if bloc in caps:
            prob += pulp.lpSum(terms) <= caps[bloc]
    prob += pulp.lpSum(objective)
    prob.solve(pulp.PULP_CBC_CMD(msg=False))
    if pulp.LpStatus[prob.status] != "Optimal":
        return FlipResult(
            article=art,
            gates=gate_ids,
            method="ilp",
            status="INFEASIBLE",
            n_flips=0,
            n_absences=0,
            members=[],
        )
    chosen: list[FlipMember] = []
    n_abs = 0
    for d, i, xg, y, a in records:
        m = d.members[i]
        if y is not None and (y.value() or 0) > 0.5:
            gates = [d.stages[g].id for g, v in xg.items() if (v.value() or 0) > 0.5]
            chosen.append(
                FlipMember(
                    chamber=d.chamber,
                    id=m.id,
                    name=m.name,
                    bloc=m.bloc,
                    p=float(d.p[list(xg), i].min()),
                    action="flip",
                    gates=gates,
                )
            )
        if a is not None and (a.value() or 0) > 0.5:
            n_abs += 1
            chosen.append(
                FlipMember(
                    chamber=d.chamber,
                    id=m.id,
                    name=m.name,
                    bloc=m.bloc,
                    p=float(d.p[:, i].min()),
                    action="absent",
                    gates=[s.id for s in d.stages],
                )
            )
    return FlipResult(
        article=art,
        gates=gate_ids,
        method="ilp",
        status="OK",
        n_flips=sum(1 for c in chosen if c.action == "flip"),
        n_absences=n_abs,
        members=chosen,
        note=ABSENCE_NOTE if n_abs else None,
    )
