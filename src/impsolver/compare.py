# SPDX-FileCopyrightText: 2026 Justin Stanley
# SPDX-License-Identifier: MIT
"""Side-by-side comparison of two portfolios or two scenarios (``impsolver compare-plans``).

Both sides are computed exactly as ``portfolio`` and ``simulate`` would compute them on their
own. The comparison only lines them up; it never adds targets.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel

from .contract import CaseGates, annotate, case_gates
from .deterministic import evaluate
from .loader import read_data
from .portfolio import PortfolioResult, Slot, make_ctx, schedule_order
from .portfolio import load as load_portfolio_inputs
from .portfolio import solve as solve_portfolio
from .prepare import Prepared, prepare
from .results import Evaluation, Simulation
from .simulate import simulate
from .tornado import Tornado, p_removal, tornado

Kind = Literal["portfolio", "scenario"]


class CompareError(ValueError):
    pass


class PortfolioSide(BaseModel):
    file: str
    result: PortfolioResult
    recommended_order: list[str]
    expected_removals: float
    # The recommended order's schedule when no removal changes a later case.
    slots: list[Slot]


class ScenarioSide(BaseModel):
    file: str
    target: str
    office: str
    composition: str
    p_removal: float
    simulation: Simulation
    evaluation: Evaluation
    tornado: Tornado
    # The counted tally of every gate, by article (see ``contract.case_gates``).
    gates: dict[str, CaseGates] = {}


class Comparison(BaseModel):
    kind: Kind
    a: PortfolioSide | ScenarioSide
    b: PortfolioSide | ScenarioSide


def kind_of(path: str | Path) -> Kind:
    """``portfolio`` for a file with candidates, ``scenario`` for one with a target."""
    data = read_data(path)
    if isinstance(data, dict) and "candidates" in data:
        return "portfolio"
    if isinstance(data, dict) and "target" in data:
        return "scenario"
    raise CompareError(f"{path}: neither a portfolio (candidates) nor a scenario (target)")


def portfolio_side(path: str | Path, exhaustive: bool = False) -> tuple[PortfolioSide, list[str]]:
    loaded = load_portfolio_inputs(path)
    warnings = [
        f"{path}: candidate {cid}: {w}" for cid, p in loaded.preps.items() for w in p.warnings
    ]
    res = solve_portfolio(loaded, exhaustive=exhaustive)
    order = res.succession_order or (res.plans[0].order if res.plans else [])
    value = (
        res.succession_value
        if res.succession_value is not None
        else (res.plans[0].expected_removals if res.plans else 0.0)
    )
    ctx, _ = make_ctx(loaded.pf, loaded.p0, p0e=loaded.p0_epochs)
    slots = [s.model_copy() for s in schedule_order(ctx, tuple(order)).slots]
    annotate(ctx, slots)
    side = PortfolioSide(
        file=str(path), result=res, recommended_order=order, expected_removals=value, slots=slots
    )
    return side, warnings


def scenario_side(prep: Prepared, path: str | Path, draws: int) -> ScenarioSide:
    scen = prep.scenario
    article = scen.articles[0] if len(scen.articles) == 1 else None
    base = p_removal(prep, article, draws)
    return ScenarioSide(
        file=str(path),
        target=scen.target.name,
        office=scen.target.office,
        composition=prep.comp.name,
        p_removal=base,
        # Same basis as p_removal: point priors, no outer uncertainty loop.
        simulation=simulate(
            prep.with_scenario(prep.scenario.model_copy(update={"uncertainty_draws": 0})),
            draws=draws,
        ),
        evaluation=evaluate(prep),
        tornado=tornado(prep, article, draws, cid="", base=base),
        gates={a: case_gates(prep, a) for a in scen.articles},
    )


def compare(
    a: str | Path, b: str | Path, draws: int = 20_000, exhaustive: bool = False
) -> tuple[Comparison, list[str]]:
    """Compute both sides. Returns the comparison and any input warnings."""
    ka, kb = kind_of(a), kind_of(b)
    if ka != kb:
        raise CompareError(f"cannot compare a {ka} ({a}) with a {kb} ({b}); give two of a kind")
    if ka == "portfolio":
        sa, wa = portfolio_side(a, exhaustive)
        sb, wb = portfolio_side(b, exhaustive)
        return Comparison(kind=ka, a=sa, b=sb), wa + wb
    pa, pb = prepare(a), prepare(b)
    warnings = [f"{a}: {w}" for w in pa.warnings] + [f"{b}: {w}" for w in pb.warnings]
    return (
        Comparison(kind=ka, a=scenario_side(pa, a, draws), b=scenario_side(pb, b, draws)),
        warnings,
    )
