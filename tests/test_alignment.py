import json
from pathlib import Path

import numpy as np
import pytest

from impsolver.alignment import (
    build_alignment,
    contested_mask,
    fit_body,
    nearest_correlation,
    pairwise_pearson,
    parse_caucus,
    shrink,
    to_alignment_body,
    write_alignment,
)
from impsolver.loader import LoadError, load_alignment
from impsolver.model import Alignment, RuleSet
from impsolver.simulate import simulate
from tests import synth
from tests.conftest import make_comp, make_prep

RNG = np.random.default_rng(1)


def test_contested_mask() -> None:
    blocs = ["R"] * 6 + ["D"] * 6
    v = np.vstack([np.ones((6, 3)), np.zeros((6, 3))])
    v[:6, 1] = 0  # both blocs vote nay: not contested
    v[6:, 2] = np.nan  # D absent: too few votes
    assert contested_mask(v, blocs).tolist() == [True, False, False]


def test_caucus_mapping() -> None:
    assert parse_caucus(["328=D"]) == {"I": "D"}
    assert parse_caucus(["I=D"]) == {"I": "D"}
    ms = synth.members(20, 20, 1)
    v = synth.votes(ms, 80, RNG, bloc_of={"I000": "D"})
    fit = fit_body(ms, v, {"I": "D"})
    assert fit.blocs[-1] == "D"
    with pytest.raises(ValueError):
        parse_caucus(["328D"])


def test_planted_defector_bloc() -> None:
    ms = synth.members(60, 60)
    planted = [f"R{i:03d}" for i in range(6)]
    v = synth.votes(ms, 300, RNG, groups=[(planted, 0.3)])
    fit = fit_body(ms, v, {})
    F = fit.loadings
    inside = F[:6] @ F[:6].T
    other = F[10:60] @ F[10:60].T
    mean_in = (inside.sum() - np.trace(inside)) / 30
    mean_out = (other.sum() - np.trace(other)) / (50 * 49)
    assert mean_in > 0.5 and mean_in > mean_out + 0.4


def test_psd_and_unit_diagonal() -> None:
    c = np.array([[1, 0.9, -0.9], [0.9, 1, 0.9], [-0.9, 0.9, 1.0]])
    out = nearest_correlation(c)
    assert np.allclose(np.diag(out), 1)
    assert np.linalg.eigvalsh(out).min() > -1e-9


def test_shrinkage_toward_cell_mean() -> None:
    corr = np.array([[1, 0.8, 0.2], [0.8, 1, 0.2], [0.2, 0.2, 1]])
    n = np.full((3, 3), 10.0)
    out = shrink(corr, n, ["R", "R", "R"], kappa=50)
    cell_mean = (0.8 * 2 + 0.2 * 4) / 6
    w = 10 / 60
    assert out[0, 1] == pytest.approx(w * 0.8 + (1 - w) * cell_mean)
    assert out[0, 0] == 1.0


def test_never_breaker_zero_and_undefined_nan() -> None:
    x = np.array([[0.0] * 20, [1, 0] * 10, [np.nan] * 20])
    corr, _ = pairwise_pearson(x, min_shared=10)
    assert corr[0, 1] == 0.0
    assert np.isnan(corr[0, 2])


def _alignment(ms, v) -> Alignment:  # type: ignore[no-untyped-def]
    body = to_alignment_body(fit_body(ms, v, {}), 5)
    return Alignment(
        schema_version=1,
        encoding="unsigned_breaks",
        source="synthetic",
        congresses=[116],
        kappa=50,
        min_shared=10,
        bodies={"house": body},
    )


def test_round_trip(tmp_path: Path) -> None:
    ms = synth.members(20, 20)
    a = _alignment(ms, synth.votes(ms, 60, RNG))
    out = tmp_path / "a.json"
    write_alignment(a, out)
    assert load_alignment(out) == a


def test_missing_encoding_rejected(tmp_path: Path) -> None:
    ms = synth.members(10, 10)
    data = _alignment(ms, synth.votes(ms, 40, RNG)).model_dump(mode="json")
    del data["encoding"]
    p = tmp_path / "old.json"
    p.write_text(json.dumps(data))
    with pytest.raises(LoadError, match="encoding"):
        load_alignment(p)


