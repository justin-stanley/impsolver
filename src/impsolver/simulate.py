# SPDX-FileCopyrightText: 2026 Justin Stanley
# SPDX-License-Identifier: MIT
"""Gaussian-copula Monte Carlo over the gates of a path.

Without alignment: u_i = sqrt(rho) z_bloc + sqrt(1-rho) e_i, and member i is PRO at gate g iff
u_i < Phi^-1(p_ig). The same u is reused at every gate within a draw.

With alignment loadings F_i (scaled by alignment_weight):
    u_ig = sqrt(rho) z_bloc + sqrt(1-rho) (s_ig F_i.w + sqrt(1 - s_ig^2 ||F_i||^2) e_i)
where s_ig = sign(lean_bg - 0.5) and lean_bg is the mean p of the bloc's free members at the gate.
A large F_i.w therefore means "breaking from the bloc's lean" at every gate. Every marginal is
preserved because the variance of u_ig is 1.

With ``attendance: random``, each present member is also absent in a draw with their missed-vote
rate, independently of everything else. One attendance draw covers every gate of a chamber.
Absent members leave the votes cast, the two-thirds-of-present denominator and the quorum count.
Absences come from a second generator seeded from the same seed, so the vote draws are exactly
those of the fixed-attendance run (common random numbers).

With ``gate_correlation`` c < 1, each gate after the first in a chamber gets its own draw of every
component (z, w, e): x_g = sqrt(c) x_(g-1) + sqrt(1-c) x', with x' fresh standard normal. Each
component stays standard normal, so every marginal is preserved, and u at adjacent gates has
correlation c. c = 1 reuses one draw at every gate and consumes no extra random numbers.

With ``uncertainty_draws`` N > 0 and at least one prior given as a range or a Beta, an outer loop
draws N sets of prior values (one value per prior per set, shared by every member and stage that
resolves to it) from PCG64([seed, 0x0DD5]). Each set runs the inner copula draws with the same
seed (common random numbers), so the spread of P(complete) across sets reflects the priors only.
P(complete) is the mean over sets (the pooled draws); the article also reports the 5th and 95th
percentiles across sets.
"""

from __future__ import annotations

from dataclasses import dataclass
from statistics import NormalDist

import numpy as np
import numpy.typing as npt

from .deterministic import default_path
from .model import Alignment, Chamber, Member, Stage
from .paths import Path, path_for
from .prepare import Prepared
from .results import CountHist, CountSummary, SimArticle, SimGate, Simulation
from .thresholds import has_quorum, membership_base, pro_wins, tie_mode
from .uncertainty import has_uncertainty, sample_scenario

CHUNK = 10_000
ATTENDANCE_STREAM = 0xA77E
UNCERTAINTY_STREAM = 0x0DD5
DEFAULT_DRAWS = 100_000
# Inner draws per outer draw when the outer loop is on and ``draws`` is not given.
DEFAULT_INNER_DRAWS = 2_000
_ND = NormalDist()

FloatArr = npt.NDArray[np.float64]


def norm_ppf(p: FloatArr) -> FloatArr:
    out = np.empty_like(p, dtype=float)
    for idx, v in np.ndenumerate(p):
        out[idx] = -np.inf if v <= 0 else (np.inf if v >= 1 else _ND.inv_cdf(float(v)))
    return out


def bloc_order(members: list[Member]) -> list[str]:
    return list(dict.fromkeys(m.bloc for m in members))


def loadings_for(
    alignment: Alignment | None, chamber: str, members: list[Member], weight: float
) -> FloatArr | None:
    if alignment is None or weight == 0.0 or chamber not in alignment.bodies:
        return None
    ab = alignment.bodies[chamber]
    by_id = {m.id: m.loadings for m in ab.members}
    rows = []
    for m in members:
        v = by_id.get(m.id) or ab.bloc_mean_loadings.get(m.bloc) or [0.0] * ab.k
        rows.append(v)
    return weight * np.asarray(rows, dtype=float)


def bloc_signs(p: FloatArr, bloc_idx: npt.NDArray[np.int64], n_blocs: int) -> FloatArr:
    """s[g, i] from the lean of member i's bloc at gate g."""
    s = np.zeros_like(p)
    for b in range(n_blocs):
        cols = bloc_idx == b
        for g in range(p.shape[0]):
            vals = p[g, cols]
            free = vals[(vals > 0) & (vals < 1)]
            if free.size == 0:
                continue
            lean = float(free.mean())
            s[g, cols] = 1.0 if lean > 0.5 else (-1.0 if lean < 0.5 else 0.0)
    return s


