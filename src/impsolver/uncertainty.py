# SPDX-FileCopyrightText: 2026 Justin Stanley
# SPDX-License-Identifier: MIT
"""Input uncertainty on priors: point values, deterministic bounds and outer-loop samples.

A party prior or override value is a number, a range ``{low, high}`` or a Beta distribution
``{beta: [a, b]}``. Everything except the Monte Carlo outer loop works with one number per prior:

- the **point** value is the distribution's mean: the midpoint of a range, a / (a + b) for a Beta;
- the **bounds** used by ``evaluate`` for pro_min / pro_max are low / high for a range and the 5th
  and 95th percentiles for a Beta.

``simulate`` with ``uncertainty_draws`` N > 0 samples every uncertain prior once per outer draw
(uniform on a range, Beta for a Beta) and substitutes the sample for every member and stage that
resolves to that prior, so members of one bloc share one value in a draw.
"""

from __future__ import annotations

import math
from typing import Literal

import numpy as np

from .model import PriorBeta, PriorRange, PriorValue, Scenario

Bound = Literal["point", "low", "high"]
BETA_BOUND_Q = (0.05, 0.95)


def is_uncertain(v: PriorValue) -> bool:
    return isinstance(v, PriorRange | PriorBeta)


def point(v: PriorValue) -> float:
    """The mean of the prior: the value itself, a range's midpoint, or a / (a + b)."""
    if isinstance(v, PriorRange):
        return (v.low + v.high) / 2.0
    if isinstance(v, PriorBeta):
        a, b = v.beta
        return a / (a + b)
    return float(v)


def bounds(v: PriorValue) -> tuple[float, float]:
    """Low and high values for deterministic bounds: a range's ends, or a Beta's 5th/95th pct."""
    if isinstance(v, PriorRange):
        return v.low, v.high
    if isinstance(v, PriorBeta):
        a, b = v.beta
        return beta_ppf(BETA_BOUND_Q[0], a, b), beta_ppf(BETA_BOUND_Q[1], a, b)
    return float(v), float(v)


def value(v: PriorValue, bound: Bound = "point") -> float:
    if bound == "point":
        return point(v)
    lo, hi = bounds(v)
    return lo if bound == "low" else hi


def sample(v: PriorValue, rng: np.random.Generator) -> float:
    """One draw: uniform on a range, Beta(a, b) for a Beta. Numbers are returned unchanged."""
    if isinstance(v, PriorRange):
        return float(rng.uniform(v.low, v.high))
    if isinstance(v, PriorBeta):
        a, b = v.beta
        return float(rng.beta(a, b))
    return float(v)


def has_uncertainty(scenario: Scenario) -> bool:
    tables = [*scenario.party_priors.values(), *scenario.overrides.values()]
    return any(is_uncertain(v) for t in tables for v in t.values())


def sample_scenario(scenario: Scenario, rng: np.random.Generator) -> Scenario:
    """A copy of ``scenario`` with every uncertain prior replaced by one sampled number.

    Priors are sampled in file order (party_priors, then overrides), so a seed fixes the draws.
    The copy has ``uncertainty_draws`` 0.
    """

    def draw(tables: dict[str, dict[str, PriorValue]]) -> dict[str, dict[str, PriorValue]]:
        return {
            name: {k: sample(v, rng) if is_uncertain(v) else v for k, v in table.items()}
            for name, table in tables.items()
        }

    return scenario.model_copy(
        update={
            "party_priors": draw(scenario.party_priors),
            "overrides": draw(scenario.overrides),
            "uncertainty_draws": 0,
        }
    )


def bound_scenario(scenario: Scenario, bound: Bound) -> Scenario:
    """A copy of ``scenario`` with every uncertain prior replaced by its ``bound`` value."""

    def fix(tables: dict[str, dict[str, PriorValue]]) -> dict[str, dict[str, PriorValue]]:
        return {
            name: {k: value(v, bound) if is_uncertain(v) else v for k, v in table.items()}
            for name, table in tables.items()
        }

    return scenario.model_copy(
        update={
            "party_priors": fix(scenario.party_priors),
            "overrides": fix(scenario.overrides),
            "uncertainty_draws": 0,
        }
    )


# ------------------------------------------------------------------ Beta quantiles


def _betacf(a: float, b: float, x: float) -> float:
    """Continued fraction for the incomplete beta function (modified Lentz)."""
    tiny = 1e-300
    qab, qap, qam = a + b, a + 1.0, a - 1.0
    c, d = 1.0, 1.0 - qab * x / qap
    d = 1.0 / (d if abs(d) > tiny else tiny)
    h = d
    for m in range(1, 500):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 + aa * d
        d = 1.0 / (d if abs(d) > tiny else tiny)
        c = 1.0 + aa / c
        c = c if abs(c) > tiny else tiny
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 + aa * d
        d = 1.0 / (d if abs(d) > tiny else tiny)
        c = 1.0 + aa / c
        c = c if abs(c) > tiny else tiny
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < 1e-14:
            break
    return h


def beta_cdf(x: float, a: float, b: float) -> float:
    """Regularized incomplete beta function I_x(a, b)."""
    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0
    ln = math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b) + a * math.log(x)
    front = math.exp(ln + b * math.log1p(-x))
    if x < (a + 1.0) / (a + b + 2.0):
        return front * _betacf(a, b, x) / a
    return 1.0 - front * _betacf(b, a, 1.0 - x) / b


def beta_ppf(q: float, a: float, b: float) -> float:
    """Quantile of Beta(a, b) by bisection on :func:`beta_cdf` (accurate to about 1e-12)."""
    lo, hi = 0.0, 1.0
    for _ in range(100):
        mid = (lo + hi) / 2.0
        if beta_cdf(mid, a, b) < q:
            lo = mid
        else:
            hi = mid
        if hi - lo < 1e-13:
            break
    return (lo + hi) / 2.0
