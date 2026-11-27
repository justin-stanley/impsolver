# SPDX-FileCopyrightText: 2026 Justin Stanley
# SPDX-License-Identifier: MIT
"""Threshold arithmetic. Everything is integer and works on scalars or numpy arrays.

The motion's yea side is PRO when ``pass_direction == "pass"`` and CON when it is ``"fail"``.
For the PRO side to win a fail-direction gate, the motion must not carry.
"""

from __future__ import annotations

import numpy as np
import numpy.typing as npt

from .model import Direction, Stage, ThresholdRule, TieBreak


def ceil_div(a: int, b: int) -> int:
    return -(-a // b)


def motion_carries[IntLike: (int, npt.NDArray[np.int64])](
    rule: ThresholdRule,
    yea: IntLike,
    nay: IntLike,
    present: IntLike,
    base: int,
) -> IntLike:
    """True where the motion carries. ``base`` is the membership base for fraction_of_membership."""
    if rule.kind == "majority_of_votes_cast":
        out = yea > nay
    elif rule.kind == "fraction_of_present":
        counted = present if rule.present_in_denominator else 0 * present
        out = rule.q * yea >= rule.p * (yea + nay + counted)
    else:
        out = rule.q * yea >= rule.p * base
    return out  # type: ignore[return-value]


def pro_wins[IntLike: (int, npt.NDArray[np.int64])](
    rule: ThresholdRule,
    direction: Direction,
    pro: IntLike,
    con: IntLike,
    present: IntLike,
    base: int,
    tie: TieBreak = "none",
) -> IntLike:
    """True where PRO wins. ``tie`` overrides how an exact tie on a majority vote goes."""
    if direction == "pass":
        out = motion_carries(rule, pro, con, present, base)
    else:
        carried = motion_carries(rule, con, pro, present, base)
        out = ~carried if isinstance(carried, np.ndarray) else (not carried)
    if tie == "none" or rule.kind != "majority_of_votes_cast":
        return out
    winner = tie == "pro"
    if isinstance(out, np.ndarray):
        return np.where(pro == con, winner, out)
    return winner if pro == con else out


def tie_mode(stage: Stage, senate_tie_break: TieBreak) -> TieBreak:
    """The scenario's tie-break applies only to majority votes in the Senate."""
    if stage.chamber == "senate" and stage.rule.kind == "majority_of_votes_cast":
        return senate_tie_break
    return "none"


def membership_base(rule: ThresholdRule, seats: int, vacancies: int) -> int:
    return seats - vacancies if rule.vacancies_reduce_base else seats


def required_pro(
    rule: ThresholdRule,
    direction: Direction,
    voting: int,
    present: int = 0,
    base: int = 0,
    tie: TieBreak = "none",
) -> int:
    """Minimal PRO count among ``voting`` yea/nay voters for PRO to win.

    ``present`` members answer present and do not vote yea or nay. The result may exceed
    ``voting`` when the gate cannot be won with this attendance.
    """
    if direction == "pass" and tie == "none":
        if rule.kind == "majority_of_votes_cast":
            return voting // 2 + 1
        if rule.kind == "fraction_of_present":
            counted = present if rule.present_in_denominator else 0
            return ceil_div(rule.p * (voting + counted), rule.q)
        return ceil_div(rule.p * base, rule.q)
    # Fail direction or a tie rule: search, which is cheap.
    for pro in range(voting + 1):
        if pro_wins(rule, direction, pro, voting - pro, present, base, tie):
            return pro
    return voting + 1


def has_quorum[IntLike: (int, npt.NDArray[np.int64])](in_chamber: IntLike, sworn: int) -> IntLike:
    """majority_of_sworn: a majority of sworn members must be present (yea, nay or present)."""
    return in_chamber >= sworn // 2 + 1  # type: ignore[return-value]