def chamber_weight(prep: Prepared, chamber: str) -> float:
    sc = prep.scenario
    w: float = sc.alignment_chamber_weight.get(chamber, 0.0)  # type: ignore[call-overload]
    return sc.alignment_weight * w


@dataclass
class ChamberModel:
    chamber: Chamber
    stages: list[Stage]
    members: list[Member]
    thresholds: FloatArr  # [g, n]
    bloc_idx: npt.NDArray[np.int64]
    n_blocs: int
    F: FloatArr | None
    signs: FloatArr | None
    seats: int
    vacancies: int
    p_absent: FloatArr | None = None  # [n]; None means fixed attendance

    def draw_absent(self, rng: np.random.Generator, m: int) -> npt.NDArray[np.bool_] | None:
        """Boolean ABSENT array [draws, n], or None when attendance is fixed."""
        if self.p_absent is None:
            return None
        res: npt.NDArray[np.bool_] = rng.random((m, len(self.members))) < self.p_absent
        return res

    def draw_pro(
        self,
        rng: np.random.Generator,
        m: int,
        rho: float,
        z: FloatArr | None = None,
        gate_correlation: float = 1.0,
    ) -> npt.NDArray[np.bool_]:
        """Boolean PRO array [g, draws, n]. ``z`` ([draws, blocs]) lets callers share swings.

        ``gate_correlation`` (c) mixes each later gate's member-level draw with a fresh one:
        x_g = sqrt(c) x_(g-1) + sqrt(1-c) x', applied to the factor weights and the individual
        noise. The bloc swing ``z`` is one party mood for the whole chamber and stays fixed across
        gates, so swings shared with other chambers or other cases stay fully shared.
        """
        n = len(self.members)
        if z is None:
            z = rng.standard_normal((m, self.n_blocs))
        e = rng.standard_normal((m, n))
        w = rng.standard_normal((m, self.F.shape[1])) if self.F is not None else None
        a, b = np.sqrt(gate_correlation), np.sqrt(1.0 - gate_correlation)
        out = np.empty((len(self.stages), m, n), dtype=bool)
        for g in range(len(self.stages)):
            if g > 0 and gate_correlation < 1.0:
                e = a * e + b * rng.standard_normal(e.shape)
                if w is not None:
                    w = a * w + b * rng.standard_normal(w.shape)
            common = np.sqrt(rho) * z[:, self.bloc_idx]
            if self.F is None or w is None:
                u = common + np.sqrt(1 - rho) * e
            else:
                assert self.signs is not None
                s = self.signs[g]
                norm2 = (self.F**2).sum(axis=1)
                idio = np.sqrt(np.clip(1.0 - s**2 * norm2, 0.0, 1.0))
                u = common + np.sqrt(1 - rho) * (s * (w @ self.F.T) + idio * e)
            out[g] = u < self.thresholds[g]
        return out


def chamber_models(
    prep: Prepared, article: str, stages: list[Stage], extra: float = 0.0
) -> dict[str, ChamberModel]:
    out: dict[str, ChamberModel] = {}
    for chamber in ("house", "senate"):
        sts = [s for s in stages if s.chamber == chamber]
        if not sts:
            continue
        body = prep.comp.bodies[chamber]
        mask = prep.present_mask(chamber)
        members = [m for m, k in zip(body.roster, mask, strict=True) if k]
        p = np.vstack([prep.probs(chamber, s.id, article, extra)[mask] for s in sts])
        blocs = bloc_order(members)
        idx = np.array([blocs.index(m.bloc) for m in members], dtype=np.int64)
        F = loadings_for(prep.alignment, chamber, members, chamber_weight(prep, chamber))
        signs = bloc_signs(p, idx, len(blocs)) if F is not None else None
        absent = None
        if prep.scenario.attendance == "random":
            rates = prep.absence_rates(chamber)[mask]
            absent = rates if rates.any() else None
        out[chamber] = ChamberModel(
            chamber,
            sts,
            members,
            norm_ppf(p),
            idx,
            len(blocs),
            F,
            signs,
            body.seats,
            body.vacancies,
            absent,
        )
    return out


@dataclass
class RawSim:
    stages: list[Stage]
    n_required: int
    pro: npt.NDArray[np.int64]  # [g, draws]
    passed: npt.NDArray[np.bool_]  # [g, draws]
    present: npt.NDArray[np.int64]  # [g, draws] members in the chamber for the vote
    # Per stage id, per roster member: draws in which that member's vote decided the gate.
    decisive: dict[str, npt.NDArray[np.int64]] | None = None
    random_attendance: bool = False

    @property
    def complete(self) -> npt.NDArray[np.bool_]:
        return np.all(self.passed[: self.n_required], axis=0)


