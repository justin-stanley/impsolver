"""Check alignment and break-rate signals against a known set of crossover votes."""

from __future__ import annotations

import numpy as np
from pydantic import BaseModel

from .model import Alignment, CrossoverFixture
from .priors import Propensity, fit_beta

DEFAULT_PSEUDO_VOTES = 20.0


class BodyCalibration(BaseModel):
    body: str
    n_party: int
    n_crossed: int
    unmatched: list[str]
    crossed_break_rate: float
    party_break_rate: float
    crossed_mean_alignment: float
    random_mean_alignment: float
    permutation_p: float
    beta: float | None
    beta_se: float | None


class Calibration(BaseModel):
    case: str
    history_congress: int
    party: str
    min_votes: int
    permutations: int
    seed: int
    bodies: list[BodyCalibration]


def _mean_pairwise(F: np.ndarray, idx: np.ndarray) -> float:
    sub = F[idx]
    g = sub @ sub.T
    n = len(idx)
    return float((g.sum() - np.trace(g)) / (n * (n - 1)))


def calibrate(
    fx: CrossoverFixture,
    alignment: Alignment,
    min_votes: int = 100,
    permutations: int = 5000,
    seed: int = 0,
) -> Calibration:
    if fx.history_congress not in alignment.congresses:
        raise ValueError(
            f"alignment covers congresses {alignment.congresses}, not {fx.history_congress}"
        )
    rng = np.random.Generator(np.random.PCG64(seed))
    out: list[BodyCalibration] = []
    for name, body in fx.bodies.items():
        if name not in alignment.bodies:
            raise ValueError(f"alignment has no body {name}")
        ab = alignment.bodies[name]
        party = [
            m
            for m in ab.members
            if m.party == fx.party and m.breaks is not None and m.n_votes >= min_votes
        ]
        ids = [m.id for m in party]
        crossed_ids = {c.id for c in body.crossed if c.id is not None}
        unmatched = [c.name for c in body.crossed if c.id is None or c.id not in ids]
        idx = np.array([i for i, m in enumerate(party) if m.id in crossed_ids], dtype=int)
        if idx.size < 2:
            raise ValueError(f"{name}: fewer than two crossers matched the alignment file")
        F = np.array([m.loadings for m in party], dtype=float)
        breaks = np.array([m.breaks or 0 for m in party], dtype=float)
        votes = np.array([m.n_votes for m in party], dtype=float)
        rate_x = float(breaks[idx].sum() / votes[idx].sum())
        rate_p = float(breaks.sum() / votes.sum())
        obs = _mean_pairwise(F, idx)
        sims = np.array(
            [
                _mean_pairwise(F, rng.choice(len(party), size=idx.size, replace=False))
                for _ in range(permutations)
            ]
        )
        pval = float((1 + (sims >= obs).sum()) / (1 + permutations))
        bloc_rate = ab.bloc_break_rate.get(party[0].bloc, rate_p)
        excess = [
            Propensity(int(b), int(v), bloc_rate, "calibrate").excess(DEFAULT_PSEUDO_VOTES)
            for b, v in zip(breaks, votes, strict=True)
        ]
        y = [1 if m.id in crossed_ids else 0 for m in party]
        try:
            beta, se = fit_beta(excess, y)
        except Exception:
            beta, se = None, None
        out.append(
            BodyCalibration(
                body=name,
                n_party=len(party),
                n_crossed=int(idx.size),
                unmatched=unmatched,
                crossed_break_rate=rate_x,
                party_break_rate=rate_p,
                crossed_mean_alignment=obs,
                random_mean_alignment=float(sims.mean()),
                permutation_p=pval,
                beta=beta,
                beta_se=se,
            )
        )
    return Calibration(
        case=fx.case,
        history_congress=fx.history_congress,
        party=fx.party,
        min_votes=min_votes,
        permutations=permutations,
        seed=seed,
        bodies=out,
    )
