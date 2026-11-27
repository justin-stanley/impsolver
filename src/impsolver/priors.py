# SPDX-FileCopyrightText: 2026 Justin Stanley
# SPDX-License-Identifier: MIT
"""Defection prior: move party-prior probabilities by each member's historical break rate."""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from .members import logit, sigmoid
from .model import STAR, Alignment, Composition, DefectionPrior, Member, RuleSet, Scenario

EPS = 1e-6


class PriorError(Exception):
    pass


def _clip(p: float) -> float:
    return min(max(p, EPS), 1.0 - EPS)


@dataclass(frozen=True)
class Propensity:
    breaks: int
    votes: int
    bloc_rate: float
    source: str
    weight: float = 1.0

    def rate(self, pseudo_votes: float) -> float:
        return (self.breaks + pseudo_votes * self.bloc_rate) / (self.votes + pseudo_votes)

    def excess(self, pseudo_votes: float) -> float:
        return logit(_clip(self.rate(pseudo_votes))) - logit(_clip(self.bloc_rate))


def adjust(p_party: float, prop: Propensity, beta: float, pseudo_votes: float) -> float:
    """Move p away from the party's lean in proportion to excess break propensity."""
    if p_party <= 0.0 or p_party >= 1.0 or p_party == 0.5 or beta == 0.0:
        return p_party
    sign = 1.0 if p_party < 0.5 else -1.0
    return sigmoid(logit(p_party) + sign * beta * prop.weight * prop.excess(pseudo_votes))


def propensities(alignment: Alignment, body: str) -> dict[str, Propensity]:
    if body not in alignment.bodies:
        raise PriorError(f"alignment has no body {body!r}")
    ab = alignment.bodies[body]
    out: dict[str, Propensity] = {}
    for m in ab.members:
        if m.breaks is None:
            continue
        rate = ab.bloc_break_rate.get(m.bloc)
        if rate is None:
            continue
        out[m.id] = Propensity(m.breaks, m.n_votes, rate, source=alignment.source)
    return out


def apply_defection_prior(
    prior: DefectionPrior,
    scenario: Scenario,
    comp: Composition,
    rules: RuleSet,
    alignment: Alignment,
) -> Composition:
    """Return a copy of ``comp`` with adjusted p_pro for members who only had a party prior."""
    if all(m.breaks is None for b in alignment.bodies.values() for m in b.members):
        raise PriorError("alignment file has no break counts; regenerate it with breaks")
    new = comp.model_copy(deep=True)
    matched = 0
    for chamber, body in new.bodies.items():
        if chamber not in alignment.bodies:
            continue
        props = propensities(alignment, chamber)
        stage_ids = [s.id for s in rules.stages if s.chamber == chamber]
        if STAR not in prior.stages:
            stage_ids = [s for s in stage_ids if s in prior.stages]
        members: list[Member] = []
        for m in body.roster:
            prop = props.get(m.id)
            if prop is None or m.p_pro or m.id in scenario.overrides:
                members.append(m)
                continue
            party = scenario.party_priors.get(m.bloc, {})
            table: dict[str, float] = {}
            for sid in stage_ids:
                base = party.get(sid, party.get(STAR))
                if base is not None:
                    table[sid] = adjust(base, prop, prior.beta, prior.pseudo_votes)
            if table:
                matched += 1
                members.append(m.model_copy(update={"p_pro": table, "p_source": "defection_rate"}))
            else:
                members.append(m)
        body.members = members
    if matched == 0:
        raise PriorError("defection prior matched no members; check that ids are bioguide ids")
    return new


def fit_beta(excess: list[float], crossed: list[int], iters: int = 50) -> tuple[float, float]:
    """Logistic fit P(cross) = sigmoid(c + beta*excess). Returns (beta, standard error)."""
    x = np.asarray(excess, dtype=float)
    y = np.asarray(crossed, dtype=float)
    if x.size == 0 or y.sum() == 0 or y.sum() == y.size:
        raise PriorError("fit_beta needs both crossers and non-crossers")
    X = np.column_stack([np.ones_like(x), x])
    w = np.zeros(2)
    for _ in range(iters):
        mu = 1.0 / (1.0 + np.exp(-(X @ w)))
        g = X.T @ (y - mu)
        H = X.T @ (X * (mu * (1 - mu))[:, None])
        step = np.linalg.solve(H + 1e-9 * np.eye(2), g)
        w += step
        if float(np.abs(step).max()) < 1e-10:
            break
    mu = 1.0 / (1.0 + np.exp(-(X @ w)))
    H = X.T @ (X * (mu * (1 - mu))[:, None])
    cov = np.linalg.inv(H)
    return float(w[1]), float(math.sqrt(cov[1, 1]))