def run_raw(
    prep: Prepared,
    article: str,
    path: Path,
    draws: int,
    seed: int,
    rho: float,
    extra: float = 0.0,
    shared: dict[tuple[str, str], FloatArr] | None = None,
    decisive: bool = False,
) -> RawSim:
    """Simulate ``draws`` passes through ``path``.

    ``shared`` maps (chamber, bloc) to a full-length array of party swings. Blocs found there use
    those swings instead of fresh ones, which correlates outcomes across scenarios.

    ``decisive`` also counts, per gate and member, the draws in which the gate's result would
    flip if that one member's vote flipped (the tally sits exactly on the line with the member
    PRO, or one short with the member not PRO). It reads the same draws and changes no result.
    """
    stages = list(path.all_stages)
    models = chamber_models(prep, article, stages, extra)
    rng = np.random.Generator(np.random.PCG64(seed))
    # A separate stream for attendance keeps the vote draws identical to fixed attendance.
    arng = np.random.Generator(np.random.PCG64([seed, ATTENDANCE_STREAM]))
    pro = np.zeros((len(stages), draws), dtype=np.int64)
    passed = np.zeros((len(stages), draws), dtype=bool)
    present = np.zeros((len(stages), draws), dtype=np.int64)
    masks = {ch: prep.present_mask(cm.chamber) for ch, cm in models.items()}
    dec = {st.id: np.zeros(len(masks[st.chamber]), dtype=np.int64) for st in stages}
    done = 0
    while done < draws:
        m = min(CHUNK, draws - done)
        national: dict[str, FloatArr] = {}
        for ch, cm in models.items():
            z = None
            if shared is not None or prep.scenario.national_swing:
                cols = []
                for b in bloc_order(cm.members):
                    key = ("house", b) if prep.scenario.national_swing else (ch, b)
                    if shared is not None and key in shared:
                        cols.append(shared[key][done : done + m])
                    elif prep.scenario.national_swing:
                        if b not in national:
                            national[b] = rng.standard_normal(m)
                        cols.append(national[b])
                    else:
                        cols.append(rng.standard_normal(m))
                z = np.column_stack(cols)
            votes = cm.draw_pro(rng, m, rho, z, prep.scenario.gate_correlation)
            absent = cm.draw_absent(arng, m)
            n_in = np.full(m, len(cm.members), dtype=np.int64)
            if absent is not None:
                votes &= ~absent[None, :, :]
                n_in -= absent.sum(axis=1)
            gate_pro = votes.sum(axis=2)
            quorum = has_quorum(n_in, cm.seats - cm.vacancies)
            for g, st in enumerate(cm.stages):
                k = stages.index(st)
                pro[k, done : done + m] = gate_pro[g]
                present[k, done : done + m] = n_in
                base = membership_base(st.rule, cm.seats, cm.vacancies)
                zero = np.zeros(m, dtype=np.int64)
                tie = tie_mode(st, prep.scenario.senate_tie_break)
                con = n_in - gate_pro[g]
                wins = pro_wins(st.rule, st.pass_direction, gate_pro[g], con, zero, base, tie)
                passed[k, done : done + m] = wins & quorum
                if decisive:
                    # One PRO vote fewer loses a won gate; one more wins a lost one.
                    lose = ~pro_wins(
                        st.rule, st.pass_direction, gate_pro[g] - 1, con + 1, zero, base, tie
                    )
                    gain = pro_wins(
                        st.rule, st.pass_direction, gate_pro[g] + 1, con - 1, zero, base, tie
                    )
                    v = votes[g]
                    other = ~v if absent is None else ~v & ~absent
                    hits = (v & (wins & lose)[:, None]).sum(axis=0)
                    hits += (other & (~wins & gain)[:, None]).sum(axis=0)
                    dec[st.id][masks[ch]] += hits
        done += m
    return RawSim(
        stages,
        len(path.stages),
        pro,
        passed,
        present,
        dec if decisive else None,
        any(cm.p_absent is not None for cm in models.values()),
    )


def summarize(x: npt.NDArray[np.int64]) -> CountSummary:
    q = np.percentile(x, [5, 50, 95])
    return CountSummary(mean=float(x.mean()), p5=float(q[0]), p50=float(q[1]), p95=float(q[2]))


