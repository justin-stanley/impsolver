# SPDX-FileCopyrightText: 2026 Justin Stanley
# SPDX-License-Identifier: MIT
"""Pooling several congresses in `impsolver align`, with and without a recency weight."""

import json
from pathlib import Path

import numpy as np
import pytest

from impsolver.alignment import (
    build_alignment,
    congress_weights,
    main,
    missed_votes,
    pairwise_pearson,
    read_members,
    read_votes,
    roll_weights,
    write_alignment,
)
from impsolver.loader import load_alignment
from impsolver.model import AlignedMember, Alignment

MEMBER_HEADER = "congress,chamber,icpsr,state_abbrev,district_code,party_code,bioname,bioguide_id"
VOTE_HEADER = "congress,chamber,rollnumber,icpsr,cast_code,prob"
N = 12  # members per congress: 6 R (B00000-B00005), 6 D (B00006-B00011)


def _congress(
    tmp: Path,
    congress: int,
    rolls: int,
    breaker: str | None = None,
    group: tuple[str, ...] = (),
    absent: str | None = None,
    every: dict[str, int] | None = None,
) -> tuple[Path, Path]:
    """Write one congress: R votes yea and D nay on every roll call.

    ``breaker`` breaks on even roll calls; ``group`` breaks together on roll calls divisible by 3;
    ``every`` maps a member to n, breaking on roll calls divisible by n; ``absent`` is recorded as
    not voting (code 9) on every roll call.
    """
    every = every or {}
    mp = tmp / f"H{congress}_members.csv"
    vp = tmp / f"H{congress}_votes.csv"
    rows = [MEMBER_HEADER]
    for i in range(N):
        party = 200 if i < 6 else 100
        rows.append(f"{congress},House,{100 + i},XX,{i},{party},M {i},B{i:05d}")
    mp.write_text("\n".join(rows) + "\n")
    vr = [VOTE_HEADER]
    for r in range(1, rolls + 1):
        for i in range(N):
            mid = f"B{i:05d}"
            yea = i < 6
            if (
                (mid == breaker and r % 2 == 0)
                or (mid in group and r % 3 == 0)
                or (mid in every and r % every[mid] == 0)
            ):
                yea = not yea
            code = 9 if mid == absent else (1 if yea else 6)
            vr.append(f"{congress},House,{r},{100 + i},{code},99")
    vp.write_text("\n".join(vr) + "\n")
    return vp, mp


def _member(a: Alignment, mid: str) -> AlignedMember:
    return next(m for m in a.bodies["house"].members if m.id == mid)


def test_congress_weights() -> None:
    assert congress_weights([116, 117, 118], None) == {116: 1.0, 117: 1.0, 118: 1.0}
    assert congress_weights([116, 117, 118], 1) == {116: 0.25, 117: 0.5, 118: 1.0}
    assert congress_weights([116, 118], 2) == {116: 0.5, 118: 1.0}
    with pytest.raises(ValueError, match="positive"):
        congress_weights([116], 0)
    assert roll_weights([(116, 1)], {116: 1.0}) is None
    assert roll_weights([(116, 1), (117, 1)], {116: 0.5, 117: 1.0}).tolist() == [0.5, 1.0]  # type: ignore[union-attr]


def test_pooled_counts_add_across_congresses(tmp_path: Path) -> None:
    v1, m1 = _congress(tmp_path, 116, 30, breaker="B00000")
    v2, m2 = _congress(tmp_path, 117, 20)
    a = build_alignment([v1, v2], [m1, m2], {})
    assert a.congresses == [116, 117] and a.half_life is None
    hb = a.bodies["house"]
    assert hb.n_contested == 50 and len(hb.members) == N  # merged by bioguide id
    b0 = _member(a, "B00000")
    assert b0.n_votes == 50 and b0.breaks == 15
    assert hb.bloc_break_rate["R"] == pytest.approx(15 / 300)
    assert "H116_votes.csv" in a.source and "H117_members.csv" in a.source


def test_equal_weight_pool_matches_one_file(tmp_path: Path) -> None:
    """Pooling two files equals one file holding both congresses' rows."""
    v1, m1 = _congress(tmp_path, 116, 30, breaker="B00000", group=("B00001", "B00002"))
    v2, m2 = _congress(tmp_path, 117, 30, group=("B00000", "B00003"))
    both_v, both_m = tmp_path / "v.csv", tmp_path / "m.csv"
    both_v.write_text(v1.read_text() + "".join(v2.read_text().splitlines(True)[1:]))
    both_m.write_text(m1.read_text() + "".join(m2.read_text().splitlines(True)[1:]))
    pooled = build_alignment([v1, v2], [m1, m2], {}).bodies
    single = build_alignment([both_v], [both_m], {}).bodies
    assert pooled == single


def test_half_life_downweights_older_congress(tmp_path: Path) -> None:
    v1, m1 = _congress(tmp_path, 116, 40, breaker="B00000")  # 20 breaks in the older congress
    v2, m2 = _congress(tmp_path, 117, 40)
    a = build_alignment([v1, v2], [m1, m2], {}, half_life=1)
    assert a.half_life == 1
    b0 = _member(a, "B00000")
    assert b0.n_votes == 60 and b0.breaks == 10  # 40 * 0.5 + 40 and 20 * 0.5
    assert a.bodies["house"].bloc_break_rate["R"] == pytest.approx(10 / 360)
    # The same data with the congresses swapped: the breaks are now recent and keep full weight.
    v3, m3 = _congress(tmp_path, 118, 40, breaker="B00000")
    b = build_alignment([v2, v3], [m2, m3], {}, half_life=1)
    assert _member(b, "B00000").breaks == 20 and _member(b, "B00000").n_votes == 60


