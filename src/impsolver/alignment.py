# SPDX-FileCopyrightText: 2026 Justin Stanley
# SPDX-License-Identifier: MIT
"""Learn co-defection loadings from Voteview roll calls.

The encoding is "unsigned breaks". On each contested roll call, a member's entry is 1 if they voted
against their bloc's majority and 0 if they voted with it. Pearson correlations between members'
break series are shrunk toward their bloc-pair mean, projected to the nearest correlation matrix,
and factored into k loadings per member.

Several congresses can be pooled by passing the files of each. By default every roll call has the
same weight; with a half-life h (in congresses) a roll call from congress c has weight
0.5 ** ((latest - c) / h), which applies to the correlations and to every count written out.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import numpy.typing as npt

from .model import AlignedMember, Alignment, AlignmentBody

VOTEVIEW_PARTY = {100: "D", 200: "R", 328: "I"}
YEA = {1, 2, 3}
NAY = {4, 5, 6}
NOT_VOTING = 9
K = 5
KAPPA = 50.0
MIN_SHARED = 10
MIN_BLOC_VOTES = 5
MAX_NORM2 = 0.999
CHAMBERS = {"House": "house", "Senate": "senate"}
VOTEVIEW_CITATION = (
    "Lewis, Jeffrey B., Keith Poole, Howard Rosenthal, Adam Boche, Aaron Rudkin, and Luke Sonnet "
    "(2026). Voteview: Congressional Roll-Call Votes Database. https://voteview.com/"
)


def voteview_source(paths: list[Path], accessed: dt.date) -> str:
    """Citation line stored in generated files, as Voteview asks users to cite the dataset."""
    files = ", ".join(sorted(p.name for p in paths))
    return f"{VOTEVIEW_CITATION} Accessed {accessed.isoformat()}. Files: {files}."


FloatArr = npt.NDArray[np.float64]


# --------------------------------------------------------------------------- input


@dataclass
class VVMember:
    """One person in one chamber, merged across the rows a party switcher gets."""

    id: str
    name: str
    chamber: str
    state: str
    district: int | None
    party_code: int
    icpsrs: set[int] = field(default_factory=set)
    icpsr_party: dict[int, int] = field(default_factory=dict)
    congresses: set[int] = field(default_factory=set)

    @property
    def party(self) -> str:
        return party_letter(self.party_code)


def party_letter(code: int) -> str:
    return VOTEVIEW_PARTY.get(code, str(code))


def parse_caucus(specs: list[str]) -> dict[str, str]:
    """'328=D' or 'I=D' -> {'I': 'D'}: a party (code or letter) maps to a bloc."""
    out: dict[str, str] = {}
    for s in specs:
        if "=" not in s:
            raise ValueError(f"bad caucus mapping {s!r}; expected PARTY=BLOC")
        k, v = (x.strip() for x in s.split("=", 1))
        out[party_letter(int(k)) if k.isdigit() else k] = v
    return out


def parse_mapping(specs: list[str], what: str = "ID=BLOC") -> dict[str, str]:
    """'KEY=VALUE' strings to a dict; used for --member-caucus."""
    out: dict[str, str] = {}
    for s in specs:
        key, sep, value = s.partition("=")
        if not sep or not key.strip() or not value.strip():
            raise ValueError(f"bad mapping {s!r}; expected {what}")
        out[key.strip()] = value.strip()
    return out


def read_members(paths: list[Path]) -> list[VVMember]:
    """Read Voteview member CSVs. Rows for the same person in one chamber are merged.

    A party switcher gets one row per party; the row from the later congress (then the larger
    icpsr, which Voteview assigns on a switch) supplies the party.
    """
    merged: dict[tuple[str, str], VVMember] = {}
    rank: dict[tuple[str, str], tuple[int, int]] = {}
    for p in paths:
        with open(p, newline="", encoding="utf-8") as fh:
            for r in csv.DictReader(fh):
                chamber = CHAMBERS.get(r["chamber"])
                if chamber is None:
                    continue
                icpsr = int(float(r["icpsr"]))
                mid = r["bioguide_id"].strip() or f"icpsr:{icpsr}"
                cong = int(r["congress"])
                code = int(float(r["party_code"]))
                dist = r.get("district_code", "").strip()
                key = (chamber, mid)
                m = merged.get(key)
                if m is None:
                    m = VVMember(
                        mid,
                        r["bioname"].strip(),
                        chamber,
                        r["state_abbrev"].strip(),
                        int(float(dist)) if dist and chamber == "house" else None,
                        code,
                    )
                    merged[key] = m
                m.icpsrs.add(icpsr)
                m.icpsr_party[icpsr] = code
                m.congresses.add(cong)
                if (cong, icpsr) >= rank.get(key, (-1, -1)):
                    rank[key] = (cong, icpsr)
                    m.party_code = code
                    m.state = r["state_abbrev"].strip()
                    if chamber == "house" and dist:
                        m.district = int(float(dist))
    return list(merged.values())


def read_votes(paths: list[Path]) -> dict[str, dict[tuple[int, int], dict[int, int]]]:
    """chamber -> (congress, rollnumber) -> icpsr -> cast_code."""
    out: dict[str, dict[tuple[int, int], dict[int, int]]] = defaultdict(lambda: defaultdict(dict))
    for p in paths:
        with open(p, newline="", encoding="utf-8") as fh:
            for r in csv.DictReader(fh):
                chamber = CHAMBERS.get(r["chamber"])
                if chamber is None:
                    continue
                key = (int(r["congress"]), int(r["rollnumber"]))
                out[chamber][key][int(float(r["icpsr"]))] = int(float(r["cast_code"]))
    return out


def vote_matrix(
    members: list[VVMember], rolls: dict[tuple[int, int], dict[int, int]]
) -> tuple[FloatArr, list[tuple[int, int]], npt.NDArray[np.int64]]:
    """1 for yea, 0 for nay, NaN otherwise; rows follow ``members``.

    Also returns the icpsr that cast each cell (0 where nobody did), so that a party switcher's
    votes can be scored against the bloc they belonged to when they cast them.
    """
    keys = sorted(rolls)
    x = np.full((len(members), len(keys)), np.nan)
    caster = np.zeros((len(members), len(keys)), dtype=np.int64)
    owner = {ic: i for i, m in enumerate(members) for ic in m.icpsrs}
    for j, k in enumerate(keys):
        for ic, code in rolls[k].items():
            i = owner.get(ic)
            if i is None:
                continue
            if code in YEA:
                x[i, j] = 1.0
                caster[i, j] = ic
            elif code in NAY and np.isnan(x[i, j]):
                x[i, j] = 0.0
                caster[i, j] = ic
    return x, keys, caster


def member_bloc(m: VVMember, caucus: dict[str, str], member_caucus: dict[str, str]) -> str:
    """A member's current bloc: a per-member mapping beats the party-level one."""
    own = member_caucus.get(m.id)
    if own is not None:
        return m.party if own.lower() == "none" else own
    return caucus.get(m.party, m.party)