def histogram(x: npt.NDArray[np.int64]) -> CountHist:
    """Draws per count, trimmed to the counts that occur."""
    if x.size == 0:
        return CountHist(start=0, counts=[])
    lo = int(x.min())
    return CountHist(start=lo, counts=[int(c) for c in np.bincount(x - lo)])


def _gates(raw: RawSim, detail: bool = False) -> list[SimGate]:
    reached = np.ones(raw.pro.shape[1], dtype=bool)
    draws = raw.pro.shape[1]
    gates: list[SimGate] = []
    for k, st in enumerate(raw.stages):
        r = float(reached.mean())
        pp = float(raw.passed[k][reached].mean()) if reached.any() else 0.0
        gate = SimGate(
            stage=st.id, p_reached=r, p_pass_given_reached=pp, pro_count=summarize(raw.pro[k])
        )
        if detail:
            n = int(reached.sum())
            gate.n_reached = n
            gate.pass_se = float(np.sqrt(pp * (1 - pp) / n)) if n else None
            gate.pro_count_reached = summarize(raw.pro[k][reached]) if n else None
            gate.pro_hist = histogram(raw.pro[k][reached])
            if raw.random_attendance:
                gate.present_count = summarize(raw.present[k])
            if raw.decisive is not None:
                gate.decisive_share = [round(float(c) / draws, 5) for c in raw.decisive[st.id]]
        gates.append(gate)
        reached = reached & raw.passed[k]
    return gates


def simulate_article(
    prep: Prepared,
    article: str,
    path: Path,
    draws: int,
    seed: int,
    rho: float,
    detail: bool = False,
) -> SimArticle:
    """One article's gate path. ``detail`` adds the per-gate fields the planning page draws."""
    raw = run_raw(prep, article, path, draws, seed, rho, decisive=detail)
    return summarize_raw(raw, article, path, draws, detail)


def summarize_raw(
    raw: RawSim, article: str, path: Path, draws: int, detail: bool = False
) -> SimArticle:
    """Per-gate pass rates and P(complete) from one simulation run."""
    pc = float(raw.complete.mean())
    return SimArticle(
        article=article,
        path=path.name,
        p_complete=pc,
        mc_se=float(np.sqrt(pc * (1 - pc) / draws)),
        gates=_gates(raw, detail),
    )


def sampled_preps(prep: Prepared, n: int, seed: int) -> list[Prepared]:
    """``n`` copies of ``prep``, each with every uncertain prior replaced by one sampled value."""
    rng = np.random.Generator(np.random.PCG64([seed, UNCERTAINTY_STREAM]))
    return [prep.with_scenario(sample_scenario(prep.scenario, rng)) for _ in range(n)]


def _spread(per: FloatArr, draws: int) -> tuple[float, float, tuple[float, float]]:
    """Mean, standard error and (p5, p95) of per-outer-draw probabilities.

    The standard error combines the spread of the mean across outer draws with the inner Monte
    Carlo error, which common random numbers do not average away: sqrt(var_t / N + p(1-p) / draws).
    """
    pc = float(per.mean())
    between = float(per.var(ddof=1)) / len(per) if len(per) > 1 else 0.0
    lo, hi = np.percentile(per, [5, 95])
    return pc, float(np.sqrt(between + pc * (1 - pc) / draws)), (float(lo), float(hi))


def simulate_article_uncertain(
    raws: list[RawSim], article: str, path: Path, draws: int
) -> SimArticle:
    """Pool the inner draws of every outer draw; report the spread across outer draws."""
    pooled = RawSim(
        raws[0].stages,
        raws[0].n_required,
        np.concatenate([r.pro for r in raws], axis=1),
        np.concatenate([r.passed for r in raws], axis=1),
        np.concatenate([r.present for r in raws], axis=1),
    )
    pc, se, interval = _spread(np.array([float(r.complete.mean()) for r in raws]), draws)
    return SimArticle(
        article=article,
        path=path.name,
        p_complete=pc,
        mc_se=se,
        gates=_gates(pooled),
        p_complete_interval=interval,
    )