def _aligned_prep(rules: RuleSet, weight: float, with_alignment: bool = True):  # type: ignore[no-untyped-def]
    ms = synth.members(60, 60)
    planted = [f"R{i:03d}" for i in range(10)]
    al = _alignment(ms, synth.votes(ms, 300, RNG, groups=[(planted, 0.3)]))
    house = [{"id": m.id, "name": m.name, "party": m.party} for m in ms]
    comp = make_comp(house, {"D": 60, "R": 40})
    return make_prep(
        rules,
        comp,
        al if with_alignment else None,
        alignment="x.json",
        alignment_weight=weight,
        party_priors={"D": {"*": 0.9}, "R": {"*": 0.2}},
        seed=5,
    )


def test_marginals_preserved_with_alignment(rules: RuleSet) -> None:
    prep = _aligned_prep(rules, 1.0)
    s = simulate(prep, draws=40_000).articles[0]
    h2 = next(g for g in s.gates if g.stage == "H2")
    assert s.gates and h2.pro_count.mean == pytest.approx(60 * 0.9 + 60 * 0.2, rel=0.015)


def test_weight_zero_matches_no_alignment(rules: RuleSet) -> None:
    a = simulate(_aligned_prep(rules, 0.0), draws=5000)
    b = simulate(_aligned_prep(rules, 0.0, with_alignment=False), draws=5000)
    assert a.articles == b.articles and not a.aligned


def test_real_alignment_files_have_encoding() -> None:
    root = Path(__file__).resolve().parents[1] / "alignment"
    for name in ("us-116.json", "us-119.json"):
        if (root / name).exists():
            a = load_alignment(root / name)
            assert a.encoding == "unsigned_breaks" and set(a.bodies) == {"house", "senate"}


def test_build_alignment_from_csv(tmp_path: Path) -> None:
    members = tmp_path / "m.csv"
    votes = tmp_path / "v.csv"
    rows = ["congress,chamber,icpsr,state_abbrev,district_code,party_code,bioname,bioguide_id"]
    for i in range(12):
        rows.append(f"119,House,{100 + i},XX,{i},{200 if i < 6 else 100},M {i},B{i:05d}")
    members.write_text("\n".join(rows) + "\n")
    vr = ["congress,chamber,rollnumber,icpsr,cast_code,prob"]
    for r in range(1, 31):
        for i in range(12):
            code = 1 if (i < 6) != (i == 0 and r % 2 == 0) else 6
            vr.append(f"119,House,{r},{100 + i},{code},99")
    votes.write_text("\n".join(vr) + "\n")
    a = build_alignment([votes], [members], {})
    hb = a.bodies["house"]
    assert hb.n_contested == 30
    b0 = next(m for m in hb.members if m.id == "B00000")
    assert b0.breaks == 15 and b0.n_votes == 30


def test_party_switcher_scored_against_bloc_at_time_of_vote(tmp_path: Path) -> None:
    """A member who switches R -> D mid-session is not charged with breaks for votes cast as R."""
    members = tmp_path / "m.csv"
    votes = tmp_path / "v.csv"
    rows = ["congress,chamber,icpsr,state_abbrev,district_code,party_code,bioname,bioguide_id"]
    for i in range(12):
        rows.append(f"119,House,{100 + i},XX,{i},{200 if i < 6 else 100},M {i},B{i:05d}")
    rows.append("119,House,900,XX,99,200,SWITCHER,S0000001")
    rows.append("119,House,901,XX,99,100,SWITCHER,S0000001")
    members.write_text("\n".join(rows) + "\n")
    vr = ["congress,chamber,rollnumber,icpsr,cast_code,prob"]
    for r in range(1, 41):
        for i in range(12):
            vr.append(f"119,House,{r},{100 + i},{1 if i < 6 else 6},99")
        # votes with R as an R (rolls 1-20), then with D as a D (rolls 21-40)
        vr.append(f"119,House,{r},{900 if r <= 20 else 901},{1 if r <= 20 else 6},99")
    votes.write_text("\n".join(vr) + "\n")
    a = build_alignment([votes], [members], {})
    sw = next(m for m in a.bodies["house"].members if m.id == "S0000001")
    assert sw.party == "D" and sw.bloc == "D"
    assert sw.breaks == 0 and sw.n_votes == 40
