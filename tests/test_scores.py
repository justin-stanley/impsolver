# SPDX-FileCopyrightText: 2026 Justin Stanley
# SPDX-License-Identifier: MIT
"""Score prior hook. Every score here is synthetic; impsolver ships no third-party scores."""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from impsolver.loader import load_composition
from impsolver.members import logit, sigmoid
from impsolver.model import AlignedMember, Alignment, AlignmentBody, RuleSet
from impsolver.prepare import prepare_objects
from impsolver.priors import apply_score_prior
from impsolver.roster import build_roster, dump_composition
from impsolver.roster import main as roster_main
from impsolver.scores import ScoreError, read_member_scores
from impsolver.simulate import sampled_preps, simulate
from tests.conftest import make_comp, make_scenario
from tests.test_roster import files  # noqa: F401  (fixture)

LOAD = [0.0, 0.0]
SRC = "Synthetic test scores v0 (not real data)"


def _csv(tmp_path: Path, rows: list[str], header: str = "id,score,source") -> Path:
    p = tmp_path / "scores.csv"
    p.write_text("\n".join([header, *rows]) + "\n", encoding="utf-8")
    return p


def test_standardizes_within_each_source(tmp_path: Path) -> None:
    p = _csv(
        tmp_path,
        ["A,1,src1", "B,3,src1", "C,10,src2", "D,20,src2", "E,30,src2"],
    )
    scores, stats = read_member_scores(p)
    assert scores["A"].z == pytest.approx(-1.0) and scores["B"].z == pytest.approx(1.0)
    sd2 = math.sqrt(200 / 3)
    assert scores["E"].z == pytest.approx(10 / sd2) and scores["D"].z == pytest.approx(0.0)
    assert scores["C"].raw == 10.0 and scores["C"].source == "src2"
    assert [(s.source, s.n) for s in stats] == [("src1", 2), ("src2", 3)]


def test_accepts_byte_order_mark(tmp_path: Path) -> None:
    p = tmp_path / "bom.csv"
    p.write_bytes(b"\xef\xbb\xbfid,score,source\nA,1,s\nB,3,s\n")
    scores, _ = read_member_scores(p)
    assert scores["B"].z == pytest.approx(1.0)


@pytest.mark.parametrize(
    ("rows", "header", "msg"),
    [
        (["A,1,s", "B,2,s"], "id,score", "header"),
        (["A,x,s", "B,2,s"], "id,score,source", "not a number"),
        (["A,nan,s", "B,2,s"], "id,score,source", "not finite"),
        (["A,1,s", "A,2,s"], "id,score,source", "duplicate"),
        (["A,1,", "B,2,s"], "id,score,source", "empty source"),
        ([",1,s", "B,2,s"], "id,score,source", "empty id"),
        (["A,1,s"], "id,score,source", "at least 2"),
        (["A,1,s", "B,1,s"], "id,score,source", "do not vary"),
    ],
)
def test_rejects_bad_files(tmp_path: Path, rows: list[str], header: str, msg: str) -> None:
    with pytest.raises(ScoreError, match=msg):
        read_member_scores(_csv(tmp_path, rows, header))


@pytest.mark.parametrize(
    "rows",
    [
        ["A,1,Doe J., State scores v2, https://x.org", "B,2,s"],  # unquoted commas
        ["A,1", "B,2,s"],  # too few fields
    ],
)
def test_rejects_rows_with_wrong_field_count(tmp_path: Path, rows: list[str]) -> None:
    with pytest.raises(ScoreError, match=r"scores.csv:2: expected 3 fields.*double quotes"):
        read_member_scores(_csv(tmp_path, rows))


def test_quoted_citation_keeps_commas_and_separate_sources(tmp_path: Path) -> None:
    v1, v2 = "Doe J., State scores, v1, https://x.org", "Doe J., State scores, v2, https://x.org"
    rows = [f'A,1,"{v1}"', f'B,3,"{v1}"', f'C,10,"{v2}"', f'D,30,"{v2}"']
    scores, stats = read_member_scores(_csv(tmp_path, rows))
    assert scores["A"].source == v1 and scores["C"].source == v2
    assert [(st.source, st.n, st.mean) for st in stats] == [(v1, 2, 2.0), (v2, 2, 20.0)]
    assert scores["C"].z == pytest.approx(-1.0)


def test_roster_attaches_scores(tmp_path: Path, files: tuple[Path, Path]) -> None:  # noqa: F811
    m, v = files
    # The file covers a reference set wider than the current seat holders.
    p = _csv(tmp_path, [f"H000008,2,{SRC}", f"X000001,0,{SRC}", f"X000002,-2,{SRC}"])
    rep = build_roster([m], [v], caucus={"I": "D"}, member_scores=p)
    house = {x.id: x for x in rep.comp.bodies["house"].roster}
    sd = math.sqrt(8 / 3)
    assert house["H000008"].score == pytest.approx(2 / sd, abs=1e-6)
    assert house["H000008"].score_source == SRC
    assert house["A000001"].score is None
    assert any(SRC in ln and "1 seat holders scored" in ln for ln in rep.lines)
    text = dump_composition(rep)
    assert "score_source" in text and SRC in text.split("schema_version")[0]
    out = tmp_path / "comp.yaml"
    out.write_text(text)
    assert load_composition(out).bodies["house"].roster[-1].score is not None