def cell_blocs(
    members: list[VVMember],
    caster: npt.NDArray[np.int64],
    caucus: dict[str, str],
    member_caucus: dict[str, str] | None = None,
) -> npt.NDArray[np.str_]:
    """Bloc label for every cell: the bloc of the party the casting icpsr belonged to.

    Votes cast under the member's current party use the member's current bloc, so a per-member
    caucus mapping applies to them; votes cast under an earlier party keep that party's bloc.
    """
    member_caucus = member_caucus or {}
    out = np.empty(caster.shape, dtype=object)
    for i, m in enumerate(members):
        final = member_bloc(m, caucus, member_caucus)
        out[i, :] = final
        for ic, code in m.icpsr_party.items():
            if code == m.party_code:
                continue
            party = party_letter(code)
            out[i, caster[i] == ic] = caucus.get(party, party)
    return out.astype(str)


def congress_weights(congresses: list[int], half_life: float | None) -> dict[int, float]:
    """Weight per congress: 1 for the latest, halving every ``half_life`` congresses before it."""
    if half_life is None:
        return {c: 1.0 for c in congresses}
    if half_life <= 0:
        raise ValueError(f"half-life must be positive, got {half_life}")
    latest = max(congresses)
    return {c: 0.5 ** ((latest - c) / half_life) for c in congresses}