def simulate(
    prep: Prepared,
    draws: int | None = None,
    rho: float | None = None,
    seed: int | None = None,
    path_name: str | None = None,
    uncertainty_draws: int | None = None,
) -> Simulation:
    """Gaussian-copula Monte Carlo over the gates of the scenario's path.

    Args:
        prep: A prepared scenario.
        draws: Number of simulated votes (per outer draw when the outer loop is on). Defaults to
            100,000, or 2,000 with the outer loop.
        rho: Bloc correlation; defaults to the scenario's ``rho``.
        seed: PCG64 seed; defaults to the scenario's ``seed``.
        path_name: ``"A"`` or ``"B"``.
        uncertainty_draws: Outer draws over uncertain priors; defaults to the scenario's
            ``uncertainty_draws``. Ignored (0) when no prior is a range or a Beta.
    """
    r = prep.scenario.rho if rho is None else rho
    s = prep.scenario.seed if seed is None else seed
    n_outer = prep.scenario.uncertainty_draws if uncertainty_draws is None else uncertainty_draws
    if n_outer < 0:
        raise ValueError("uncertainty_draws must be >= 0")
    if not has_uncertainty(prep.scenario):
        n_outer = 0
    n = draws if draws is not None else (DEFAULT_INNER_DRAWS if n_outer else DEFAULT_DRAWS)
    path = path_for(prep.rules, prep.scenario, path_name or default_path(prep))
    arts = list(prep.scenario.articles)
    p_any: float | None = None
    any_interval: tuple[float, float] | None = None
    if n_outer:
        preps = sampled_preps(prep, n_outer, s)
        raws = {a: [run_raw(p, a, path, n, s, r) for p in preps] for a in arts}
        articles = [simulate_article_uncertain(raws[a], a, path, n) for a in arts]
        if len(arts) > 1:
            # Removal on any article, per outer draw: articles share each draw's priors and swings.
            per_any = [
                float(any_complete({a: raws[a][t] for a in arts}).mean()) for t in range(n_outer)
            ]
            p_any, _, any_interval = _spread(np.array(per_any), n)
    else:
        articles = [simulate_article(prep, a, path, n, s, r) for a in arts]
    return Simulation(
        target=prep.scenario.target.name,
        draws=n,
        rho=r,
        seed=s,
        aligned=prep.alignment is not None
        and any(chamber_weight(prep, ch) > 0 for ch in ("house", "senate")),
        articles=articles,
        uncertainty_draws=n_outer,
        p_any_complete=p_any,
        p_any_complete_interval=any_interval,
    )


def p_complete(
    prep: Prepared,
    article: str | None = None,
    draws: int = 20_000,
    seed: int | None = None,
    extra: float = 0.0,
    path_name: str | None = None,
) -> float:
    path = path_for(prep.rules, prep.scenario, path_name or default_path(prep))
    art = article or prep.scenario.articles[0]
    raw = run_raw(
        prep,
        art,
        path,
        draws,
        prep.scenario.seed if seed is None else seed,
        prep.scenario.rho,
        extra,
    )
    return float(raw.complete.mean())


def run_raw_articles(
    prep: Prepared,
    articles: list[str],
    path: Path,
    draws: int,
    seed: int,
    rho: float,
    extra: float = 0.0,
    shared: dict[tuple[str, str], FloatArr] | None = None,
    decisive: bool = False,
) -> dict[str, RawSim]:
    """Run :func:`run_raw` for each article with common random numbers.

    Every article uses the same seed and the same ``shared`` swings. The generator draws the bloc
    swings, member noise and alignment factors in an order and with shapes that depend only on the
    members, blocs and loadings, never on the article, so draw ``j`` sees the same z, e and w for
    every article. Only the thresholds (and alignment signs) differ. Articles are therefore
    correlated through the shared member draws, as they are when one chamber votes on several
    articles against the same official.
    """
    return {a: run_raw(prep, a, path, draws, seed, rho, extra, shared, decisive) for a in articles}


def any_complete(raws: dict[str, RawSim]) -> npt.NDArray[np.bool_]:
    """Per-draw indicator that at least one article completes its path."""
    res: npt.NDArray[np.bool_] = np.logical_or.reduce([r.complete for r in raws.values()])
    return res


def p_any_complete(
    prep: Prepared,
    articles: list[str] | None = None,
    draws: int = 20_000,
    seed: int | None = None,
    extra: float = 0.0,
    path_name: str | None = None,
) -> float:
    """P(at least one article completes), from one joint simulation over ``articles``.

    ``articles`` defaults to all of the scenario's articles. With one article this equals
    :func:`p_complete` for the same seed and draws.
    """
    path = path_for(prep.rules, prep.scenario, path_name or default_path(prep))
    raws = run_raw_articles(
        prep,
        articles or list(prep.scenario.articles),
        path,
        draws,
        prep.scenario.seed if seed is None else seed,
        prep.scenario.rho,
        extra,
    )
    return float(any_complete(raws).mean())