def test_roster_cli_flag_and_no_match(tmp_path: Path, files: tuple[Path, Path]) -> None:  # noqa: F811
    m, v = files
    good = _csv(tmp_path, [f"H000008,1,{SRC}", f"X000001,0,{SRC}"])
    out = tmp_path / "c.yaml"
    args = ["--members", str(m), "--votes", str(v), "--out", str(out)]
    assert roster_main([*args, "--member-scores", str(good)]) == 0
    assert "score: " in out.read_text()
    bad = tmp_path / "bad.csv"
    bad.write_text(f"id,score,source\nX000001,1,{SRC}\nX000002,0,{SRC}\n")
    assert roster_main([*args, "--member-scores", str(bad)]) == 2


def _alignment(ids: dict[str, int], senate: dict[str, int] | None = None) -> Alignment:
    def body(ids: dict[str, int]) -> AlignmentBody:
        ms = [
            AlignedMember(id=i, name=i, party="R", bloc="R", n_votes=n, breaks=0, loadings=LOAD)
            for i, n in ids.items()
        ]
        return AlignmentBody(
            k=2,
            n_contested=200,
            members=ms,
            bloc_mean_loadings={"R": LOAD},
            bloc_break_rate={"R": 0.05},
        )

    bodies = {"house": body(ids)}
    if senate is not None:
        bodies["senate"] = body(senate)
    return Alignment(
        schema_version=1,
        encoding="unsigned_breaks",
        source="t",
        congresses=[116],
        kappa=50,
        min_shared=10,
        bodies=bodies,
    )


def _house() -> list[dict[str, Any]]:
    def m(i: str, party: str = "R", **kw: Any) -> dict[str, Any]:
        return {"id": i, "name": i, "party": party, **kw}

    return [
        m("NEW", score=1.5, score_source=SRC),
        m("VET", score=1.5, score_source=SRC),  # has history in the alignment file
        m("ZERO", score=-1.0, score_source=SRC),  # in the alignment file but never voted
        m("OWN", score=1.5, p_pro={"*": 0.3}),
        m("OVR", score=1.5),
        m("DEM", party="D", score=1.5),
        m("NOSCORE"),
    ]


def test_score_prior_moves_only_new_scored_members(rules: RuleSet) -> None:
    scen = make_scenario(
        party_priors={"R": {"*": 0.1}, "D": {"*": 0.9}},
        alignment="a.json",
        overrides={"OVR": {"*": 0.5}},
        score_prior={"R": {"slope": 0.4, "intercept": -0.2}},
    )
    align = _alignment({"VET": 200, "ZERO": 0})
    comp, n = apply_score_prior(scen, make_comp(_house(), {"R": 1}), rules, align)
    house = {m.id: m for m in comp.bodies["house"].roster}
    assert n == 2
    assert house["NEW"].p_pro["H2"] == pytest.approx(sigmoid(logit(0.1) - 0.2 + 0.4 * 1.5))
    assert house["ZERO"].p_pro["H2"] == pytest.approx(sigmoid(logit(0.1) - 0.2 - 0.4))
    assert house["NEW"].p_source == "score_prior"
    assert set(house["NEW"].p_pro) == {s.id for s in rules.stages if s.chamber == "house"}
    for mid in ("VET", "OVR", "DEM", "NOSCORE"):
        assert house[mid].p_pro == {}
    assert house["OWN"].p_pro == {"*": 0.3}


def test_score_prior_needs_alignment_and_default_is_unchanged(rules: RuleSet) -> None:
    with pytest.raises(ValidationError, match="score_prior needs an alignment"):
        make_scenario(score_prior={"R": {"slope": 1.0}})
    comp = make_comp(_house(), {"R": 1})
    align = _alignment({"VET": 200})
    plain = prepare_objects(rules, comp, make_scenario(alignment="a.json"), align)
    assert plain.comp == comp


def test_prepare_applies_and_resamples(rules: RuleSet) -> None:
    scen = make_scenario(
        party_priors={"R": {"*": {"low": 0.1, "high": 0.3}}, "D": {"*": 0.9}},
        alignment="a.json",
        score_prior={"R": {"slope": 1.0}},
    )
    prep = prepare_objects(rules, make_comp(_house(), {"R": 1}), scen, _alignment({"VET": 200}))
    new = {m.id: m for m in prep.comp.bodies["house"].roster}["NEW"]
    assert new.p_pro["H1"] == pytest.approx(sigmoid(logit(0.2) + 1.5))
    resampled = prep.with_scenario(scen.model_copy(update={"party_priors": {"R": {"*": 0.05}}}))
    new2 = {m.id: m for m in resampled.comp.bodies["house"].roster}["NEW"]
    assert new2.p_pro["H1"] == pytest.approx(sigmoid(logit(0.05) + 1.5))


