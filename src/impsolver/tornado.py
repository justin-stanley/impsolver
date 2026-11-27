# SPDX-FileCopyrightText: 2026 Justin Stanley
# SPDX-License-Identifier: MIT
"""One-notch sensitivity of a case's P(removal): the numbers behind the tornado chart.

Each input is moved one notch down and one notch up while everything else stays as supplied:

- each bloc's party prior by ``PRIOR_NOTCH`` on the probability scale, at every stage key the
  bloc lists, clipped to [0, 1];
- the bloc correlation ``rho`` by ``RHO_NOTCH``, clipped to [0, 1];
- in a portfolio, ``fatigue_delta`` by ``FATIGUE_NOTCH``, holding the recommended order fixed.

Every run reuses the scenario's seed and the same number of draws as the base value, so the
member and swing draws are common random numbers and a swing reflects the input, not Monte Carlo
noise. Members with an override or their own ``p_pro`` do not move with their bloc's notch.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

from .members import logit, sigmoid
from .model import Scenario
from .prepare import Prepared, prepare_objects
from .simulate import p_any_complete, p_complete

PRIOR_NOTCH = 0.05
RHO_NOTCH = 0.2
FATIGUE_NOTCH = 0.2
TORNADO_NOTE = (
    "Each bar moves one input one notch down (upper bar) and up (lower bar) and holds the rest "
    "as supplied. Bloc priors move by 0.05 at every stage they list, rho by 0.2 (both clipped to "
    "[0, 1]) and the portfolio fatigue delta by 0.2 with the order held fixed. Runs share the "
    "scenario's seed and draws, so swings are not Monte Carlo noise. Members with overrides or "
    "their own probabilities do not move with their bloc. It restates the inputs; it is not a "
    "forecast."
)


class TornadoBar(BaseModel):
    input: str
    kind: Literal["bloc_prior", "rho", "fatigue"]
    low_setting: str
    high_setting: str
    p_low: float
    p_high: float
    swing: float
    note: str | None = None


class Tornado(BaseModel):
    id: str
    label: str
    base: float
    basis: str
    draws: int
    bars: list[TornadoBar]
    notes: list[str] = []


def fatigued(p0: float, delta: float, m: int) -> float:
    """P after ``m`` earlier trials at fatigue ``delta`` (the portfolio's rule)."""
    if p0 <= 0.0 or p0 >= 1.0 or delta == 0.0 or m == 0:
        return p0
    return sigmoid(logit(p0) - delta * m)


def p_removal(prep: Prepared, article: str | None, draws: int) -> float:
    """P(removal) at the scenario's seed: ``article`` completes, or (None) any article does."""
    if article is not None:
        return p_complete(prep, article, draws=draws)
    return p_any_complete(prep, draws=draws)


def with_scenario(prep: Prepared, scenario: Scenario) -> Prepared:
    """``prep`` with another scenario, re-applying any defection prior to the raw roster."""
    comp = prep.raw_comp if prep.raw_comp is not None else prep.comp
    return prepare_objects(prep.rules, comp, scenario, prep.alignment, prep.source)


def _clip(x: float) -> float:
    return min(1.0, max(0.0, x))


def _fmt(x: float) -> str:
    return f"{x:.2f}".rstrip("0").rstrip(".") if x not in (0.0, 1.0) else f"{x:.0f}"


def _bloc_prior(scen: Scenario, bloc: str, sign: int) -> tuple[Scenario, str, bool]:
    table = scen.party_priors[bloc]
    moved = {k: _clip(v + sign * PRIOR_NOTCH) for k, v in table.items()}
    clipped = any(abs(moved[k] - (table[k] + sign * PRIOR_NOTCH)) > 1e-12 for k in table)
    priors = {**scen.party_priors, bloc: moved}
    detail = ", ".join(f"{k} {_fmt(v)}" for k, v in moved.items())
    return scen.model_copy(update={"party_priors": priors}), detail, clipped


def _blocs(prep: Prepared) -> list[str]:
    present = {m.bloc for b in prep.comp.bodies.values() for m in b.roster}
    return sorted(b for b in prep.scenario.party_priors if b in present)


def tornado(
    prep: Prepared,
    article: str | None,
    draws: int,
    cid: str = "",
    label: str | None = None,
    fatigue: tuple[float, int] | None = None,
    base: float | None = None,
) -> Tornado:
    """One-notch swings of P(removal) for one case.

    Args:
        prep: The prepared scenario.
        article: Article to measure, or ``None`` for removal on any article.
        draws: Monte Carlo draws per run (use the same number as the base value).
        cid: Identifier shown with the chart.
        label: Display name; defaults to the target's name.
        fatigue: ``(fatigue_delta, attempt)`` when the case sits in a portfolio order. Every bar
            is then the P in that position, and a fatigue bar is added.
        base: The case's P(removal) alone, if already computed with the same seed and draws.
    """
    scen = prep.scenario
    delta, attempt = fatigue if fatigue is not None else (0.0, 0)

    def value(p: float) -> float:
        return fatigued(p, delta, attempt)

    p0 = p_removal(prep, article, draws) if base is None else base
    bars: list[TornadoBar] = []
    for bloc in _blocs(prep):
        lo_s, lo_d, lo_c = _bloc_prior(scen, bloc, -1)
        hi_s, hi_d, hi_c = _bloc_prior(scen, bloc, +1)
        lo = value(p_removal(with_scenario(prep, lo_s), article, draws))
        hi = value(p_removal(with_scenario(prep, hi_s), article, draws))
        bars.append(
            TornadoBar(
                input=f"{bloc} prior",
                kind="bloc_prior",
                low_setting=f"-{PRIOR_NOTCH:g}" + (" (clipped)" if lo_c else ""),
                high_setting=f"+{PRIOR_NOTCH:g}" + (" (clipped)" if hi_c else ""),
                p_low=lo,
                p_high=hi,
                swing=abs(hi - lo),
                note=f"down: {lo_d}; up: {hi_d}",
            )
        )
    r_lo, r_hi = _clip(scen.rho - RHO_NOTCH), _clip(scen.rho + RHO_NOTCH)
    lo = value(
        p_removal(with_scenario(prep, scen.model_copy(update={"rho": r_lo})), article, draws)
    )
    hi = value(
        p_removal(with_scenario(prep, scen.model_copy(update={"rho": r_hi})), article, draws)
    )
    bars.append(
        TornadoBar(
            input="rho",
            kind="rho",
            low_setting=f"rho {_fmt(r_lo)}",
            high_setting=f"rho {_fmt(r_hi)}",
            p_low=lo,
            p_high=hi,
            swing=abs(hi - lo),
            note=f"supplied rho {_fmt(scen.rho)}",
        )
    )
    notes: list[str] = []
    if fatigue is not None:
        f_lo, f_hi = delta - FATIGUE_NOTCH, delta + FATIGUE_NOTCH
        lo, hi = fatigued(p0, f_lo, attempt), fatigued(p0, f_hi, attempt)
        bars.append(
            TornadoBar(
                input="fatigue delta",
                kind="fatigue",
                low_setting=f"{f_lo:+.2f}",
                high_setting=f"{f_hi:+.2f}",
                p_low=lo,
                p_high=hi,
                swing=abs(hi - lo),
                note="no effect: tried first in the order"
                if attempt == 0
                else f"trial {attempt + 1} in the recommended order; order held fixed",
            )
        )
        basis = f"P in the recommended order (trial {attempt + 1}, fatigue {delta:g})"
    else:
        basis = "P(removal) alone"
    if article is None and len(scen.articles) > 1:
        notes.append("removal on any article")
    bars.sort(key=lambda b: (-b.swing, b.input))
    return Tornado(
        id=cid,
        label=label or scen.target.name,
        base=value(p0),
        basis=basis,
        draws=draws,
        bars=bars,
        notes=notes,
    )
