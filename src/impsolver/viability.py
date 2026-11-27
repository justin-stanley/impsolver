"""Rank user-supplied scenarios by how close each is to completing its path.

The tool ranks the scenarios it is given and never proposes targets of its own.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path

from .flips import find_flips
from .prepare import Prepared, prepare
from .results import ViabilityLabel, ViabilityRow
from .simulate import p_complete

GAP_MAX = 8.0
GAP_TOL = 0.01


@dataclass
class Case:
    source: str
    prep: Prepared


def _p_complete(prep: Prepared, delta: float, draws: int) -> float:
    """P(at least the best article completes) under a uniform logit shift toward PRO."""
    return max(p_complete(prep, a, draws=draws, extra=delta) for a in prep.scenario.articles)


def support_gap(prep: Prepared, target_p: float, draws: int) -> float | None:
    """Smallest uniform logit shift that lifts P(complete) to target_p (common random numbers)."""
    if _p_complete(prep, 0.0, draws) >= target_p:
        return 0.0
    if _p_complete(prep, GAP_MAX, draws) < target_p:
        return None
    lo, hi = 0.0, GAP_MAX
    while hi - lo > GAP_TOL:
        mid = (lo + hi) / 2
        if _p_complete(prep, mid, draws) >= target_p:
            hi = mid
        else:
            lo = mid
    return round(hi, 4)


def min_flips(prep: Prepared) -> int | None:
    best: int | None = None
    for a in prep.scenario.articles:
        r = find_flips(prep, article=a, method="ilp")
        if r.status == "INFEASIBLE":
            continue
        n = r.n_flips
        best = n if best is None else min(best, n)
    return best


def assess(
    cases: list[Case], target_p: float = 0.5, max_gap: float = 2.0, draws: int = 20_000
) -> list[ViabilityRow]:
    rows: list[ViabilityRow] = []
    for c in cases:
        pc = _p_complete(c.prep, 0.0, draws)
        gap = support_gap(c.prep, target_p, draws)
        label: ViabilityLabel = (
            "viable"
            if pc >= target_p
            else "reachable"
            if gap is not None and gap <= max_gap
            else "out of reach"
        )
        rows.append(
            ViabilityRow(
                scenario=c.source,
                target=c.prep.scenario.target.name,
                p_complete=pc,
                flips=min_flips(c.prep),
                support_gap=gap,
                label=label,
            )
        )
    rows.sort(
        key=lambda r: (
            -r.p_complete,
            r.flips if r.flips is not None else math.inf,
            r.support_gap if r.support_gap is not None else math.inf,
        )
    )
    return rows


def assess_paths(paths: list[str | Path], **kw: float) -> list[ViabilityRow]:
    return assess([Case(str(p), prepare(p)) for p in paths], **kw)  # type: ignore[arg-type]
