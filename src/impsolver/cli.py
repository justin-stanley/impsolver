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
from .compare import CompareError, Comparison, PortfolioSide
from .compare import compare as compare_plans
from .deterministic import default_path, evaluate
from .flips import ABSENCE_NOTE, FlipError, find_flips
from .loader import (
    BUILTIN_FIXTURES,
    LoadError,
    load_alignment,
    load_composition,
    load_crossovers,
    load_portfolio,
    load_rules,
    load_scenario,
    resolve,
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
from .paths import PathError, path_for
from .portfolio import PortfolioError, PortfolioResult, change_dates, epoch_preps
from .portfolio import load as load_portfolio_inputs
from .portfolio import solve as solve_portfolio
from .prepare import Prepared
from .prepare import prepare as _prepare_raw
from .priors import PriorError
from .report import render as render_report
from .report import render_comparison
from .results import Evaluation, FlipResult, Simulation
from .score import (
    DEFAULT_BETAS,
    DEFAULT_RHOS,
    DEFAULT_WEIGHTS,
    MIN_EFFECTIVE_DRAWS,
    ScorePoint,
    Sweep,
    sweep,
)
from .simulate import simulate
from .templates import DEFAULT_NAMES, TEMPLATES
from .viability import Case, assess

PIVOT_HEADING = "members nearest the threshold (by the supplied probabilities)"


class CliError(Exception):
    pass


# Which template each template refers to when they share a folder.
NEEDS = {"scenario": "composition", "portfolio": "scenario"}


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
        if a.pivots:
            short = next(g.short_at_min for g in a.gates if g.stage == a.binding_gate)
            out.append(f"  {PIVOT_HEADING} at {a.binding_gate}, short {short} at the minimum:")
            out += [
                f"    {m.id:12} {m.bloc:4} p={m.p:.3f} {m.source:14} {m.name}" for m in a.pivots
            ]
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
    head = f"{s.target}: {s.draws} draws, rho={s.rho}, seed={s.seed}, aligned={s.aligned}"
    if s.uncertainty_draws:
        head += f", {s.uncertainty_draws} outer draws over uncertain priors"
    out = [head]
    for a in s.articles:
        line = (
            f"\nArticle {a.article}, path {a.path}: P(complete)={a.p_complete:.4f} "
            f"(MC s.e. {a.mc_se:.4f})"
        )
        if a.p_complete_interval is not None:
            lo, hi = a.p_complete_interval
            line += f", 5-95% over priors [{lo:.4f}, {hi:.4f}]"
        out.append(line)
        for g in a.gates:
            c = g.pro_count
            out.append(
                f"  {g.stage:4} reached {g.p_reached:.4f}  pass|reached "
                f"{g.p_pass_given_reached:.4f}  PRO mean {c.mean:.1f} "
                f"[p5 {c.p5:.0f}, p50 {c.p50:.0f}, p95 {c.p95:.0f}]"
            )
    if s.p_any_complete is not None and s.p_any_complete_interval is not None:
        lo, hi = s.p_any_complete_interval
        out.append(
            f"\nAny article: P(removal)={s.p_any_complete:.4f}, "
            f"5-95% over priors [{lo:.4f}, {hi:.4f}]"
        )
    return "\n".join(out)


# ------------------------------------------------------------------- commands


def prepare(path: str, composition: str | None = None) -> Prepared:
    """Load a scenario and print its warnings (unknown ids or blocs) to stderr."""
    prep = _prepare_raw(path, composition)
    for w in prep.warnings:
        print(f"warning: {w}", file=sys.stderr)
    return prep


def _validate_portfolio(path: str) -> tuple[str, list[str]]:
    """Check a portfolio and every scenario it references without simulating them.

    Returns a one-line summary and the warnings, each prefixed with its candidate id.
    """
    pf = load_portfolio(path)  # also rejects unknown ids in after/excludes/succession
    warnings: list[str] = []
    n_scen = 0
    for c in pf.candidates:
        if c.scenario is None:
            continue
        n_scen += 1
        try:
            prep = _prepare_raw(resolve(c.scenario, path))
            if c.article is not None and c.article not in prep.scenario.articles:
                raise CliError(
                    f"article {c.article} is not in the scenario's articles "
                    f"({', '.join(prep.scenario.articles)})"
                )
            path_for(prep.rules, prep.scenario, default_path(prep))
            evaluate(prep)  # resolves every probability
            eps = epoch_preps(pf, resolve(c.scenario, path), f"candidate {c.id}")
            for d, ep in zip(change_dates(pf), eps, strict=True):
                evaluate(ep)  # each roster epoch, so a new seat without a prior fails here
                prep.warnings += [
                    f"roster from {d}: {w}" for w in ep.warnings if w not in prep.warnings
                ]
        except ERRORS as e:
            msg = str(e) if not isinstance(e, KeyError) else f"unknown key {e}"
            raise CliError(f"{path}: candidate {c.id}: {msg}") from e
        warnings += [f"candidate {c.id}: {w}" for w in prep.warnings]
    for w in warnings:
        print(f"warning: {w}", file=sys.stderr)
    return f"portfolio ok: {len(pf.candidates)} candidates, {n_scen} scenarios", warnings


def cmd_validate(a: argparse.Namespace) -> int:
    report: dict[str, str] = {}
    if a.rules is None and a.portfolio is None:
        raise CliError(
            "validate needs a rule set (with optional composition and scenario), "
            "--portfolio FILE, or both"
        )
    if a.rules is not None:
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
    if a.portfolio:
        summary, warnings = _validate_portfolio(a.portfolio)
        if warnings:
            raise CliError(f"{a.portfolio}: {len(warnings)} warning(s); see above")
        report[a.portfolio] = summary
    _emit(a, report, lambda: "\n".join(f"{k}: {v}" for k, v in report.items()))
    return 0


def cmd_init(a: argparse.Namespace) -> int:
    text = TEMPLATES[a.kind]
    if a.out is None:
        sys.stdout.write(text)
        return 0
    out = Path(a.out)
    if out.exists() and not a.force:
        raise CliError(f"{out} already exists; pass --force to overwrite it")
    out.write_text(text, encoding="utf-8")
    hint = f"; it expects {DEFAULT_NAMES[NEEDS[a.kind]]} next to it" if a.kind in NEEDS else ""
    print(f"wrote {a.kind} template to {out}{hint}", file=sys.stderr)
    return 0


FIXED_ATTENDANCE_NOTE = (
    "note: attendance is random in this scenario, but {cmd} counts every present member; "
    "use simulate to see the effect of absences"
)


def cmd_evaluate(a: argparse.Namespace) -> int:
    prep = prepare(a.scenario)
    if prep.scenario.attendance == "random":
        print(FIXED_ATTENDANCE_NOTE.format(cmd="evaluate"), file=sys.stderr)
    e = evaluate(prep, a.path)
    _emit(a, e, lambda: render_evaluation(e))
    return 0


def cmd_flips(a: argparse.Namespace) -> int:
    prep = prepare(a.scenario)
    if prep.scenario.attendance == "random":
        print(FIXED_ATTENDANCE_NOTE.format(cmd="flips"), file=sys.stderr)
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
    s = simulate(
        prepare(a.scenario),
        draws=a.draws,
        rho=a.rho,
        seed=a.seed,
        path_name=a.path,
        uncertainty_draws=a.uncertainty_draws,
    )
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


def render_comparison_text(c: Comparison) -> str:
    out: list[str] = []
    for tag, side in (("A", c.a), ("B", c.b)):
        if isinstance(side, PortfolioSide):
            out.append(
                f"\n{tag}: {side.file}\n  E[removals]={side.expected_removals:.3f}  order "
                f"{' > '.join(side.recommended_order) or 'none'}"
            )
            tornadoes = list(side.result.tornado.values())
        else:
            out.append(
                f"\n{tag}: {side.file}\n  {side.target} ({side.office}) on {side.composition}: "
                f"P(removal)={side.p_removal:.4f}"
            )
            tornadoes = [side.tornado]
        for t in tornadoes:
            out.append(f"  {t.id or t.label}: {t.basis} {t.base:.4f}")
            out += [
                f"    {b.input:16} {b.low_setting:>18} {b.p_low:.4f}  "
                f"{b.high_setting:>18} {b.p_high:.4f}  swing {b.swing:.4f}"
                for b in t.bars
            ]
    return "\n".join(out)


def cmd_compare_plans(a: argparse.Namespace) -> int:
    c, warnings = compare_plans(a.a, a.b, draws=a.draws, exhaustive=a.exhaustive)
    for w in warnings:
        print(f"warning: {w}", file=sys.stderr)
    if a.html:
        Path(a.html).write_text(render_comparison(c), encoding="utf-8")
        print(f"wrote {a.html}", file=sys.stderr)
    _emit(a, c, lambda: render_comparison_text(c))
    return 0


def cmd_viability(a: argparse.Namespace) -> int:
    cases = [Case(str(p), prepare(p)) for p in a.scenarios]
    rows = assess(cases, target_p=a.target_p, max_gap=a.max_gap, draws=a.draws)

    def text() -> str:
        out: list[str] = []
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
    # The tornado runs are only shown on the page and in JSON; skip them for plain text.
    r = solve_portfolio(
        loaded, exhaustive=a.exhaustive, sensitivities=bool(a.html) or a.format == "json"
    )
    if a.html:
        Path(a.html).write_text(render_report(r, loaded.pf), encoding="utf-8")
        print(f"wrote {a.html}", file=sys.stderr)

    def text() -> str:
        out: list[str] = []
        for i, p in enumerate(r.plans, 1):
            out.append(
                f"\nPlan {i}: E[removals]={p.expected_removals:.3f}  order {' > '.join(p.order)}"
            )
            for s in p.slots:
                out.append(
                    f"  {s.id:16} House {s.house_start}..{s.house_end}  "
                    f"trial {s.trial_start}..{s.trial_end}  p0={s.p0:.3f} p={s.p:.3f}"
                    + (f"  roster from {r.epochs[s.epoch - 1]}" if s.epoch else "")
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


def _floats(text: str) -> list[float]:
    try:
        return [float(v) for v in text.split(",") if v.strip()]
    except ValueError as e:
        raise argparse.ArgumentTypeError(f"expected comma-separated numbers, got {text!r}") from e


def _settings(q: ScorePoint) -> str:
    parts = [f"beta {q.beta:g}"]
    if q.rho is not None:
        parts.append(f"rho {q.rho:g}")
    if q.weight is not None:
        parts.append(f"weight {q.weight:g}")
        if q.weight > 0 and q.kappa is not None:
            parts.append(f"kappa {q.kappa:g}")
    return ", ".join(parts)


def _low(q: ScorePoint) -> str:
    if q.min_effective_draws is not None and q.min_effective_draws < MIN_EFFECTIVE_DRAWS:
        return "  (low effective draws: Monte Carlo error)"
    return ""


def _scored(q: ScorePoint) -> str:
    return f"Brier {q.brier:.4f}  log {q.log_loss:.4f}{_low(q)}"


def render_sweep(s: Sweep, top: int) -> str:
    base = "observed share per event" if s.base_rate is None else f"{s.base_rate:g}"
    out = [
        f"score: events {', '.join(s.events)}; base rate {base}; min votes {s.min_votes}",
        "lower is better (Brier = mean squared error, log = mean log loss in nats)",
    ]
    out += [f"skipped: {x}" for x in s.skipped]
    for c in s.chambers:
        out.append(
            f"\n{c.body}: {len(c.events)} event(s), {c.n_members} members, {c.n_crossed} crossed"
        )
        for e in c.events:
            if e.n_not_voting is None:
                out.append(
                    f"  {e.case}: fixture lists no non-voters, so members who did not vote "
                    "(absent or no longer seated) are scored as non-crossers"
                )
            elif e.n_not_voting:
                out.append(f"  {e.case}: {e.n_not_voting} members left out as not voting")
            if e.unmatched:
                out.append(f"  {e.case} unmatched: {', '.join(e.unmatched)}")
        out.append("  marginal P(cross), by beta:")
        for q in c.marginal:
            mark = "  <- default" if q.beta == c.default_marginal.beta else ""
            out.append(f"    beta {q.beta:5.2f}  {_scored(q)}{mark}")
        bm, bb = c.best_marginal, c.best_marginal_brier
        out.append(f"  best by log: {_settings(bm)}; by Brier: {_settings(bb)}")
        if c.best_conditional is not None and c.default_conditional is not None:
            out.append(
                f"  conditional P(cross | other members), top {top} of {len(c.conditional)}:"
            )
            for q in sorted(c.conditional, key=lambda q: (q.log_loss, q.beta))[:top]:
                out.append(f"    {_settings(q):40s} {_scored(q)}")
            out.append(
                f"    default: {_settings(c.default_conditional)}: {_scored(c.default_conditional)}"
            )
            bcb = c.best_conditional_brier
            assert bcb is not None
            out.append(f"  best by Brier: {_settings(bcb)}{_low(bcb)}")
            if c.min_effective_draws is not None:
                skip = (
                    f"; best settings skip points below {MIN_EFFECTIVE_DRAWS:g}"
                    if c.min_effective_draws < MIN_EFFECTIVE_DRAWS
                    else ""
                )
                out.append(
                    f"  smallest effective draws: {c.min_effective_draws:.0f} of {s.draws}{skip}"
                )
        for label, held in (("marginal", c.loeo_marginal), ("conditional", c.loeo_conditional)):
            for h in held:
                out.append(
                    f"  held out {h.event} ({label}): chose {_settings(h.chosen)}; "
                    f"log {h.log_loss:.4f} vs default {h.default_log_loss:.4f}, "
                    f"Brier {h.brier:.4f} vs default {h.default_brier:.4f}"
                )
    out += [f"note: {n}" for n in s.notes]
    out.append("note: the sweep reports only; it does not change any default")
    return "\n".join(out)


def cmd_score(a: argparse.Namespace) -> int:
    paths = a.fixtures or sorted((BUILTIN_FIXTURES / "members").glob("*.yaml"))
    s = sweep(
        [load_crossovers(p) for p in paths],
        [load_alignment(p) for p in a.alignment],
        betas=a.beta,
        rhos=a.rho,
        weights=a.weight,
        base_rate=a.base_rate,
        min_votes=a.min_votes,
        draws=a.draws,
        seed=a.seed,
        conditional=not a.marginal_only,
    )
    _emit(a, s, lambda: render_sweep(s, a.top))
    return 0


SCHEMAS: dict[str, type[BaseModel]] = {
    "rules": RuleSet,
    "composition": Composition,
    "scenario": Scenario,
    "alignment": Alignment,
    "fixture": Fixture,
    "crossovers": CrossoverFixture,
    "portfolio": Portfolio,
    "report": PortfolioResult,
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
        description="Counts the votes needed to impeach and remove a U.S. official, "
        "and estimates the odds of getting them.",
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

    p = add(
        "validate",
        cmd_validate,
        help="validate rules, composition, scenario and portfolio files",
        description="Check input files without running them. Exits 2 on any error or warning.",
    )
    p.add_argument("rules", nargs="?", help="built-in rule set name (us-federal) or a YAML path")
    p.add_argument("composition", nargs="?")
    p.add_argument("scenario", nargs="?")
    p.add_argument(
        "--portfolio",
        metavar="FILE",
        help="also check a portfolio and every scenario its candidates reference",
    )

    p = add(
        "init",
        cmd_init,
        help="write a commented starter file (placeholder officials only)",
        description="Write a commented template that validates. composition.yaml, "
        "scenario.yaml and portfolio.yaml in one folder refer to each other.",
    )
    p.add_argument("kind", choices=sorted(TEMPLATES))
    p.add_argument("--out", metavar="FILE", help="write here instead of standard output")
    p.add_argument("--force", action="store_true", help="overwrite an existing --out file")

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
    p.add_argument(
        "--draws",
        type=int,
        help="draws (default 100000; per outer draw, default 2000, with uncertainty_draws)",
    )
    p.add_argument(
        "--uncertainty-draws",
        type=int,
        metavar="N",
        help="outer draws over range/beta priors (overrides the scenario's uncertainty_draws)",
    )
    p.add_argument("--rho", type=float)
    p.add_argument("--seed", type=int)
    p.add_argument("--path")

    p = add("compare", cmd_compare, help="evaluate one scenario against several compositions")
    p.add_argument("scenario")
    p.add_argument("--composition", action="append", required=True)

    p = add(
        "compare-plans",
        cmd_compare_plans,
        help="two portfolios or two scenarios side by side, with tornado sensitivity",
        description="Compute two portfolios (or two scenarios) as their own commands would, "
        "and show them side by side with one-notch sensitivity of each case's P(removal).",
    )
    p.add_argument("a", metavar="A.yaml")
    p.add_argument("b", metavar="B.yaml")
    p.add_argument("--html", metavar="OUT", help="also write a self-contained comparison page")
    p.add_argument(
        "--draws",
        type=int,
        default=20_000,
        help="draws per run for scenarios (portfolios use their own draws)",
    )
    p.add_argument("--exhaustive", action="store_true", help="exhaustive portfolio search")

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

    p = add(
        "score",
        cmd_score,
        help="score crossing predictions on crossover fixtures over a grid of settings",
        description="Brier and log scores of per-member crossing predictions on crossover "
        "fixtures, over a grid of beta (defection prior), rho and alignment weight, and one "
        "kappa per alignment file. Reports the best settings and, with several events, "
        "leave-one-event-out scores. It never changes defaults.",
    )
    p.add_argument(
        "fixtures", nargs="*", help="crossover fixtures (default: every built-in fixture)"
    )
    p.add_argument(
        "--alignment",
        action="append",
        required=True,
        help="alignment file; repeat with files fitted at other kappa values "
        "(impsolver align --kappa K)",
    )
    p.add_argument("--beta", type=_floats, default=list(DEFAULT_BETAS), metavar="B,B,...")
    p.add_argument("--rho", type=_floats, default=list(DEFAULT_RHOS), metavar="R,R,...")
    p.add_argument(
        "--weight",
        type=_floats,
        default=list(DEFAULT_WEIGHTS),
        metavar="W,W,...",
        help="alignment weights to try",
    )
    p.add_argument(
        "--base-rate",
        type=float,
        help="crossing base rate for every event (default: each event's observed share)",
    )
    p.add_argument("--min-votes", type=int, default=100)
    p.add_argument("--draws", type=int, default=10_000, help="importance draws per event")
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--top", type=int, default=5, help="conditional settings to list")
    p.add_argument(
        "--marginal-only",
        action="store_true",
        help="skip the conditional (rho, weight, kappa) grid",
    )

    p = add("schema", cmd_schema, help="write JSON schemas")
    p.add_argument("--out", default="schemas")

    sub.add_parser(
        "roster",
        help="build a composition from Voteview or certified results (see roster --help)",
        add_help=False,
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
    CompareError,
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
