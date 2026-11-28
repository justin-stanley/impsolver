# SPDX-FileCopyrightText: 2026 Justin Stanley
# SPDX-License-Identifier: MIT
"""Output models. These are plain (non-strict) pydantic models so they serialize cleanly."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

Outcome = Literal["PASS", "FAIL", "NO_QUORUM"]
Verdict = Literal["PASS", "FAIL", "CONTESTED", "NO_QUORUM"]
ViabilityLabel = Literal["viable", "reachable", "out of reach"]


class GateTally(BaseModel):
    stage: str
    chamber: str
    label: str
    direction: str
    pro: int
    con: int
    present: int
    absent: int
    required: int
    outcome: Outcome
    short: int


class BlocCount(BaseModel):
    bloc: str
    count: int


class DeterministicGate(BaseModel):
    stage: str
    chamber: str
    label: str
    pro_min: int
    pro_max: int
    uncertain: int
    absent: int
    required: int
    verdict: Verdict
    short_at_min: int
    presiding_officer: str | None = None
    uncertain_by_bloc: list[BlocCount]


class PivotMember(BaseModel):
    """A non-PRO member at the binding gate, listed by the supplied probability of PRO."""

    id: str
    name: str
    bloc: str
    p: float
    source: str


class DeterministicArticle(BaseModel):
    article: str
    path: str
    verdict: Verdict
    ends_at: str | None
    binding_gate: str
    controlling_coalition: list[BlocCount]
    gates: list[DeterministicGate]
    pivots: list[PivotMember] = []


class Evaluation(BaseModel):
    target: str
    office: str
    composition: str
    cutoffs: tuple[float, float]
    articles: list[DeterministicArticle]


class FlipMember(BaseModel):
    chamber: str
    id: str
    name: str
    bloc: str
    p: float
    action: Literal["flip", "absent"]
    gates: list[str]


class FlipResult(BaseModel):
    article: str
    gates: list[str]
    method: Literal["greedy", "ilp"]
    status: Literal["OK", "INFEASIBLE", "ALREADY_PASSING"]
    n_flips: int
    n_absences: int
    members: list[FlipMember]
    note: str | None = None


class CountSummary(BaseModel):
    mean: float
    p5: float
    p50: float
    p95: float


class CountHist(BaseModel):
    """How many draws gave each count: ``counts[i]`` draws had ``start + i``."""

    start: int
    counts: list[int]


class SimGate(BaseModel):
    stage: str
    p_reached: float
    p_pass_given_reached: float
    pro_count: CountSummary  # over every draw, as if the vote were held each time
    # Detail for the planning page (``simulate_article(..., detail=True)``); None otherwise.
    n_reached: int | None = None
    pass_se: float | None = None  # standard error of p_pass_given_reached
    pro_count_reached: CountSummary | None = None  # over the draws that reach the gate
    pro_hist: CountHist | None = None  # PRO count over the draws that reach the gate
    present_count: CountSummary | None = None  # members in the chamber; random attendance only
    # Per roster member: the share of draws in which the gate's result would flip if that one
    # member's vote flipped (0 for a member who is absent throughout).
    decisive_share: list[float] | None = None


class SimArticle(BaseModel):
    article: str
    path: str
    p_complete: float
    mc_se: float
    gates: list[SimGate]
    # 5th and 95th percentiles of P(complete) across outer draws over uncertain priors.
    p_complete_interval: tuple[float, float] | None = None


class Simulation(BaseModel):
    target: str
    draws: int
    rho: float
    seed: int
    aligned: bool
    articles: list[SimArticle]
    uncertainty_draws: int = 0
    # With the outer loop and several articles: P(at least one article completes) and its 5-95%
    # interval across outer draws.
    p_any_complete: float | None = None
    p_any_complete_interval: tuple[float, float] | None = None


class BacktestCheck(BaseModel):
    case: str
    stage: str
    article: str
    tally: str
    expected: str
    got: str
    expected_short: int | None
    short: int
    ok: bool


class BacktestReport(BaseModel):
    checks: list[BacktestCheck]
    path_checks: list[str]
    ok: bool


class ViabilityRow(BaseModel):
    scenario: str
    target: str
    p_complete: float
    flips: int | None
    support_gap: float | None
    label: ViabilityLabel
