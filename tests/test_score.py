# SPDX-FileCopyrightText: 2026 Justin Stanley
# SPDX-License-Identifier: MIT
import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from impsolver import score as S
from impsolver.alignment import fit_body, to_alignment_body, write_alignment
from impsolver.cli import main
from impsolver.loader import BUILTIN_FIXTURES, load_alignment, load_crossovers
from impsolver.model import Alignment, CrossoverFixture
from impsolver.priors import Propensity, adjust, propensities
from tests import synth

REPO = Path(__file__).resolve().parents[1]
GROUP_A = [f"R{i:03d}" for i in range(12)]
GROUP_B = [f"R{i:03d}" for i in range(12, 24)]
MS = synth.members(120, 60)
VOTES = synth.votes(MS, 300, np.random.default_rng(2), groups=[(GROUP_A, 0.15), (GROUP_B, 0.15)])


def _alignment(kappa: float = 50.0, congress: int = 116) -> Alignment:
    body = to_alignment_body(fit_body(MS, VOTES, {}, kappa=kappa), 5)
    return Alignment(
        schema_version=1,
        encoding="unsigned_breaks",
        source="synthetic",
        congresses=[congress],
        kappa=kappa,
        min_shared=10,
        bodies={"house": body},
    )


AL = _alignment()


def _fixture(case: str, crossed: list[str], congress: int = 116) -> CrossoverFixture:
    return CrossoverFixture.model_validate(
        {
            "schema_version": 1,
            "case": case,
            "history_congress": congress,
            "party": "R",
            "bodies": {
                "house": {
                    "crossed": [{"id": c, "name": c} for c in crossed]
                    + [{"id": None, "name": "not seated"}]
                }
            },
        }
    )


SMALL: dict[str, Any] = {
    "betas": [0.0, 1.0],
    "rhos": [0.0],
    "weights": [0.0, 1.0],
    "draws": 2000,
}


def test_log_ndtr_matches_erfc() -> None:
    xs = np.linspace(-35, 8, 300)
    got = S.log_ndtr(xs)
    want = np.array([math.log(0.5 * math.erfc(-x / math.sqrt(2))) for x in xs])
    assert np.allclose(got, want, rtol=1e-6, atol=1e-9)


def test_marginal_matches_defection_prior() -> None:
    ev = S.event_data(_fixture("a", GROUP_A), "house", {50.0: AL}, 100, 0.08)
    p = S.marginal_p(ev, 1.3)
    ab = AL.bodies["house"]
    rate = ab.bloc_break_rate["R"]
    m = next(m for m in ab.members if m.id == "R000")
    assert m.breaks is not None
    want = adjust(0.08, Propensity(m.breaks, m.n_votes, rate, "x"), 1.3, 20.0)
    assert p[0] == pytest.approx(want)
    assert ev.unmatched == ["not seated"] and ev.y.sum() == 12


def test_conditional_without_correlation_is_marginal() -> None:
    ev = S.event_data(_fixture("a", GROUP_A), "house", {50.0: AL}, 100, None)
    eps = S.make_draws(ev, 500, np.random.default_rng(0))
    p, ess = S.conditional_p(ev, eps, 1.0, 0.0, 0.0, 50.0)
    assert np.allclose(p, S.marginal_p(ev, 1.0), atol=1e-9) and ess > 100


def test_conditional_uses_alignment_and_bloc_swing() -> None:
    ev = S.event_data(_fixture("a", GROUP_A), "house", {50.0: AL}, 100, None)
    eps = S.make_draws(ev, 2000, np.random.default_rng(0))
    p0, _ = S.conditional_p(ev, eps, 1.0, 0.0, 0.0, 50.0)
    p1, ess = S.conditional_p(ev, eps, 1.0, 0.0, 1.0, 50.0)
    # Both groups break equally often; only alignment tells the crossing group apart.
    assert p1[:12].mean() > 0.8 > 0.3 > p0[:12].mean()
    assert p1[12:24].mean() < 0.05 < p0[12:24].mean()
    assert ess > 100
    pr, _ = S.conditional_p(ev, eps, 1.0, 0.6, 0.0, 50.0)
    assert not np.allclose(pr, p0)
    # Monte Carlo error across seeds is small
    p2, _ = S.conditional_p(ev, S.make_draws(ev, 2000, np.random.default_rng(1)), 1.0, 0, 1, 50)
    assert np.abs(p1 - p2).max() < 0.02