def test_score_prior_warnings(rules: RuleSet) -> None:
    scen = make_scenario(alignment="a.json", score_prior={"X": {"slope": 1.0}})
    prep = prepare_objects(rules, make_comp({"R": 3}, {"R": 1}), scen, _alignment({}))
    assert any("score_prior bloc X matches no scored member" in w for w in prep.warnings)
    assert any("score_prior moved no member" in w for w in prep.warnings)
    with pytest.raises(ValueError, match="score_prior needs an alignment"):
        prepare_objects(rules, make_comp({"R": 3}, {"R": 1}), scen, None)


def test_certain_party_prior_is_kept(rules: RuleSet) -> None:
    scen = make_scenario(
        party_priors={"R": {"*": 0.0}}, alignment="a.json", score_prior={"R": {"slope": 2.0}}
    )
    comp, n = apply_score_prior(scen, make_comp(_house(), {"R": 1}), rules, _alignment({}))
    assert n == 4  # NEW, VET, ZERO, OVR: no alignment history and no override here
    new = {m.id: m for m in comp.bodies["house"].roster}["NEW"]
    assert set(new.p_pro.values()) == {0.0}


def _senate() -> list[dict[str, Any]]:
    return [
        {"id": "SNEW", "name": "SNEW", "party": "R", "score": 2.0, "score_source": SRC},
        {"id": "SVET", "name": "SVET", "party": "R", "score": 2.0, "score_source": SRC},
        # A former House member: no Senate votes, but House votes in the alignment file.
        {"id": "MOVED", "name": "MOVED", "party": "R", "score": 2.0, "score_source": SRC},
    ]


def test_score_prior_senate_and_history_in_any_chamber(rules: RuleSet) -> None:
    scen = make_scenario(alignment="a.json", score_prior={"R": {"slope": 0.5}})
    align = _alignment({"VET": 200, "MOVED": 150}, senate={"SVET": 80, "MOVED": 0})
    comp, n = apply_score_prior(scen, make_comp(_house(), _senate()), rules, align)
    senate = {m.id: m for m in comp.bodies["senate"].roster}
    senate_stages = {s.id for s in rules.stages if s.chamber == "senate"}
    assert set(senate["SNEW"].p_pro) == senate_stages
    assert senate["SNEW"].p_pro["S2"] == pytest.approx(sigmoid(logit(0.05) + 1.0))
    assert senate["SVET"].p_pro == {} and senate["MOVED"].p_pro == {}
    assert n == 4  # house NEW, ZERO and OVR (no override here); senate SNEW


def test_chamber_missing_from_alignment_is_skipped_with_warning(rules: RuleSet) -> None:
    scen = make_scenario(alignment="a.json", score_prior={"R": {"slope": 0.5}})
    comp = make_comp(_house(), _senate())
    prep = prepare_objects(rules, comp, scen, _alignment({"VET": 200}))  # house only
    senate = {m.id: m for m in prep.comp.bodies["senate"].roster}
    assert all(m.p_pro == {} for m in senate.values())
    assert {m.id: m for m in prep.comp.bodies["house"].roster}["NEW"].p_pro
    assert any("score_prior skipped the senate" in w for w in prep.warnings)
    both = prepare_objects(rules, comp, scen, _alignment({"VET": 200}, senate={}))
    assert not any("skipped" in w for w in both.warnings)


def test_partial_override_excludes_member_at_every_stage(rules: RuleSet) -> None:
    scen = make_scenario(
        alignment="a.json",
        overrides={"NEW": {"H1": 0.5}},
        score_prior={"R": {"slope": 1.0}},
    )
    comp, _ = apply_score_prior(scen, make_comp(_house(), {"R": 1}), rules, _alignment({}))
    assert {m.id: m for m in comp.bodies["house"].roster}["NEW"].p_pro == {}


def test_outer_loop_reapplies_score_prior_through_simulate(rules: RuleSet) -> None:
    house = [
        {"id": f"N{i:03d}", "name": f"N{i:03d}", "party": "R", "score": 3.0, "score_source": SRC}
        for i in range(435)
    ]
    kw: dict[str, Any] = {
        "party_priors": {"R": {"*": {"low": 0.2, "high": 0.6}}, "D": {"*": 0.9}},
        "alignment": "a.json",
        "uncertainty_draws": 4,
    }
    comp = make_comp(house, {"R": 100})
    align = _alignment({})
    scored = prepare_objects(
        rules, comp, make_scenario(score_prior={"R": {"slope": 1.0}}, **kw), align
    )
    for sp in sampled_preps(scored, 4, scored.scenario.seed):
        drawn = sp.scenario.party_priors["R"]["*"]
        assert isinstance(drawn, float)
        new = sp.comp.bodies["house"].roster[0]
        assert new.p_pro["H1"] == pytest.approx(sigmoid(logit(drawn) + 3.0))
    plain = prepare_objects(rules, comp, make_scenario(**kw), align)
    with_score = simulate(scored, draws=500)
    without = simulate(plain, draws=500)
    assert with_score.uncertainty_draws == 4
    h1 = [
        next(g for g in sim.articles[0].gates if g.stage == "H1").p_pass_given_reached
        for sim in (with_score, without)
    ]
    assert h1[0] > h1[1] + 0.5
