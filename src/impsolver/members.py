# SPDX-FileCopyrightText: 2026 Justin Stanley
# SPDX-License-Identifier: MIT
"""Per-member probability resolution."""

from __future__ import annotations

import math

from .model import STAR, Member, PriorValue, Scenario
from .uncertainty import Bound, value


class ResolutionError(Exception):
    pass


def logit(p: float) -> float:
    return math.log(p / (1.0 - p))


def sigmoid(x: float) -> float:
    if x >= 0:
        return 1.0 / (1.0 + math.exp(-x))
    e = math.exp(x)
    return e / (1.0 + e)


def shifted(p: float, delta: float) -> float:
    """sigmoid(logit p + delta). 0 and 1 stay fixed."""
    if p <= 0.0 or p >= 1.0 or delta == 0.0:
        return p
    return sigmoid(logit(p) + delta)


def _lookup(table: dict[str, PriorValue], stage: str) -> PriorValue | None:
    if stage in table:
        return table[stage]
    return table.get(STAR)


class Resolver:
    """Resolve p_pro: override, member stage, member '*', party stage, party '*'; then shifts.

    An override or party prior may be a range or a Beta distribution. ``bound`` picks which
    number stands for it: ``"point"`` (the mean; a range's midpoint), or ``"low"`` / ``"high"``
    (a range's ends, a Beta's 5th / 95th percentile) for the deterministic bounds.
    """

    def __init__(self, scenario: Scenario) -> None:
        self.scenario = scenario

    def spec(self, m: Member, stage: str) -> tuple[PriorValue, str]:
        """The prior value as given (a number, range or Beta) and where it came from."""
        ov = self.scenario.overrides.get(m.id)
        if ov is not None:
            v = _lookup(ov, stage)
            if v is not None:
                return v, "override"
        mv = m.p_pro.get(stage, m.p_pro.get(STAR))
        if mv is not None:
            return mv, m.p_source or "member"
        party = self.scenario.party_priors.get(m.bloc)
        if party is not None:
            v = _lookup(party, stage)
            if v is not None:
                return v, "party_prior"
        raise ResolutionError(
            f"no probability for member {m.id} ({m.name}, bloc {m.bloc}) at stage {stage}"
        )

    def base(self, m: Member, stage: str, bound: Bound = "point") -> tuple[float, str]:
        v, source = self.spec(m, stage)
        return value(v, bound), source

    def delta(self, m: Member, stage: str, article: str) -> float:
        total = 0.0
        for s in self.scenario.shifts:
            if s.bloc not in (m.bloc, STAR):
                continue
            if s.stage is not None and s.stage != stage:
                continue
            if s.article is not None and s.article != article:
                continue
            total += s.delta
        return total

    def resolve(
        self, m: Member, stage: str, article: str, extra: float = 0.0, bound: Bound = "point"
    ) -> float:
        p, _ = self.base(m, stage, bound)
        return shifted(p, self.delta(m, stage, article) + extra)