def test_sweep_one_event() -> None:
    s = S.sweep([_fixture("a", GROUP_A)], [AL], **SMALL)
    (c,) = s.chambers
    assert c.n_crossed == 12 and c.n_members == 120
    assert s.betas == [0.0, 1.0] and s.rhos == [0.0, 0.6] and s.kappas == [50.0]
    assert len(c.marginal) == 2 and c.best_marginal.beta == 1.0
    # 2 betas x 2 rhos x 2 weights
    assert len(c.conditional) == 8
    assert c.best_conditional is not None and c.best_conditional.weight == 1.0
    assert c.best_conditional.log_loss < c.best_marginal.log_loss
    assert c.default_conditional is not None
    assert (c.default_conditional.beta, c.default_conditional.rho) == (1.0, 0.6)
    assert c.default_conditional.weight == 1.0 and c.default_marginal.beta == 1.0
    assert not c.loeo_marginal and not c.loeo_conditional
    assert any("one event only" in n for n in s.notes)
    assert any("observed crossing share" in n for n in s.notes)


def test_sweep_brier_and_log_are_scores() -> None:
    s = S.sweep([_fixture("a", GROUP_A)], [AL], **SMALL)
    zero = next(q for q in s.chambers[0].marginal if q.beta == 0.0)
    b = 12 / 120
    assert zero.brier == pytest.approx(b * (1 - b))
    assert zero.log_loss == pytest.approx(-(b * math.log(b) + (1 - b) * math.log(1 - b)))


def test_leave_one_event_out() -> None:
    fxs = [_fixture("a", GROUP_A), _fixture("b", GROUP_B)]
    s = S.sweep(fxs, [AL], **SMALL)
    (c,) = s.chambers
    assert [e.case for e in c.events] == ["a", "b"] and c.n_crossed == 24
    assert [h.event for h in c.loeo_conditional] == ["a", "b"]
    for h in c.loeo_conditional:
        # Training on the other group still picks alignment, and it beats the default on the
        # held-out event (default weight 1 too, but rho 0.6).
        assert h.chosen.weight == 1.0
        assert h.log_loss <= h.default_log_loss + 1e-12
    assert len(c.loeo_marginal) == 2
    assert not any("one event only" in n for n in s.notes)


def test_kappa_grid_and_skips() -> None:
    fxs = [_fixture("a", GROUP_A), _fixture("old", GROUP_B, congress=110)]
    s = S.sweep(fxs, [AL, _alignment(10.0)], **SMALL)
    assert s.kappas == [10.0, 50.0] and s.events == ["a"]
    assert s.skipped == ["old: no alignment file covers congress 110"]
    c = s.chambers[0]
    # weight 0 ignores loadings, so it is scored once (at the default kappa)
    assert len(c.conditional) == 2 * 2 * (1 + 2)
    assert {q.kappa for q in c.conditional if q.weight == 1.0} == {10.0, 50.0}
    s2 = S.sweep([_fixture("a", GROUP_A)], [_alignment(10.0)], **SMALL)
    assert any("kappa 10 stands in" in n for n in s2.notes)


def test_kappa_only_on_some_events_is_dropped() -> None:
    fxs = [_fixture("a", GROUP_A), _fixture("b", GROUP_B, congress=117)]
    als = [AL, _alignment(10.0), _alignment(50.0, congress=117)]
    s = S.sweep(fxs, als, **SMALL)
    assert s.kappas == [50.0]
    assert any("left out" in n for n in s.notes)


def test_marginal_only_and_fixed_base_rate() -> None:
    s = S.sweep([_fixture("a", GROUP_A)], [AL], base_rate=0.2, conditional=False, **SMALL)
    c = s.chambers[0]
    assert c.conditional == [] and c.best_conditional is None and c.default_conditional is None
    assert c.events[0].base_rate == 0.2 and s.base_rate == 0.2
    assert not any("observed crossing share" in n for n in s.notes)


@pytest.mark.parametrize(
    ("kwargs", "msg"),
    [
        ({"base_rate": 0.6}, "base rate"),
        ({"rhos": [1.0]}, "rho"),
        ({"weights": [1.5]}, "weights"),
        ({"draws": 10}, "draws"),
    ],
)
def test_sweep_rejects_bad_settings(kwargs: dict[str, Any], msg: str) -> None:
    with pytest.raises(S.ScoreError, match=msg):
        S.sweep([_fixture("a", GROUP_A)], [AL], **kwargs)


def test_sweep_input_errors() -> None:
    fx = _fixture("a", GROUP_A)
    with pytest.raises(S.ScoreError, match="no crossover"):
        S.sweep([], [AL])
    with pytest.raises(S.ScoreError, match="no alignment files"):
        S.sweep([fx], [])
    with pytest.raises(S.ScoreError, match="covers any"):
        S.sweep([_fixture("x", GROUP_A, congress=99)], [AL])
    with pytest.raises(S.ScoreError, match="two alignment files"):
        S.sweep([fx], [AL, AL])
    with pytest.raises(S.ScoreError, match="both crossers"):
        S.sweep([_fixture("none", [])], [AL], **SMALL)
    with pytest.raises(S.ScoreError, match="lacks members"):
        bad = AL.model_copy(deep=True)
        bad.bodies["house"].members = bad.bodies["house"].members[1:]
        S.event_data(fx, "house", {50.0: AL, 10.0: bad}, 100, None)


