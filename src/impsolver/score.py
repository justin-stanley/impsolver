# SPDX-FileCopyrightText: 2026 Justin Stanley
# SPDX-License-Identifier: MIT
"""Score per-member crossing predictions on crossover fixtures over a grid of settings.

For each event (a crossover fixture) and chamber, the members of the fixture's party with break
counts, a bloc break rate and at least ``min_votes`` votes in the alignment file are scored, except
those the fixture lists as ``not_voting`` (no longer seated, or absent from the vote); ``y_i`` is 1
for members listed as having crossed. Without a ``not_voting`` list, members who did not vote count
as non-crossers. An event that cannot be scored is skipped with a reason.

Marginal prediction (depends on beta only). With base rate b (the event's observed crossing share
unless ``base_rate`` is given), the defection prior gives

    p_i = sigmoid(logit(b) + beta * excess_i)

which is exactly ``priors.adjust`` applied to a party prior of b < 0.5: crossing means moving away
from the party's lean.

Conditional prediction (depends on beta, rho, the alignment weight a and the kappa the alignment
file was fitted with). Under the simulation's copula, member i crosses given the bloc swing z and
factor weights w with probability

    q_i(z, w) = Phi((Phi^-1(p_i) + sqrt(rho) z + sqrt(1-rho) a F_i.w) / (sqrt(1-rho) psi_i)),

psi_i = sqrt(1 - a^2 ||F_i||^2), which averages to p_i over z and w. The conditional prediction is
P(y_i = 1 | every other member's outcome), from Monte Carlo draws of (z, w) weighted by the
likelihood of the other members' outcomes (self-normalised importance sampling, common random
numbers across the grid). Correlation choices cannot change marginal scores, so this is how rho,
the alignment weight and kappa are scored.

Scores are Brier (mean squared error) and log loss (mean -log probability of the outcome, in nats);
lower is better for both. Pooled scores average over members of every scored event. With more
than one event, each event is held out in turn: the best settings on the others are scored on it.
Best settings skip grid points with fewer than MIN_EFFECTIVE_DRAWS effective draws, unless every
point is below it.

The sweep only reports. It never changes defaults.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from statistics import NormalDist

import numpy as np
import numpy.typing as npt
from pydantic import BaseModel

from .alignment import KAPPA
from .model import ALIGNMENT_CHAMBER_DEFAULT, Alignment, CrossoverFixture, DefectionPrior, Scenario
from .priors import Propensity

FloatArr = npt.NDArray[np.float64]

EPS = 1e-6
PSEUDO_VOTES = DefectionPrior().pseudo_votes
DEFAULT_BETA = DefectionPrior().beta
DEFAULT_RHO = float(Scenario.model_fields["rho"].default)
DEFAULT_BETAS = (0.0, 0.25, 0.5, 0.75, 1.0, 1.25, 1.5, 1.75, 2.0, 2.5, 3.0)
DEFAULT_RHOS = (0.0, 0.3, 0.6, 0.9)
DEFAULT_WEIGHTS = (0.0, 0.5, 1.0)
_ND = NormalDist()
_SQRT2 = math.sqrt(2.0)
# Numerical Recipes erfc coefficients (fractional error below 1.2e-7 everywhere, tails included).
_ERFC = (
    -1.26551223,
    1.00002368,
    0.37409196,
    0.09678418,
    -0.18628806,
    0.27886807,
    -1.13520398,
    1.48851587,
    -0.82215223,
    0.17087277,
)


class ScoreError(ValueError):
    pass


def log_ndtr(x: FloatArr) -> FloatArr:
    """log Phi(x), accurate in the lower tail."""
    z = np.abs(x) / _SQRT2
    t = 1.0 / (1.0 + 0.5 * z)
    poly = np.zeros_like(t)
    for c in reversed(_ERFC):
        poly = poly * t + c
    log_erfc = np.log(t) - z * z + poly
    lower = math.log(0.5) + log_erfc
    upper = np.log1p(-0.5 * np.exp(log_erfc))
    out: FloatArr = np.where(x < 0, lower, upper)
    return out


def _ppf(p: FloatArr) -> FloatArr:
    return np.array([_ND.inv_cdf(float(v)) for v in p], dtype=float)


def _logit(p: float) -> float:
    return math.log(p / (1.0 - p))


class ScorePoint(BaseModel):
    beta: float
    rho: float | None = None
    weight: float | None = None
    kappa: float | None = None
    brier: float
    log_loss: float
    # Conditional scores only: smallest effective number of importance draws over members and
    # events. Below about 100 the score has noticeable Monte Carlo error.
    min_effective_draws: float | None = None


class HeldOut(BaseModel):
    event: str
    chosen: ScorePoint  # best settings on the other events, with their pooled training scores
    brier: float  # held-out scores of the chosen settings
    log_loss: float
    default_brier: float  # held-out scores of the default settings
    default_log_loss: float


class EventInfo(BaseModel):
    case: str
    n_members: int
    n_crossed: int
    base_rate: float
    unmatched: list[str]
    # Members of the party left out because they cast no vote on the event. None when the
    # fixture has no not_voting list, so every party member is scored and anyone not listed as
    # crossing counts as a non-crosser, including members who were absent or no longer seated.
    n_not_voting: int | None = None


class ChamberSweep(BaseModel):
    body: str
    events: list[EventInfo]
    n_members: int
    n_crossed: int
    marginal: list[ScorePoint]
    conditional: list[ScorePoint]
    default_marginal: ScorePoint
    default_conditional: ScorePoint | None
    best_marginal: ScorePoint
    best_marginal_brier: ScorePoint
    best_conditional: ScorePoint | None
    best_conditional_brier: ScorePoint | None
    loeo_marginal: list[HeldOut]
    loeo_conditional: list[HeldOut]
    min_effective_draws: float | None
    # Alignment weights scored for this chamber: the requested grid plus the chamber's default.
    weights: list[float] = []


class Sweep(BaseModel):
    events: list[str]
    skipped: list[str]
    base_rate: float | None
    min_votes: int
    draws: int
    seed: int
    betas: list[float]
    rhos: list[float]
    # The requested grid; each chamber also scores its own default (see ChamberSweep.weights).
    weights: list[float]
    kappas: list[float]
    chambers: list[ChamberSweep]
    notes: list[str]


@dataclass
class EventData:
    case: str
    y: FloatArr  # [n]
    excess: FloatArr  # [n]
    loadings: dict[float, FloatArr]  # kappa -> F [n, k]
    base_rate: float
    unmatched: list[str]
    excluded: int = 0  # members left out because the fixture lists them as not voting
    has_voters: bool = False  # whether the fixture lists who did not vote


def event_data(
    fx: CrossoverFixture,
    chamber: str,
    alignments: dict[float, Alignment],
    min_votes: int,
    base_rate: float | None,
) -> EventData:
    """Members, outcomes, break excess and loadings for one event and chamber.

    Members on the fixture's ``not_voting`` list cast no vote on the event and are left out; so
    are members whose bloc has no break rate, as in ``priors.propensities``.
    """
    ref_kappa = min(alignments, key=lambda k: (abs(k - KAPPA), k))
    ab = alignments[ref_kappa].bodies[chamber]
    body = fx.bodies[chamber]  # type: ignore[index]
    absent = {c.id for c in body.not_voting or [] if c.id is not None}
    eligible = [
        m
        for m in ab.members
        if m.party == fx.party
        and m.breaks is not None
        and m.n_votes >= min_votes
        and m.bloc in ab.bloc_break_rate
    ]
    party = [m for m in eligible if m.id not in absent]
    excluded = len(eligible) - len(party)
    ids = [m.id for m in party]
    crossed = {c.id for c in body.crossed if c.id is not None}
    unmatched = [c.name for c in body.crossed if c.id is None or c.id not in ids]
    y = np.array([1.0 if i in crossed else 0.0 for i in ids])
    if y.sum() == 0 or y.sum() == y.size:
        raise ScoreError(f"{fx.case} {chamber}: needs both crossers and non-crossers")
    excess = np.array(
        [
            Propensity(m.breaks or 0, m.n_votes, ab.bloc_break_rate[m.bloc], "score").excess(
                PSEUDO_VOTES
            )
            for m in party
        ]
    )
    loadings: dict[float, FloatArr] = {}
    for kappa, al in alignments.items():
        by_id = {m.id: m.loadings for m in al.bodies[chamber].members}
        missing = [i for i in ids if i not in by_id]
        if missing:
            raise ScoreError(
                f"{fx.case} {chamber}: alignment with kappa {kappa} lacks members {missing[:3]}"
            )
        loadings[kappa] = np.array([by_id[i] for i in ids], dtype=float)
    b = float(y.mean()) if base_rate is None else base_rate
    return EventData(
        fx.case, y, excess, loadings, b, unmatched, excluded, body.not_voting is not None
    )


def marginal_p(ev: EventData, beta: float) -> FloatArr:
    p: FloatArr = 1.0 / (1.0 + np.exp(-(_logit(ev.base_rate) + beta * ev.excess)))
    return np.clip(p, EPS, 1.0 - EPS)


def losses(p: FloatArr, y: FloatArr) -> tuple[FloatArr, FloatArr]:
    """Per-member squared error and log loss."""
    q = np.clip(p, EPS, 1.0 - EPS)
    return (q - y) ** 2, -(y * np.log(q) + (1 - y) * np.log(1 - q))


PROPOSAL_SCALE = 1.5


def make_draws(ev: EventData, draws: int, rng: np.random.Generator) -> FloatArr:
    """Standard normal draws [N, 1 + k] for (z, w), shared by every grid point."""
    k = next(iter(ev.loadings.values())).shape[1]
    out: FloatArr = rng.standard_normal((draws, 1 + k))
    return out


def _mills(x: FloatArr) -> FloatArr:
    """phi(x) / Phi(x), stable for large negative x."""
    out: FloatArr = np.exp(-0.5 * x * x - 0.5 * math.log(2 * math.pi) - log_ndtr(x))
    return out


def _mode(G: FloatArr, c: FloatArr, sign: FloatArr) -> tuple[FloatArr, FloatArr]:
    """Posterior mode and Hessian of -log posterior for theta ~ N(0, I) and probit outcomes."""
    theta = np.zeros(G.shape[1])
    for _ in range(50):
        x = sign * (c + G @ theta)
        lam = _mills(x)
        grad = -theta + G.T @ (sign * lam)
        hess = np.eye(G.shape[1]) + G.T @ (G * (lam * (x + lam))[:, None])
        step = np.linalg.solve(hess, grad)
        theta = theta + step
        if float(np.abs(step).max()) < 1e-9:
            break
    x = sign * (c + G @ theta)
    lam = _mills(x)
    return theta, np.eye(G.shape[1]) + G.T @ (G * (lam * (x + lam))[:, None])


def conditional_p(
    ev: EventData, eps: FloatArr, beta: float, rho: float, weight: float, kappa: float
) -> tuple[FloatArr, float]:
    """P(y_i = 1 | y_-i) for every member, and the smallest effective number of draws.

    theta = (z, w) is drawn from a Gaussian centred on the posterior mode given every outcome,
    with the Laplace covariance widened by PROPOSAL_SCALE; importance weights correct to the exact
    posterior, and dividing out member i's own likelihood leaves the posterior given y_-i.
    """
    F = ev.loadings[kappa]
    t = _ppf(marginal_p(ev, beta))
    s = math.sqrt(1.0 - rho)
    idio = np.sqrt(np.clip(1.0 - weight**2 * (F**2).sum(axis=1), 1e-12, 1.0))
    denom = s * idio
    G = np.column_stack([np.full(F.shape[0], math.sqrt(rho)), s * weight * F]) / denom[:, None]
    c = t / denom
    sign = 2.0 * ev.y - 1.0
    mode, hess = _mode(G, c, sign)
    L = np.linalg.cholesky(np.linalg.inv(hess)) * PROPOSAL_SCALE
    theta = mode[None, :] + eps @ L.T
    a = c[None, :] + theta @ G.T
    lp1 = log_ndtr(a)
    lp0 = log_ndtr(-a)
    lpy = np.where(ev.y[None, :] > 0, lp1, lp0)
    # log prior - log proposal, up to a constant shared by every draw
    base = -0.5 * (theta**2).sum(axis=1) + 0.5 * (eps**2).sum(axis=1)
    logw = (base + lpy.sum(axis=1))[:, None] - lpy
    logw -= logw.max(axis=0, keepdims=True)
    w = np.exp(logw)
    sw = w.sum(axis=0)
    p = (w * np.exp(lp1)).sum(axis=0) / sw
    ess = float((sw**2 / (w**2).sum(axis=0)).min())
    return p, ess


# Grid points with fewer effective draws than this are flagged, and are not chosen as best
# settings unless every grid point is below it.
MIN_EFFECTIVE_DRAWS = 100.0


def _reliable(ess: float | None) -> bool:
    return ess is None or ess >= MIN_EFFECTIVE_DRAWS


def _best(points: list[ScorePoint], key: str = "log_loss") -> ScorePoint:
    ok = [q for q in points if _reliable(q.min_effective_draws)] or points
    return min(ok, key=lambda q: (getattr(q, key), q.beta, q.rho or 0, q.weight or 0))


Key = tuple[float, ...]
Table = dict[Key, tuple[FloatArr, FloatArr, float | None]]  # squared errors, log losses, ESS
Pooled = dict[Key, tuple[float, float, float | None]]


def _pool(per_event: list[Table], keep: list[int]) -> Pooled:
    out: Pooled = {}
    for key in per_event[0]:
        sq = np.concatenate([per_event[i][key][0] for i in keep])
        ll = np.concatenate([per_event[i][key][1] for i in keep])
        ess = [e for i in keep if (e := per_event[i][key][2]) is not None]
        out[key] = (float(sq.mean()), float(ll.mean()), min(ess) if ess else None)
    return out


def _point(key: Key, scores: tuple[float, float, float | None]) -> ScorePoint:
    names = ("beta", "rho", "weight", "kappa")
    return ScorePoint(
        **dict(zip(names, key, strict=False)),
        brier=scores[0],
        log_loss=scores[1],
        min_effective_draws=scores[2],
    )


def _sweep_table(
    per_event: list[Table],
    default_key: Key,
    names: list[str],
) -> tuple[list[ScorePoint], ScorePoint, list[HeldOut]]:
    pooled = _pool(per_event, list(range(len(per_event))))
    points = [_point(k, v) for k, v in pooled.items()]
    held: list[HeldOut] = []
    if len(per_event) > 1:
        for i, name in enumerate(names):
            train = _pool(per_event, [j for j in range(len(per_event)) if j != i])
            ok = [k for k in train if _reliable(train[k][2])] or list(train)
            key = min(ok, key=lambda k: (train[k][1], k))
            sq, ll, _ = per_event[i][key]
            dsq, dll, _ = per_event[i][default_key]
            held.append(
                HeldOut(
                    event=name,
                    chosen=_point(key, train[key]),
                    brier=float(sq.mean()),
                    log_loss=float(ll.mean()),
                    default_brier=float(dsq.mean()),
                    default_log_loss=float(dll.mean()),
                )
            )
    return points, _point(default_key, pooled[default_key]), held


def _grid(values: list[float] | tuple[float, ...], default: float) -> list[float]:
    return sorted({float(v) for v in values} | {float(default)})


def sweep(
    fixtures: list[CrossoverFixture],
    alignments: list[Alignment],
    betas: list[float] | tuple[float, ...] = DEFAULT_BETAS,
    rhos: list[float] | tuple[float, ...] = DEFAULT_RHOS,
    weights: list[float] | tuple[float, ...] = DEFAULT_WEIGHTS,
    base_rate: float | None = None,
    min_votes: int = 100,
    draws: int = 10_000,
    seed: int = 0,
    conditional: bool = True,
) -> Sweep:
    """Score crossing predictions on every fixture an alignment file covers.

    Each alignment file is one kappa value; files covering the same congress must differ in kappa.
    The default settings (beta, rho, the chamber's default alignment weight, and kappa 50 or the
    nearest available) are always added to the grid.
    """
    if not fixtures:
        raise ScoreError("no crossover fixtures")
    if not alignments:
        raise ScoreError("no alignment files")
    if base_rate is not None and not 0.0 < base_rate < 0.5:
        raise ScoreError("base rate must be in (0, 0.5)")
    if any(not 0.0 <= r < 1.0 for r in rhos):
        raise ScoreError("rho values must be in [0, 1)")
    if any(not 0.0 <= w <= 1.0 for w in weights):
        raise ScoreError("alignment weights must be in [0, 1]")
    if draws < 100:
        raise ScoreError("draws must be at least 100")
    by_congress: dict[int, dict[float, Alignment]] = {}
    for al in alignments:
        for c in al.congresses:
            slot = by_congress.setdefault(c, {})
            if al.kappa in slot:
                raise ScoreError(f"two alignment files cover congress {c} with kappa {al.kappa}")
            slot[al.kappa] = al
    used = [fx for fx in fixtures if fx.history_congress in by_congress]
    skipped = [
        f"{fx.case}: no alignment file covers congress {fx.history_congress}"
        for fx in fixtures
        if fx.history_congress not in by_congress
    ]
    if not used:
        raise ScoreError("no alignment file covers any fixture's history congress")
    kappa_sets = [set(by_congress[fx.history_congress]) for fx in used]
    kappas = sorted(set.intersection(*kappa_sets))
    notes: list[str] = []
    if set.union(*kappa_sets) != set(kappas):
        notes.append("kappa values not available for every event were left out")
    if not kappas:
        raise ScoreError("no kappa value is available for every event")
    default_kappa = min(kappas, key=lambda k: (abs(k - KAPPA), k))
    if default_kappa != KAPPA:
        notes.append(f"default kappa {KAPPA:g} not supplied; kappa {default_kappa:g} stands in")
    if base_rate is None:
        notes.append(
            "base rate is each event's observed crossing share, so scores measure how well the "
            "settings rank and spread members, not how well the overall rate is guessed"
        )
    beta_grid = _grid(betas, DEFAULT_BETA)
    rho_grid = _grid(rhos, DEFAULT_RHO)
    chambers: list[ChamberSweep] = []
    for ci, chamber in enumerate(("house", "senate")):
        evs: list[EventData] = []
        for fx in used:
            if chamber not in fx.bodies:
                continue
            als = {k: a for k, a in by_congress[fx.history_congress].items() if k in set(kappas)}
            if any(chamber not in a.bodies for a in als.values()):
                skipped.append(f"{fx.case} {chamber}: alignment has no {chamber} body")
                continue
            try:
                evs.append(event_data(fx, chamber, als, min_votes, base_rate))
            except ScoreError as e:
                skipped.append(str(e))
        if not evs:
            continue
        if len(evs) < 2 <= len(used):
            notes.append(
                f"{chamber}: one scored event only: no leave-one-event-out scores; "
                "its scores are in-sample"
            )
        names = [e.case for e in evs]
        default_w = ALIGNMENT_CHAMBER_DEFAULT[chamber]  # type: ignore[index]
        weight_grid = _grid(weights, default_w)
        marg: list[Table] = [
            {(b,): (*losses(marginal_p(ev, b), ev.y), None) for b in beta_grid} for ev in evs
        ]
        m_points, m_default, m_held = _sweep_table(marg, (DEFAULT_BETA,), names)
        c_points: list[ScorePoint] = []
        c_default: ScorePoint | None = None
        c_held: list[HeldOut] = []
        min_ess: float | None = None
        if conditional:
            cond = []
            for i, ev in enumerate(evs):
                rng = np.random.Generator(np.random.PCG64([seed, i, ci]))
                d = make_draws(ev, draws, rng)
                table: Table = {}
                for b in beta_grid:
                    for r in rho_grid:
                        for w in weight_grid:
                            for k in kappas:
                                if w == 0.0 and k != default_kappa:
                                    continue  # loadings unused: same score at every kappa
                                p, ess = conditional_p(ev, d, b, r, w, k)
                                min_ess = ess if min_ess is None else min(min_ess, ess)
                                table[(b, r, w, k)] = (*losses(p, ev.y), ess)
                cond.append(table)
            dkey = (DEFAULT_BETA, DEFAULT_RHO, default_w, default_kappa)
            c_points, c_default, c_held = _sweep_table(cond, dkey, names)
        chambers.append(
            ChamberSweep(
                weights=[float(w) for w in weight_grid],
                body=chamber,
                events=[
                    EventInfo(
                        case=e.case,
                        n_members=int(e.y.size),
                        n_crossed=int(e.y.sum()),
                        base_rate=e.base_rate,
                        unmatched=e.unmatched,
                        n_not_voting=e.excluded if e.has_voters else None,
                    )
                    for e in evs
                ],
                n_members=sum(int(e.y.size) for e in evs),
                n_crossed=sum(int(e.y.sum()) for e in evs),
                marginal=m_points,
                conditional=c_points,
                default_marginal=m_default,
                default_conditional=c_default,
                best_marginal=_best(m_points),
                best_marginal_brier=_best(m_points, "brier"),
                best_conditional=_best(c_points) if c_points else None,
                best_conditional_brier=_best(c_points, "brier") if c_points else None,
                loeo_marginal=m_held,
                loeo_conditional=c_held,
                min_effective_draws=min_ess,
            )
        )
    if not chambers:
        raise ScoreError("no event could be scored: " + "; ".join(skipped))
    if len(used) < 2:
        notes.append("one event only: no leave-one-event-out scores; all scores are in-sample")
    return Sweep(
        events=[fx.case for fx in used],
        skipped=skipped,
        base_rate=base_rate,
        min_votes=min_votes,
        draws=draws,
        seed=seed,
        betas=beta_grid,
        rhos=rho_grid,
        weights=sorted({float(w) for w in weights}),
        kappas=kappas,
        chambers=chambers,
        notes=notes,
    )