def roll_weights(keys: list[tuple[int, int]], weights: dict[int, float] | None) -> FloatArr | None:
    """Per-roll-call weights in ``keys`` order, or None when every weight is 1."""
    if weights is None or all(w == 1.0 for w in weights.values()):
        return None
    return np.array([weights[c] for c, _ in keys], dtype=float)


def missed_votes(
    members: list[VVMember],
    rolls: dict[tuple[int, int], dict[int, int]],
    weights: dict[int, float] | None = None,
) -> list[tuple[int, int]]:
    """(n_missed, n_possible) per member over every roll call, not only contested ones.

    A roll call is possible for a member when Voteview lists any of their icpsrs on it (Voteview
    omits members who were not serving). It is missed when the only code recorded is 9 (not
    voting). Yea, nay and present (codes 1 to 8) all count as attending. With ``weights`` (per
    congress), each roll call counts its congress's weight and the totals are rounded.
    """
    out: list[tuple[int, int]] = []
    for m in members:
        missed = possible = 0.0
        for (cong, _), votes in rolls.items():
            codes = [votes[ic] for ic in m.icpsrs if ic in votes]
            if not codes:
                continue
            w = 1.0 if weights is None else weights[cong]
            possible += w
            if all(c == NOT_VOTING for c in codes):
                missed += w
        out.append((round(missed), round(possible)))
    return out


# ----------------------------------------------------------------------- the model


def bloc_rows(blocs: list[str]) -> dict[str, npt.NDArray[np.int64]]:
    out: dict[str, list[int]] = defaultdict(list)
    for i, b in enumerate(blocs):
        out[b].append(i)
    return {b: np.asarray(v, dtype=np.int64) for b, v in out.items()}


def _cells(
    blocs: list[str], shape: tuple[int, ...], cells: npt.NDArray[np.str_] | None
) -> npt.NDArray[np.str_]:
    if cells is not None:
        return cells
    return np.broadcast_to(np.asarray(blocs, dtype=str)[:, None], shape)


def _bloc_share(votes: FloatArr, mask: npt.NDArray[np.bool_]) -> tuple[FloatArr, FloatArr]:
    v = np.where(mask, votes, np.nan)
    cast = (~np.isnan(v)).sum(axis=0).astype(float)
    with np.errstate(invalid="ignore", divide="ignore"):
        share = np.where(cast > 0, np.nansum(v, axis=0) / np.maximum(cast, 1), np.nan)
    return share, cast


def contested_mask(
    votes: FloatArr,
    blocs: list[str],
    min_bloc_votes: int = MIN_BLOC_VOTES,
    cells: npt.NDArray[np.str_] | None = None,
) -> npt.NDArray[np.bool_]:
    """Roll calls where the two largest blocs take opposite majorities."""
    rows = bloc_rows(blocs)
    big = sorted(rows, key=lambda b: (-len(rows[b]), b))[:2]
    if len(big) < 2:
        return np.zeros(votes.shape[1], dtype=bool)
    lab = _cells(blocs, votes.shape, cells)
    shares = []
    for bloc in big:
        share, cast = _bloc_share(votes, lab == bloc)
        share[cast < min_bloc_votes] = np.nan
        shares.append(share)
    s1, s2 = shares
    out: npt.NDArray[np.bool_] = ((s1 > 0.5) & (s2 < 0.5)) | ((s1 < 0.5) & (s2 > 0.5))
    return out