def test_senate_body_missing_from_alignment_is_skipped() -> None:
    fx = CrossoverFixture.model_validate(
        {
            **_fixture("a", GROUP_A).model_dump(),
            "bodies": {
                "house": {"crossed": [{"id": c, "name": c} for c in GROUP_A]},
                "senate": {"crossed": [{"id": "S1", "name": "S1"}]},
            },
        }
    )
    s = S.sweep([fx], [AL], **SMALL)
    assert [c.body for c in s.chambers] == ["house"]
    assert s.skipped == ["a senate: alignment has no senate body"]


def _files(tmp_path: Path) -> tuple[str, str, str]:
    al = tmp_path / "al.json"
    write_alignment(AL, al)
    paths = []
    for case, group in (("a", GROUP_A), ("b", GROUP_B)):
        p = tmp_path / f"{case}.json"
        p.write_text(_fixture(case, group).model_dump_json(), encoding="utf-8")
        paths.append(str(p))
    return str(al), paths[0], paths[1]


def test_cli_score_text(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    al, a, b = _files(tmp_path)
    args = ["score", a, b, "--alignment", al, "--beta", "0,1", "--rho", "0", "--weight", "0,1"]
    rc = main([*args, "--draws", "1000", "--top", "3"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "house: 2 event(s), 240 members, 24 crossed" in out
    assert "beta  1.00" in out and "<- default" in out
    assert "conditional P(cross | other members), top 3 of 8" in out
    assert "held out a (conditional): chose beta" in out
    assert "a unmatched: not seated" in out
    assert "does not change any default" in out


def test_cli_score_json(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    al, a, _ = _files(tmp_path)
    rc = main(["--format", "json", "score", a, "--alignment", al, "--marginal-only"])
    d = json.loads(capsys.readouterr().out)
    assert rc == 0 and d["chambers"][0]["conditional"] == []
    assert d["betas"] == list(S.DEFAULT_BETAS)


def test_cli_score_errors(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    al, a, _ = _files(tmp_path)
    assert main(["score", a, "--alignment", al, "--rho", "1"]) == 2
    assert "rho" in capsys.readouterr().err
    with pytest.raises(SystemExit):
        main(["score", a, "--alignment", al, "--beta", "x"])


def test_render_flags_low_effective_draws() -> None:
    from impsolver.cli import _scored, _settings

    q = S.ScorePoint(beta=1, rho=0.6, weight=1, kappa=50, brier=0.1, log_loss=0.3)
    assert _settings(q) == "beta 1, rho 0.6, weight 1, kappa 50"
    assert "low effective" not in _scored(q)
    assert "low effective" in _scored(q.model_copy(update={"min_effective_draws": 5.0}))
    assert _settings(q.model_copy(update={"weight": 0.0})) == "beta 1, rho 0.6, weight 0"


def test_real_2021_sweep() -> None:
    al = REPO / "alignment" / "us-116.json"
    if not al.exists():
        pytest.skip("alignment/us-116.json not generated (needs Voteview data)")
    fx = load_crossovers(BUILTIN_FIXTURES / "members" / "trump-2021-crossovers.yaml")
    s = S.sweep([fx], [load_alignment(al)], conditional=False)
    house, senate = s.chambers
    # 41 House and 8 Senate Republicans of the 116th cast no vote on the 2021 event.
    assert (house.n_members, house.n_crossed) == (160, 8)
    assert (senate.n_members, senate.n_crossed) == (46, 7)
    assert house.events[0].n_not_voting == 41 and senate.events[0].n_not_voting == 8
    assert house.best_marginal.beta == 1.25 and senate.best_marginal.beta == 1.0
    zero = next(q for q in house.marginal if q.beta == 0.0)
    assert house.best_marginal.log_loss < zero.log_loss


def _with_not_voting(fx: CrossoverFixture, ids: list[str]) -> CrossoverFixture:
    d = fx.model_dump()
    d["bodies"]["house"]["not_voting"] = [{"id": i, "name": i} for i in ids]
    return CrossoverFixture.model_validate(d)


def test_not_voting_members_are_left_out() -> None:
    absent = GROUP_B[:5] + ["R100", "NOPE"]  # "NOPE" is not in the alignment
    fx = _with_not_voting(_fixture("a", GROUP_A), absent)
    ev = S.event_data(fx, "house", {50.0: AL}, 100, None)
    assert ev.y.size == 120 - 6 and ev.excluded == 6 and ev.has_voters
    assert ev.base_rate == pytest.approx(12 / 114)
    s = S.sweep([fx], [AL], **SMALL)
    assert s.chambers[0].events[0].n_not_voting == 6 and s.chambers[0].n_members == 114
    plain = S.sweep([_fixture("a", GROUP_A)], [AL], **SMALL)
    assert plain.chambers[0].events[0].n_not_voting is None
    everyone = S.sweep([_with_not_voting(_fixture("a", GROUP_A), [])], [AL], **SMALL)
    assert everyone.chambers[0].events[0].n_not_voting == 0


def test_cli_reports_not_voting(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    al, a, _ = _files(tmp_path)
    b = tmp_path / "b.json"
    fx = _with_not_voting(_fixture("b", GROUP_A), GROUP_B[:3])
    b.write_text(fx.model_dump_json(), encoding="utf-8")
    assert main(["score", a, str(b), "--alignment", al, "--marginal-only"]) == 0
    out = capsys.readouterr().out
    assert "a: fixture lists no non-voters" in out
    assert "b: 3 members left out as not voting" in out


def test_bloc_rate_is_per_member() -> None:
    al = AL.model_copy(deep=True)
    ab = al.bodies["house"]
    for m in ab.members:
        if m.id in GROUP_B:
            m.bloc = "X"
    ab.bloc_break_rate["X"] = 0.2
    ev = S.event_data(_fixture("a", GROUP_A), "house", {50.0: al}, 100, 0.08)
    p = S.marginal_p(ev, 1.3)
    props = propensities(al, "house")
    ids = [m.id for m in ab.members if m.party == "R" and m.n_votes >= 100]
    for i, mid in enumerate(ids):
        assert p[i] == pytest.approx(adjust(0.08, props[mid], 1.3, 20.0))
    # A bloc with no break rate is left out, as in priors.propensities.
    del ab.bloc_break_rate["X"]
    ev2 = S.event_data(_fixture("a", GROUP_A), "house", {50.0: al}, 100, 0.08)
    assert ev2.y.size == 120 - len(GROUP_B)


def test_unscorable_event_is_skipped() -> None:
    s = S.sweep([_fixture("a", GROUP_A), _fixture("none", [])], [AL], **SMALL)
    assert s.events == ["a", "none"] and [e.case for e in s.chambers[0].events] == ["a"]
    assert s.skipped == ["none house: needs both crossers and non-crossers"]
    assert any(n.startswith("house: one scored event only") for n in s.notes)
    assert not any(n.startswith("one event only") for n in s.notes)
    with pytest.raises(S.ScoreError, match="no event could be scored"):
        S.sweep([_fixture("none", [])], [AL], **SMALL)


def test_best_skips_low_effective_draws() -> None:
    lo = S.ScorePoint(beta=2, rho=0.9, weight=1, brier=0.01, log_loss=0.05, min_effective_draws=3)
    hi = S.ScorePoint(beta=1, rho=0, weight=0, brier=0.02, log_loss=0.1, min_effective_draws=900)
    assert S._best([lo, hi]) == hi and S._best([lo, hi], "brier") == hi
    assert S._best([lo]) == lo  # nothing reliable: fall back to the full grid
    sq = np.array([0.0])
    tables: list[S.Table] = [
        {(2.0,): (sq, np.array([0.01]), 3.0), (1.0,): (sq, np.array([0.2]), 500.0)},
        {(2.0,): (sq, np.array([0.01]), 3.0), (1.0,): (sq, np.array([0.3]), 500.0)},
    ]
    _, _, held = S._sweep_table(tables, (1.0,), ["a", "b"])
    assert [h.chosen.beta for h in held] == [1.0, 1.0]


def test_render_flags_low_draws_on_best_by_brier() -> None:
    from impsolver.cli import render_sweep

    s = S.sweep([_fixture("a", GROUP_A)], [AL], **SMALL)
    c = s.chambers[0]
    assert c.best_conditional_brier is not None
    c.best_conditional_brier.min_effective_draws = 2.0
    c.min_effective_draws = 2.0
    out = render_sweep(s, 3)
    line = next(x for x in out.splitlines() if "best by Brier" in x)
    assert "low effective draws" in line
    assert "best settings skip points below 100" in out


def test_weights_are_reported_per_chamber() -> None:
    s = S.sweep([_fixture("a", GROUP_A)], [AL], **{**SMALL, "weights": [0.0]})
    (c,) = s.chambers
    # The house grid is the request plus the house default; the top level lists only the request.
    assert s.weights == [0.0]
    assert c.weights == sorted({0.0, S.ALIGNMENT_CHAMBER_DEFAULT[c.body]})
    assert {p.weight for p in c.conditional} == set(c.weights)