def test_half_life_weights_attendance(tmp_path: Path) -> None:
    v1, m1 = _congress(tmp_path, 116, 40, absent="B00007")
    v2, m2 = _congress(tmp_path, 117, 40)
    flat = _member(build_alignment([v1, v2], [m1, m2], {}), "B00007")
    assert (flat.n_missed, flat.n_possible) == (40, 80)
    rec = _member(build_alignment([v1, v2], [m1, m2], {}, half_life=1), "B00007")
    assert (rec.n_missed, rec.n_possible) == (20, 60)
    members = [m for m in read_members([m1, m2]) if m.id == "B00007"]
    rolls = read_votes([v1, v2])["house"]
    assert missed_votes(members, rolls, {116: 0.25, 117: 1.0}) == [(10, 50)]


def test_recent_co_breakers_dominate_with_short_half_life(tmp_path: Path) -> None:
    """Pair A co-breaks in the old congress and pair B in the recent one; otherwise apart."""
    old = ("B00000", "B00001")
    new = ("B00002", "B00003")
    apart = {"B00000": 4, "B00001": 5}
    v1, m1 = _congress(tmp_path, 116, 60, group=old, every={"B00002": 4, "B00003": 5})
    v2, m2 = _congress(tmp_path, 118, 60, group=new, every=apart)

    def pair(a: Alignment, ids: tuple[str, str]) -> float:
        x, y = (np.array(_member(a, i).loadings) for i in ids)
        return float(x @ y)

    flat = build_alignment([v1, v2], [m1, m2], {})
    short = build_alignment([v1, v2], [m1, m2], {}, half_life=0.25)
    assert pair(flat, old) == pytest.approx(pair(flat, new), abs=0.05)
    assert pair(short, new) > pair(short, old) + 0.1


def test_weighted_pearson_equals_duplicated_columns() -> None:
    rng = np.random.default_rng(3)
    x = (rng.random((5, 30)) < 0.4).astype(float)
    x[0, :4] = np.nan
    w = np.ones(30)
    w[:10] = 2.0
    corr_w, n_w = pairwise_pearson(x, 10, w)
    dup = np.hstack([x, x[:, :10]])
    corr_d, n_d = pairwise_pearson(dup, 10)
    assert np.allclose(corr_w, corr_d) and np.allclose(n_w, n_d)
    ones_c, ones_n = pairwise_pearson(x, 10, np.ones(30))
    plain_c, plain_n = pairwise_pearson(x, 10)
    assert np.allclose(ones_c, plain_c) and np.allclose(ones_n, plain_n)


def test_min_shared_counts_roll_calls_not_weight() -> None:
    x = np.array([[1.0, 0.0] * 6, [1.0, 0.0] * 6])
    corr, n = pairwise_pearson(x, 10, np.full(12, 0.1))
    assert corr[0, 1] == pytest.approx(1.0)  # 12 shared roll calls >= 10, though weight is 1.2
    assert n[0, 1] == pytest.approx(1.2)


def test_file_layout_and_round_trip(tmp_path: Path) -> None:
    v1, m1 = _congress(tmp_path, 116, 30, breaker="B00000")
    v2, m2 = _congress(tmp_path, 117, 30)
    flat = build_alignment([v1, v2], [m1, m2], {})
    out = tmp_path / "flat.json"
    write_alignment(flat, out)
    assert "half_life" not in json.loads(out.read_text())
    assert load_alignment(out) == flat
    rec = build_alignment([v1, v2], [m1, m2], {}, half_life=2)
    out2 = tmp_path / "rec.json"
    write_alignment(rec, out2)
    assert json.loads(out2.read_text())["half_life"] == 2
    assert load_alignment(out2) == rec


def test_no_roll_calls_is_an_error(tmp_path: Path) -> None:
    v = tmp_path / "v.csv"
    v.write_text(VOTE_HEADER + "\n")
    _, m = _congress(tmp_path, 116, 1)
    with pytest.raises(ValueError, match="no House or Senate roll calls"):
        build_alignment([v], [m], {})


def test_cli_half_life(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    v1, m1 = _congress(tmp_path, 116, 30, breaker="B00000")
    v2, m2 = _congress(tmp_path, 117, 30)
    out = tmp_path / "a.json"
    args = ["--votes", str(v1), "--votes", str(v2), "--members", str(m1), "--members", str(m2)]
    assert main([*args, "--half-life", "1", "--accessed", "2026-11-27", "--out", str(out)]) == 0
    printed = capsys.readouterr().out
    assert "congresses 116, 117 (half-life 1)" in printed
    assert load_alignment(out).half_life == 1
    assert main([*args, "--out", str(out)]) == 0
    assert "(equal weight)" in capsys.readouterr().out
    assert main([*args, "--half-life", "0", "--out", str(out)]) == 2
    assert "half-life must be positive" in capsys.readouterr().err


def test_committed_pooled_file() -> None:
    path = Path(__file__).resolve().parents[1] / "alignment" / "us-116-118.json"
    if not path.exists():
        pytest.skip("no pooled alignment file")
    a = load_alignment(path)
    assert a.congresses == [116, 117, 118] and a.half_life is None
    assert set(a.bodies) == {"house", "senate"}
    for c in (116, 117, 118):
        assert f"H{c}_votes.csv" in a.source and f"S{c}_members.csv" in a.source
