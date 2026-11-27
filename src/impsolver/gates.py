"""Evaluate a single gate from an explicit tally."""

from __future__ import annotations

from .model import Body, Stage
from .results import GateTally
from .thresholds import has_quorum, membership_base, pro_wins, required_pro


def evaluate_gate(
    stage: Stage,
    pro: int,
    con: int,
    present: int,
    absent: int,
    seats: int,
    vacancies: int = 0,
) -> GateTally:
    sworn = seats - vacancies
    base = membership_base(stage.rule, seats, vacancies)
    voting = pro + con
    need = required_pro(stage.rule, stage.pass_direction, voting, present, base)
    if not has_quorum(pro + con + present, sworn):
        outcome = "NO_QUORUM"
    elif pro_wins(stage.rule, stage.pass_direction, pro, con, present, base):
        outcome = "PASS"
    else:
        outcome = "FAIL"
    return GateTally(
        stage=stage.id,
        chamber=stage.chamber,
        label=stage.label,
        direction=stage.pass_direction,
        pro=pro,
        con=con,
        present=present,
        absent=absent,
        required=need,
        outcome=outcome,  # type: ignore[arg-type]
        short=max(0, need - pro),
    )


def evaluate_gate_body(stage: Stage, body: Body, pro: int, con: int, present: int = 0) -> GateTally:
    absent = body.sworn - pro - con - present
    return evaluate_gate(stage, pro, con, present, absent, body.seats, body.vacancies)