def unsigned_breaks(
    votes: FloatArr, blocs: list[str], cells: npt.NDArray[np.str_] | None = None
) -> FloatArr:
    """1 where a member votes against their bloc's majority, 0 with it, NaN otherwise.

    With ``cells``, each vote is scored against the bloc its caster belonged to at the time.
    """
    out = np.full_like(votes, np.nan)
    lab = _cells(blocs, votes.shape, cells)
    for b in np.unique(lab):
        mask = lab == b
        share, _ = _bloc_share(votes, mask)
        position = np.where(share > 0.5, 1.0, np.where(share < 0.5, 0.0, np.nan))
        diff = np.abs(votes - position[None, :])
        out[mask] = diff[mask]
    return out


def pairwise_pearson(
    x: FloatArr, min_shared: int = MIN_SHARED, weights: FloatArr | None = None
) -> tuple[FloatArr, FloatArr]:
    """Pairwise-complete Pearson correlation of 0/1 rows. Returns (corr, n_shared).

    With column ``weights`` the moments are weighted and n_shared is the summed weight of the
    shared columns; ``min_shared`` still counts shared columns, unweighted.
    """
    present = (~np.isnan(x)).astype(float)
    filled = np.nan_to_num(x)
    if weights is None:
        n = present @ present.T
        sx = filled @ present.T
        sxy = filled @ filled.T
        shared = n
    else:
        n = (present * weights) @ present.T
        sx = (filled * weights) @ present.T
        sxy = (filled * weights) @ filled.T
        shared = present @ present.T
    with np.errstate(invalid="ignore", divide="ignore"):
        mi = sx / n
        mj = sx.T / n
        cov = sxy / n - mi * mj
        var_i = mi * (1 - mi)
        var_j = mj * (1 - mj)
        corr = cov / np.sqrt(var_i * var_j)
    enough = shared >= min_shared
    defined = enough & (var_i > 0) & (var_j > 0)
    corr = np.where(defined, np.clip(np.nan_to_num(corr), -1, 1), np.where(enough, 0.0, np.nan))
    return corr, n


def shrink(corr: FloatArr, n: FloatArr, blocs: list[str], kappa: float = KAPPA) -> FloatArr:
    """Shrink each pair toward the mean over defined pairs in its bloc-pair cell."""
    rows = bloc_rows(blocs)
    out = np.empty_like(corr)
    w = np.where(np.isnan(corr), 0.0, n / (n + kappa))
    off = ~np.eye(len(blocs), dtype=bool)
    for ra in rows.values():
        for rb in rows.values():
            cell = corr[np.ix_(ra, rb)]
            ok = ~np.isnan(cell) & off[np.ix_(ra, rb)]
            mean = float(cell[ok].mean()) if ok.any() else 0.0
            wc = w[np.ix_(ra, rb)]
            out[np.ix_(ra, rb)] = wc * np.nan_to_num(cell) + (1 - wc) * mean
    np.fill_diagonal(out, 1.0)
    return out


def nearest_correlation(c: FloatArr) -> FloatArr:
    """One-step projection: symmetrize, clip negative eigenvalues, rescale the diagonal to 1."""
    s = (c + c.T) / 2
    vals, vecs = np.linalg.eigh(s)
    psd = (vecs * np.clip(vals, 0, None)) @ vecs.T
    d = np.sqrt(np.clip(np.diag(psd), 1e-12, None))
    out: FloatArr = psd / np.outer(d, d)
    np.fill_diagonal(out, 1.0)
    return out


def cap_norm(rows: FloatArr, max_norm2: float = MAX_NORM2) -> FloatArr:
    n2 = (rows**2).sum(axis=1, keepdims=True)
    scale = np.where(n2 > max_norm2, np.sqrt(max_norm2 / np.maximum(n2, 1e-300)), 1.0)
    return rows * scale


