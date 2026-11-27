# SPDX-FileCopyrightText: 2026 Justin Stanley
# SPDX-License-Identifier: MIT
"""Synthetic roll-call data for alignment tests."""

from __future__ import annotations

import numpy as np

from impsolver.alignment import VVMember


def members(n_r: int, n_d: int, n_i: int = 0) -> list[VVMember]:
    out = [VVMember(f"R{i:03d}", f"R {i}", "house", "XX", i, 200, {1000 + i}) for i in range(n_r)]
    out += [VVMember(f"D{i:03d}", f"D {i}", "house", "XX", i, 100, {2000 + i}) for i in range(n_d)]
    out += [VVMember(f"I{i:03d}", f"I {i}", "house", "XX", i, 328, {3000 + i}) for i in range(n_i)]
    return out


def votes(
    ms: list[VVMember],
    n_votes: int,
    rng: np.random.Generator,
    groups: list[tuple[list[str], float]] = (),
    base_break: float = 0.05,
    never: set[str] = frozenset(),
    bloc_of: dict[str, str] | None = None,
) -> np.ndarray:
    """R votes yea and D votes nay on every roll call, except for breaks.

    ``groups`` lists (member ids, rate): each group breaks together on a shared random subset.
    """
    bloc_of = bloc_of or {}
    n = len(ms)
    idx = {m.id: i for i, m in enumerate(ms)}
    pos = np.array([1.0 if bloc_of.get(m.id, m.party) == "R" else 0.0 for m in ms])
    brk = rng.random((n, n_votes)) < base_break
    grouped: set[str] = set()
    for ids, rate in groups:
        shared = rng.random(n_votes) < rate
        for mid in ids:
            brk[idx[mid]] = shared
            grouped.add(mid)
    for mid in never:
        brk[idx[mid]] = False
    return np.abs(pos[:, None] - brk.astype(float))
