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


class DeterministicArticle(BaseModel):
    article: str
    path: str
    verdict: Verdict
    ends_at: str | None
    binding_gate: str
    controlling_coalition: list[BlocCount]
    gates: list[DeterministicGate]


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


class SimGate(BaseModel):
    stage: str
    p_reached: float
    p_pass_given_reached: float
    pro_count: CountSummary


class SimArticle(BaseModel):
    article: str
    path: str
    p_complete: float
    mc_se: float
    gates: list[SimGate]


class Simulation(BaseModel):
    target: str
    draws: int
    rho: float
    seed: int
    aligned: bool
    articles: list[SimArticle]


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