def factor(c: FloatArr, k: int) -> FloatArr:
    vals, vecs = np.linalg.eigh(c)
    order = np.argsort(vals)[::-1][:k]
    load = vecs[:, order] * np.sqrt(np.clip(vals[order], 0, None))
    for j in range(load.shape[1]):
        if load[np.argmax(np.abs(load[:, j])), j] < 0:
            load[:, j] = -load[:, j]
    if load.shape[1] < k:
        load = np.hstack([load, np.zeros((load.shape[0], k - load.shape[1]))])
    return cap_norm(load)


@dataclass
class BodyFit:
    members: list[VVMember]
    blocs: list[str]
    breaks: FloatArr
    n_contested: int
    loadings: FloatArr
    has_history: npt.NDArray[np.bool_]
    weights: FloatArr | None = None  # per contested roll call; None = all 1


def fit_body(
    members: list[VVMember],
    votes: FloatArr,
    caucus: dict[str, str],
    k: int = K,
    kappa: float = KAPPA,
    min_shared: int = MIN_SHARED,
    caster: npt.NDArray[np.int64] | None = None,
    member_caucus: dict[str, str] | None = None,
    weights: FloatArr | None = None,
) -> BodyFit:
    """Fit one chamber. ``weights`` (one per roll call, column of ``votes``) are recency weights."""
    mc = member_caucus or {}
    blocs = [member_bloc(m, caucus, mc) for m in members]
    cells = cell_blocs(members, caster, caucus, mc) if caster is not None else None
    mask = contested_mask(votes, blocs, cells=cells)
    br = unsigned_breaks(votes[:, mask], blocs, cells[:, mask] if cells is not None else None)
    w = weights[mask] if weights is not None else None
    has = (~np.isnan(br)).sum(axis=1) > 0
    load = np.zeros((len(members), k))
    hist = np.flatnonzero(has)
    if hist.size:
        hb = [blocs[i] for i in hist]
        corr, n = pairwise_pearson(br[hist], min_shared, w)
        c = nearest_correlation(shrink(corr, n, hb, kappa))
        load[hist] = factor(c, min(k, hist.size))
    return BodyFit(members, blocs, br, int(mask.sum()), load, has, w)


def _weighted_counts(x: FloatArr, w: FloatArr | None) -> tuple[float, float]:
    """(breaks, votes) over the non-NaN cells of ``x``, each column counted with its weight."""
    cast = ~np.isnan(x)
    if w is None:
        return float(np.nansum(x)), float(cast.sum())
    wb = np.broadcast_to(w, x.shape)
    return float((np.nan_to_num(x) * wb).sum()), float((cast * wb).sum())


def to_alignment_body(
    fit: BodyFit, k: int, missed: list[tuple[int, int]] | None = None
) -> AlignmentBody:
    rows = bloc_rows(fit.blocs)
    means: dict[str, list[float]] = {}
    rates: dict[str, float] = {}
    for b, r in rows.items():
        h = r[fit.has_history[r]]
        mean = fit.loadings[h].mean(axis=0) if h.size else np.zeros(k)
        means[b] = [float(v) for v in cap_norm(mean[None, :])[0]]
        brk, cast = _weighted_counts(fit.breaks[r], fit.weights)
        rates[b] = brk / cast if cast else 0.0
    out: list[AlignedMember] = []
    for i, m in enumerate(fit.members):
        brk, cast = _weighted_counts(fit.breaks[i], fit.weights)
        nv = round(cast)
        hist = bool(fit.has_history[i])
        out.append(
            AlignedMember(
                id=m.id,
                name=m.name,
                party=m.party,
                bloc=fit.blocs[i],
                n_votes=nv,
                breaks=round(brk) if hist else None,
                loadings=[float(v) for v in fit.loadings[i]] if hist else means[fit.blocs[i]],
                n_missed=missed[i][0] if missed is not None else None,
                n_possible=missed[i][1] if missed is not None else None,
            )
        )
    return AlignmentBody(
        k=k,
        n_contested=fit.n_contested,
        members=out,
        bloc_mean_loadings=means,
        bloc_break_rate=rates,
    )


