"""Per-member probability resolution."""

from __future__ import annotations

import math

from .model import STAR, Member, Scenario


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


def _lookup(table: dict[str, float], stage: str) -> float | None:
    if stage in table:
        return table[stage]
    return table.get(STAR)


class Resolver:
    """Resolve p_pro: override, member stage, member '*', party stage, party '*'; then shifts."""

    def __init__(self, scenario: Scenario) -> None:
        self.scenario = scenario

    def base(self, m: Member, stage: str) -> tuple[float, str]:
        ov = self.scenario.overrides.get(m.id)
        if ov is not None:
            v = _lookup(ov, stage)
            if v is not None:
                return v, "override"
        v = _lookup(m.p_pro, stage)
        if v is not None:
            return v, m.p_source or "member"
        party = self.scenario.party_priors.get(m.bloc)
        if party is not None:
            v = _lookup(party, stage)
            if v is not None:
                return v, "party_prior"
        raise ResolutionError(
            f"no probability for member {m.id} ({m.name}, bloc {m.bloc}) at stage {stage}"
        )

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

    def resolve(self, m: Member, stage: str, article: str, extra: float = 0.0) -> float:
        p, _ = self.base(m, stage)
        return shifted(p, self.delta(m, stage, article) + extra)
