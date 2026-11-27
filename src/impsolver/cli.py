# SPDX-FileCopyrightText: 2026 Justin Stanley
# SPDX-License-Identifier: MIT
"""Command-line interface. All rendering lives here."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ValidationError

from . import alignment as alignment_mod
from . import roster as roster_mod
from .backtest import run_backtest
from .calibrate import calibrate
from .deterministic import evaluate
from .flips import ABSENCE_NOTE, FlipError, find_flips
from .loader import (
    BUILTIN_FIXTURES,
    LoadError,
    load_alignment,
    load_composition,
    load_crossovers,
    load_rules,
    load_scenario,
    resolve_rules,
)
from .members import ResolutionError
from .model import (
    Alignment,
    Composition,
    CrossoverFixture,
    Fixture,
    Portfolio,
    RuleSet,
    Scenario,
)
from .paths import PathError
from .portfolio import PortfolioError
from .portfolio import load as load_portfolio_inputs
from .portfolio import solve as solve_portfolio
from .prepare import Prepared
from .prepare import prepare as _prepare_raw
from .priors import PriorError
from .report import render as render_report
from .results import Evaluation, FlipResult, Simulation
from .simulate import simulate
from .viability import Case, assess

NEUTRALITY = "impsolver evaluates only the targets you supply; it does not nominate targets."


class CliError(Exception):
    pass


def _emit(args: argparse.Namespace, obj: Any, text: Callable[[], str]) -> None:
    if args.format == "json":
        data = obj.model_dump(mode="json") if isinstance(obj, BaseModel) else obj
        print(json.dumps(data, indent=2, default=str))
    else:
        print(text())


# ------------------------------------------------------------------ renderers


def render_evaluation(e: Evaluation) -> str:
    out = [f"{e.target} ({e.office}) on {e.composition}; cutoffs {e.cutoffs[0]}/{e.cutoffs[1]}"]
    for a in e.articles:
        out.append(
            f"\nArticle {a.article}, path {a.path}: {a.verdict}"
            + (f", ends at {a.ends_at}" if a.ends_at else "")
            + f"; binding gate {a.binding_gate}"
        )
        out.append(f"  {'gate':5} {'label':34} {'pro min':>7} {'pro max':>7} {'need':>5} verdict")
        for g in a.gates:
            out.append(
                f"  {g.stage:5} {g.label[:34]:34} {g.pro_min:>7} {g.pro_max:>7} "
                f"{g.required:>5} {g.verdict}"
                + (f" (presiding: {g.presiding_officer})" if g.presiding_officer else "")
            )
        if a.controlling_coalition:
            out.append(
                "  controlling coalition at binding gate (non-PRO members): "
                + ", ".join(f"{b.bloc} {b.count}" for b in a.controlling_coalition)
            )
    return "\n".join(out)


def render_flips(r: FlipResult) -> str:
    head = (
        f"Article {r.article}, gates {','.join(r.gates)} ({r.method}): {r.status}; "
        f"{r.n_flips} flips, {r.n_absences} absences"
    )
    lines = [head]
    for m in r.members:
        lines.append(
            f"  {m.action:6} {m.chamber:6} {m.id:10} {m.bloc:3} p={m.p:.3f} "
            f"{m.name} [{','.join(m.gates)}]"
        )
    if r.n_absences:
        lines.append(f"  note: {ABSENCE_NOTE}")
    return "\n".join(lines)


def render_simulation(s: Simulation) -> str:
    out = [f"{s.target}: {s.draws} draws, rho={s.rho}, seed={s.seed}, aligned={s.aligned}"]
    for a in s.articles:
        out.append(
            f"\nArticle {a.article}, path {a.path}: P(complete)={a.p_complete:.4f} "
            f"(MC s.e. {a.mc_se:.4f})"
        )
        for g in a.gates:
            c = g.pro_count
            out.append(
                f"  {g.stage:4} reached {g.p_reached:.4f}  pass|reached "
                f"{g.p_pass_given_reached:.4f}  PRO mean {c.mean:.1f} "
                f"[p5 {c.p5:.0f}, p50 {c.p50:.0f}, p95 {c.p95:.0f}]"
            )
    return "\n".join(out)


# ------------------------------------------------------------------- commands


def prepare(path: str, composition: str | None = None) -> Prepared:
    """Load a scenario and print its warnings (unknown ids or blocs) to stderr."""
    prep = _prepare_raw(path, composition)
    for w in prep.warnings:
        print(f"warning: {w}", file=sys.stderr)
    return prep


def cmd_validate(a: argparse.Namespace) -> int:
    report: dict[str, str] = {}
    rules = load_rules(resolve_rules(a.rules, Path.cwd() / "_"))
    report[a.rules] = f"rules ok: {len(rules.stages)} stages"
    if a.composition:
        c = load_composition(a.composition)
        report[a.composition] = "composition ok: " + ", ".join(
            f"{k} {len(b.roster)}+{b.vacancies} vacant" for k, b in c.bodies.items()
        )
    if a.scenario:
        load_scenario(a.scenario)
        prep = prepare(a.scenario, a.composition)
        evaluate(prep)  # resolves every probability
        if prep.warnings:
            raise CliError(f"{a.scenario}: {len(prep.warnings)} warning(s); see above")
        report[a.scenario] = "scenario ok"
    _emit(a, report, lambda: "\n".join(f"{k}: {v}" for k, v in report.items()))
    return 0


def cmd_evaluate(a: argparse.Namespace) -> int:
    e = evaluate(prepare(a.scenario), a.path)
    _emit(a, e, lambda: render_evaluation(e))
    return 0


def cmd_flips(a: argparse.Namespace) -> int:
    prep = prepare(a.scenario)
    seen = len(prep.warnings)
    r = find_flips(
        prep,
        article=a.article,
        path_name=a.path,
        gate=a.gate,
        method="greedy" if a.greedy else "ilp",
        constraints=a.constraint,
        exclude=a.exclude,
        allow_absence=a.allow_absence,
        absence_cost=a.absence_cost,
        per_gate_stance=a.per_gate_stance,
    )
    for w in prep.warnings[seen:]:
        print(f"warning: {w}", file=sys.stderr)
    _emit(a, r, lambda: render_flips(r))
    return 0


def cmd_simulate(a: argparse.Namespace) -> int:
    s = simulate(prepare(a.scenario), draws=a.draws, rho=a.rho, seed=a.seed, path_name=a.path)
    _emit(a, s, lambda: render_simulation(s))
    return 0


def cmd_compare(a: argparse.Namespace) -> int:
    rows = []
    for comp in a.composition:
        e = evaluate(prepare(a.scenario, comp))
        for art in e.articles:
            rows.append(
                {
                    "composition": e.composition,
                    "article": art.article,
                    "verdict": art.verdict,
                    "binding_gate": art.binding_gate,
                    "short_at_min": max(
                        g.short_at_min for g in art.gates if g.stage == art.binding_gate
                    ),
                }
            )

    def text() -> str:
        return "\n".join(
            f"{r['composition']:20} article {r['article']:4} {r['verdict']:10} "
            f"binding {r['binding_gate']} short {r['short_at_min']}"
            for r in rows
        )

    _emit(a, rows, text)
    return 0


def cmd_viability(a: argparse.Namespace) -> int:
    cases = [Case(str(p), prepare(p)) for p in a.scenarios]
    rows = assess(cases, target_p=a.target_p, max_gap=a.max_gap, draws=a.draws)

    def text() -> str:
        out = [NEUTRALITY]
        for r in rows:
            gap = "n/a" if r.support_gap is None else f"{r.support_gap:.2f}"
            out.append(
                f"{r.label:13} P={r.p_complete:.3f} flips={r.flips} gap={gap}  "
                f"{r.target} ({r.scenario})"
            )
        return "\n".join(out)

    _emit(a, [r.model_dump() for r in rows], text)
    return 0


def cmd_backtest(a: argparse.Namespace) -> int:
    rep = run_backtest([Path(f) for f in a.fixtures] or None)

    def text() -> str:
        out = [
            f"{'OK' if c.ok else 'MISMATCH':8} {c.case:14} {c.stage} art {c.article:4} "
            f"{c.tally:10} expected {c.expected:5} got {c.got:5} short {c.short}"
            for c in rep.checks
        ]
        out += rep.path_checks
        out.append("backtest: all match" if rep.ok else "backtest: MISMATCH")
        return "\n".join(out)

    _emit(a, rep, text)
    return 0 if rep.ok else 1


def cmd_portfolio(a: argparse.Namespace) -> int:
    loaded = load_portfolio_inputs(a.file)
    for cid, prep in loaded.preps.items():
        for w in prep.warnings:
            print(f"warning: candidate {cid}: {w}", file=sys.stderr)
    r = solve_portfolio(loaded, exhaustive=a.exhaustive)
    if a.html:
        Path(a.html).write_text(render_report(r, loaded.pf), encoding="utf-8")
        print(f"wrote {a.html}", file=sys.stderr)

    def text() -> str:
        out = [NEUTRALITY]
        for i, p in enumerate(r.plans, 1):
            out.append(
                f"\nPlan {i}: E[removals]={p.expected_removals:.3f}  order {' > '.join(p.order)}"
            )
            for s in p.slots:
                out.append(
                    f"  {s.id:16} House {s.house_start}..{s.house_end}  "
                    f"trial {s.trial_start}..{s.trial_end}  p0={s.p0:.3f} p={s.p:.3f}"
                )
        for d in r.dropped:
            out.append(f"dropped {d.id}: {d.reason} ({d.detail})")
        out.append("\nSensitivity" + (" (FRAGILE)" if r.fragile else ""))
        for row in r.sensitivity:
            out.append(
                f"  {row.label:20} best {row.best:.3f} base {row.base_rescheduled:.3f} "
                f"regret {row.regret:.3f}" + ("  FRAGILE" if row.fragile else "")
            )
        if r.succession_order is not None:
            out.append(
                f"\nWith succession: {' > '.join(r.succession_order)} E={r.succession_value:.3f}"
            )
        if r.removals_dist is not None:
            rd = r.removals_dist
            out.append(
                f"\nRemovals ({rd.method}): mean {rd.mean:.3f}, sd {rd.sd:.3f} "
                f"(independent sd {rd.independent_sd:.3f})"
            )
            out.append("  " + "  ".join(f"P({k})={q:.3f}" for k, q in enumerate(rd.probabilities)))
            out += [f"  note: {n}" for n in rd.notes]
        return "\n".join(out)

    _emit(a, r, text)
    return 0


def cmd_calibrate(a: argparse.Namespace) -> int:
    c = calibrate(
        load_crossovers(a.fixture), load_alignment(a.alignment), a.min_votes, a.permutations, a.seed
    )

    def text() -> str:
        out = [f"{c.case}: history congress {c.history_congress}, party {c.party}"]
        for b in c.bodies:
            beta = "n/a" if b.beta is None else f"{b.beta:.2f} ± {b.beta_se:.2f}"
            out.append(
                f"  {b.body}: {b.n_crossed}/{b.n_party} crossers matched; break rate "
                f"{b.crossed_break_rate:.3f} vs party {b.party_break_rate:.3f}; alignment "
                f"{b.crossed_mean_alignment:.2f} vs random {b.random_mean_alignment:.2f} "
                f"(p={b.permutation_p:.3f}); beta {beta}"
            )
            if b.unmatched:
                out.append(f"    unmatched: {', '.join(b.unmatched)}")
        return "\n".join(out)

    _emit(a, c, text)
    return 0


SCHEMAS: dict[str, type[BaseModel]] = {
    "rules": RuleSet,
    "composition": Composition,
    "scenario": Scenario,
    "alignment": Alignment,
    "fixture": Fixture,
    "crossovers": CrossoverFixture,
    "portfolio": Portfolio,
}


def cmd_schema(a: argparse.Namespace) -> int:
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    for name, cls in SCHEMAS.items():
        (out / f"{name}.schema.json").write_text(
            json.dumps(cls.model_json_schema(), indent=2) + "\n", encoding="utf-8"
        )
    print(f"wrote {len(SCHEMAS)} schemas to {out}")
    return 0


# ----------------------------------------------------------------------- parser


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="impsolver",
        description="Neutral vote-math solver for "
        "impeachment (House) and conviction (Senate). " + NEUTRALITY,
    )
    ap.add_argument("--format", choices=["text", "json"], default="text")
    sub = ap.add_subparsers(dest="command", required=True)

    def add(
        name: str, fn: Callable[[argparse.Namespace], int], **kw: Any
    ) -> argparse.ArgumentParser:
        p = sub.add_parser(name, **kw)
        p.add_argument("--format", choices=["text", "json"], default=argparse.SUPPRESS)
        p.set_defaults(fn=fn)
        return p

    p = add("validate", cmd_validate, help="validate rules, composition and scenario files")
    p.add_argument("rules", help="built-in rule set name (us-federal) or a YAML path")
    p.add_argument("composition", nargs="?")
    p.add_argument("scenario", nargs="?")

    p = add("evaluate", cmd_evaluate, help="deterministic bounds per gate")
    p.add_argument("scenario")
    p.add_argument("--path")

    p = add("flips", cmd_flips, help="minimal changes for the gates to pass")
    p.add_argument("scenario")
    p.add_argument("--gate")
    p.add_argument("--path")
    p.add_argument("--article")
    p.add_argument("--ilp", action="store_true", help="exact ILP (the default; kept for scripts)")
    p.add_argument("--greedy", action="store_true", help="fast greedy heuristic instead of the ILP")
    p.add_argument("--constraint", action="append", default=[], metavar="BLOC<=N")
    p.add_argument("--exclude", action="append", default=[], metavar="ID")
    p.add_argument("--allow-absence", action="store_true")
    p.add_argument("--absence-cost", type=float, default=1.0)
    p.add_argument("--per-gate-stance", action="store_true")

    p = add("simulate", cmd_simulate, help="copula Monte Carlo")
    p.add_argument("scenario")
    p.add_argument("--draws", type=int, default=100_000)
    p.add_argument("--rho", type=float)
    p.add_argument("--seed", type=int)
    p.add_argument("--path")

    p = add("compare", cmd_compare, help="evaluate one scenario against several compositions")
    p.add_argument("scenario")
    p.add_argument("--composition", action="append", required=True)

    p = add("viability", cmd_viability, help="rank the scenarios you supply")
    p.add_argument("scenarios", nargs="+")
    p.add_argument("--target-p", type=float, default=0.5)
    p.add_argument("--max-gap", type=float, default=2.0)
    p.add_argument("--draws", type=int, default=20_000)

    p = add("backtest", cmd_backtest, help="replay historical roll calls")
    p.add_argument("fixtures", nargs="*")

    p = add("portfolio", cmd_portfolio, help="schedule a portfolio of candidates")
    p.add_argument("file")
    p.add_argument("--exhaustive", action="store_true")
    p.add_argument("--html", metavar="OUT", help="also write a self-contained HTML planning page")

    p = add("calibrate", cmd_calibrate, help="check alignment against known crossovers")
    p.add_argument(
        "fixture",
        nargs="?",
        default=str(BUILTIN_FIXTURES / "members" / "trump-2021-crossovers.yaml"),
        help="crossover fixture (default: the built-in 2021 crossovers)",
    )
    p.add_argument("--alignment", required=True)
    p.add_argument("--min-votes", type=int, default=100)
    p.add_argument("--permutations", type=int, default=5000)
    p.add_argument("--seed", type=int, default=0)

    p = add("schema", cmd_schema, help="write JSON schemas")
    p.add_argument("--out", default="schemas")

    sub.add_parser(
        "roster", help="build a composition from Voteview (see roster --help)", add_help=False
    )
    sub.add_parser(
        "align", help="fit alignment loadings from Voteview (see align --help)", add_help=False
    )
    return ap


ERRORS = (
    LoadError,
    ValidationError,
    ResolutionError,
    PathError,
    FlipError,
    PriorError,
    PortfolioError,
    CliError,
    ValueError,
    KeyError,
    OSError,
)


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == "roster":
        return roster_mod.main(argv[1:])
    if argv and argv[0] == "align":
        return alignment_mod.main(argv[1:])
    args = build_parser().parse_args(argv)
    try:
        rc: int = args.fn(args)
        return rc
    except ERRORS as e:
        msg = str(e) if not isinstance(e, KeyError) else f"unknown key {e}"
        print(f"error: {msg}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