def build_alignment(
    vote_paths: list[Path],
    member_paths: list[Path],
    caucus: dict[str, str],
    k: int = K,
    kappa: float = KAPPA,
    min_shared: int = MIN_SHARED,
    member_caucus: dict[str, str] | None = None,
    accessed: dt.date | None = None,
    half_life: float | None = None,
) -> Alignment:
    """Fit every chamber in the vote files, pooling all the congresses they cover.

    ``half_life`` (in congresses) down-weights older congresses; None weights them equally.
    """
    members = read_members(member_paths)
    rolls = read_votes(vote_paths)
    congresses = sorted({c for rc in rolls.values() for c, _ in rc})
    if not congresses:
        raise ValueError("no House or Senate roll calls in the vote files")
    weights = congress_weights(congresses, half_life)
    bodies: dict[str, AlignmentBody] = {}
    for chamber, rc in sorted(rolls.items()):
        ms = sorted((m for m in members if m.chamber == chamber), key=lambda m: m.id)
        x, keys, caster = vote_matrix(ms, rc)
        keep = (~np.isnan(x)).any(axis=1)
        ms = [m for m, kk in zip(ms, keep, strict=True) if kk]
        fit = fit_body(
            ms,
            x[keep],
            caucus,
            k,
            kappa,
            min_shared,
            caster[keep],
            member_caucus,
            roll_weights(keys, weights),
        )
        missed = missed_votes(ms, rc, weights if half_life is not None else None)
        bodies[chamber] = to_alignment_body(fit, k, missed)
    return Alignment(
        schema_version=1,
        encoding="unsigned_breaks",
        source=voteview_source([*vote_paths, *member_paths], accessed or dt.date.today()),
        congresses=congresses,
        kappa=kappa,
        min_shared=min_shared,
        bodies=bodies,
        half_life=half_life,
    )


def write_alignment(a: Alignment, out: Path) -> None:
    data = a.model_dump(mode="json")
    if data.get("half_life") is None:
        data.pop("half_life", None)  # equal weighting: keep the original file layout
    out.write_text(json.dumps(data, indent=1) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="impsolver align", description=__doc__)
    ap.add_argument("--votes", action="append", required=True, type=Path)
    ap.add_argument("--members", action="append", required=True, type=Path)
    ap.add_argument("--caucus", action="append", default=[], help="PARTY=BLOC, e.g. 328=D")
    ap.add_argument(
        "--member-caucus",
        action="append",
        default=[],
        help="ID=BLOC ('none' = own party); beats --caucus",
    )
    ap.add_argument(
        "--accessed",
        type=dt.date.fromisoformat,
        default=None,
        help="date the Voteview files were downloaded (for the citation; default today)",
    )
    ap.add_argument(
        "--half-life",
        type=float,
        default=None,
        metavar="CONGRESSES",
        help="recency weight when pooling congresses: a roll call's weight halves every this many "
        "congresses before the latest (default: equal weight)",
    )
    ap.add_argument("--k", type=int, default=K)
    ap.add_argument("--kappa", type=float, default=KAPPA)
    ap.add_argument("--min-shared", type=int, default=MIN_SHARED)
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args(argv)
    try:
        mc = parse_mapping(a.member_caucus)
        al = build_alignment(
            a.votes,
            a.members,
            parse_caucus(a.caucus),
            a.k,
            a.kappa,
            a.min_shared,
            mc,
            a.accessed,
            a.half_life,
        )
    except (OSError, ValueError, KeyError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    write_alignment(al, a.out)
    weighting = "equal weight" if al.half_life is None else f"half-life {al.half_life:g}"
    print(f"congresses {', '.join(map(str, al.congresses))} ({weighting})")
    for name, b in al.bodies.items():
        print(
            f"{name}: {len(b.members)} members, {b.n_contested} contested roll calls, "
            f"break rates {', '.join(f'{k}={v:.3f}' for k, v in sorted(b.bloc_break_rate.items()))}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
