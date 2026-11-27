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
    notes: list[str] = []
    all_ok = all(c.ok for c in checks)
    for article in dict.fromkeys(v.article for v in fx.votes):
        ends_at: str | None = None
        for st in path.stages:
            outcome = last.get((article, st.id))
            if outcome is not None and outcome != "PASS":
                ends_at = st.id
                break
        complete = ends_at is None
        ok = complete == fx.expected_complete and (
            fx.expected_ends_at is None or ends_at == fx.expected_ends_at
        )
        all_ok &= ok
        notes.append(
            f"{fx.case} article {article}: path {fx.path} "
            + ("completed" if complete else f"ended at {ends_at}")
            + ("" if ok else f" (expected ends_at={fx.expected_ends_at})")
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
