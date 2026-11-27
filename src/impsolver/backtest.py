# SPDX-FileCopyrightText: 2026 Justin Stanley
# SPDX-License-Identifier: MIT
"""Replay historical roll calls through the rule set and check the recorded outcomes."""

from __future__ import annotations

from pathlib import Path

from .gates import evaluate_gate
from .loader import BUILTIN_FIXTURES, builtin_rules, load_fixture, load_rules
from .model import Fixture, RuleSet
from .paths import build_path
from .results import BacktestCheck, BacktestReport

DEFAULT_RULES = builtin_rules("us-federal")
DEFAULT_FIXTURES = BUILTIN_FIXTURES


def default_fixtures() -> list[Path]:
    return sorted(DEFAULT_FIXTURES.glob("*.yaml"))


def check_fixture(fx: Fixture, rules: RuleSet) -> tuple[list[BacktestCheck], list[str], bool]:
    checks: list[BacktestCheck] = []
    last: dict[tuple[str, str], str] = {}
    for v in fx.votes:
        st = rules.stage(v.stage)
        body = fx.bodies[st.chamber]
        pro, con = (v.yea, v.nay) if st.pass_direction == "pass" else (v.nay, v.yea)
        g = evaluate_gate(st, pro, con, v.present, v.not_voting, body.seats, body.vacancies)
        ok = g.outcome == v.expected and (v.expected_short is None or v.expected_short == g.short)
        tally = f"{v.yea}-{v.nay}" + (f"-{v.present}" if v.present else "")
        checks.append(
            BacktestCheck(
                case=fx.case,
                stage=v.stage,
                article=v.article,
                tally=tally,
                expected=v.expected,
                got=g.outcome,
                expected_short=v.expected_short,
                short=g.short,
                ok=ok,
            )
        )
        last[(v.article, v.stage)] = g.outcome  # a later vote supersedes an earlier one
    path = build_path(rules, fx.path)
    required = [st.id for st in path.stages]
    notes: list[str] = []
    ends: dict[str, str | None] = {}
    for article in dict.fromkeys(v.article for v in fx.votes):
        if not any((article, sid) in last for sid in required):
            continue  # only optional-stage votes (S3) under this label: not an article outcome
        ends_at: str | None = None
        for sid in required:
            outcome = last.get((article, sid))
            if outcome is not None and outcome != "PASS":
                ends_at = sid
                break
        if ends_at is None and last.get((article, required[-1])) != "PASS":
            ends_at = required[-1]  # never reached the terminal vote, so it cannot have completed
        ends[article] = ends_at
    # Conviction on any one article removes the official, so completion is a case-level outcome.
    # A case that did not complete ended at the furthest stage any article reached.
    complete = any(e is None for e in ends.values())
    case_ends: str | None = None
    if not complete and ends:
        case_ends = max(ends.values(), key=lambda s: required.index(s or required[-1]))
    # A fixture with no vote on a required stage has no case outcome to check.
    case_ok = bool(ends) and (
        complete == fx.expected_complete
        and (fx.expected_ends_at is None or case_ends == fx.expected_ends_at)
    )
    all_ok = all(c.ok for c in checks) and case_ok
    for article, ends_at in ends.items():
        notes.append(
            f"{fx.case} article {article}: path {fx.path} "
            + ("completed" if ends_at is None else f"ended at {ends_at}")
        )
    if not ends:
        notes.append(f"{fx.case}: no vote on a required stage of path {fx.path}")
        return checks, notes, False
    notes.append(
        f"{fx.case}: "
        + ("completed" if complete else f"ended at {case_ends}")
        + (
            ""
            if case_ok
            else f" (expected complete={fx.expected_complete}, ends_at={fx.expected_ends_at})"
        )
    )
    return checks, notes, all_ok


def run_backtest(
    fixtures: list[Path] | None = None, rules_path: Path | None = None
) -> BacktestReport:
    rules = load_rules(rules_path or DEFAULT_RULES)
    checks: list[BacktestCheck] = []
    notes: list[str] = []
    ok = True
    for f in fixtures or default_fixtures():
        c, n, o = check_fixture(load_fixture(f), rules)
        checks += c
        notes += n
        ok &= o
    return BacktestReport(checks=checks, path_checks=notes, ok=ok)
