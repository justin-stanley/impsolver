# SPDX-FileCopyrightText: 2026 Justin Stanley
# SPDX-License-Identifier: MIT
"""Input uncertainty on priors: ranges and Beta priors, bounds, and the outer Monte Carlo loop."""

import json
from pathlib import Path

import numpy as np
import pytest
from pydantic import ValidationError

from impsolver.cli import main
from impsolver.deterministic import evaluate
from impsolver.model import PriorBeta, PriorRange, RuleSet
from impsolver.prepare import prepare_objects
from impsolver.simulate import sampled_preps, simulate
from impsolver.uncertainty import (
    beta_cdf,
    beta_ppf,
    bounds,
    has_uncertainty,
    point,
    sample,
    sample_scenario,
    value,
)
from tests.conftest import make_comp, make_prep, make_scenario
from tests.test_priors import _alignment

COMP = {"D": 220, "R": 215}, {"D": 50, "R": 50}


# ------------------------------------------------------------------------ schema


def test_schema_accepts_number_range_and_beta() -> None:
    s = make_scenario(
        party_priors={
            "D": {"*": 0.95},
            "R": {"*": {"low": 0.2, "high": 0.4}, "S2": {"beta": [3, 7]}},
        },
        overrides={"R-001": {"*": {"low": 0.5, "high": 0.5}}},
    )
    assert s.party_priors["D"]["*"] == 0.95
    assert s.party_priors["R"]["*"] == PriorRange(low=0.2, high=0.4)
    assert s.party_priors["R"]["S2"] == PriorBeta(beta=(3.0, 7.0))
    assert s.uncertainty_draws == 0
    assert has_uncertainty(s)
    assert not has_uncertainty(make_scenario())


@pytest.mark.parametrize(
    "bad",
    [
        {"low": 0.5, "high": 0.4},
        {"low": -0.1, "high": 0.4},
        {"low": 0.1, "high": 1.2},
        {"low": 0.1},
        {"low": 0.1, "high": 0.2, "mid": 0.15},
        {"beta": [0, 2]},
        {"beta": [2]},
        {"beta": [1, 2, 3]},
        1.5,
    ],
)
def test_schema_rejects_bad_values(bad: object) -> None:
    with pytest.raises(ValidationError):
        make_scenario(party_priors={"R": {"*": bad}})


def test_uncertainty_draws_must_be_non_negative() -> None:
    with pytest.raises(ValidationError):
        make_scenario(uncertainty_draws=-1)


# ---------------------------------------------------------------- point and bounds


def test_point_bounds_and_value() -> None:
    r = PriorRange(low=0.2, high=0.6)
    assert point(r) == pytest.approx(0.4)
    assert bounds(r) == (0.2, 0.6)
    assert value(r, "low") == 0.2 and value(r, "high") == 0.6 and value(r) == pytest.approx(0.4)
    b = PriorBeta(beta=(2.0, 8.0))
    assert point(b) == pytest.approx(0.2)
    lo, hi = bounds(b)
    assert beta_cdf(lo, 2, 8) == pytest.approx(0.05, abs=1e-9)
    assert beta_cdf(hi, 2, 8) == pytest.approx(0.95, abs=1e-9)
    assert point(0.3) == 0.3 and bounds(0.3) == (0.3, 0.3)


@pytest.mark.parametrize("b", [0.5, 1.0, 3.0, 40.0])
@pytest.mark.parametrize("q", [0.01, 0.05, 0.5, 0.95])
def test_beta_ppf_matches_closed_forms(q: float, b: float) -> None:
    # Beta(1, b): F(x) = 1 - (1 - x)^b; Beta(b, 1): F(x) = x^b.
    assert beta_ppf(q, 1.0, b) == pytest.approx(1 - (1 - q) ** (1 / b), abs=1e-9)
    assert beta_ppf(q, b, 1.0) == pytest.approx(q ** (1 / b), abs=1e-9)


def test_beta_cdf_edges_and_symmetry() -> None:
    assert beta_cdf(0.0, 2, 3) == 0.0 and beta_cdf(1.0, 2, 3) == 1.0
    assert beta_cdf(0.5, 4, 4) == pytest.approx(0.5, abs=1e-12)
    assert beta_cdf(0.3, 2, 5) == pytest.approx(1 - beta_cdf(0.7, 5, 2), abs=1e-12)
    # Beta(2, 2): F(x) = 3x^2 - 2x^3.
    assert beta_cdf(0.3, 2, 2) == pytest.approx(3 * 0.09 - 2 * 0.027, abs=1e-12)


def test_sample_stays_in_support_and_matches_mean() -> None:
    rng = np.random.default_rng(0)
    r = PriorRange(low=0.2, high=0.3)
    xs = [sample(r, rng) for _ in range(2000)]
    assert min(xs) >= 0.2 and max(xs) <= 0.3
    assert np.mean(xs) == pytest.approx(0.25, abs=0.003)
    b = PriorBeta(beta=(3.0, 1.0))
    assert np.mean([sample(b, rng) for _ in range(4000)]) == pytest.approx(0.75, abs=0.01)
    assert sample(0.4, rng) == 0.4


def test_sample_scenario_one_value_per_prior() -> None:
    s = make_scenario(
        party_priors={"D": {"*": 0.9}, "R": {"*": {"low": 0.1, "high": 0.5}, "H1": 0.2}},
        overrides={"D-001": {"S2": {"beta": [2, 2]}}},
        uncertainty_draws=5,
    )
    t = sample_scenario(s, np.random.default_rng(1))
    assert t.uncertainty_draws == 0 and not has_uncertainty(t)
    assert t.party_priors["R"]["H1"] == 0.2 and t.party_priors["D"]["*"] == 0.9
    assert 0.1 <= t.party_priors["R"]["*"] <= 0.5  # type: ignore[operator]
    assert isinstance(t.overrides["D-001"]["S2"], float)
    # The original scenario is untouched.
    assert isinstance(s.party_priors["R"]["*"], PriorRange)


# ----------------------------------------------------------------- resolution


def test_resolver_bounds_and_sources(rules: RuleSet) -> None:
    prep = make_prep(
        rules,
        make_comp(*COMP),
        party_priors={"D": {"*": 0.9}, "R": {"*": {"low": 0.2, "high": 0.6}}},
        overrides={"R-001": {"*": {"beta": [1, 1]}}},
        shifts=[{"label": "s", "bloc": "R", "delta": 1.0}],
    )
    r2 = prep.members("house")[221]
    assert r2.id == "R-002"
    assert prep.resolver.base(r2, "H1") == (pytest.approx(0.4), "party_prior")
    assert prep.resolver.base(r2, "H1", "low")[0] == 0.2
    assert prep.resolver.base(r2, "H1", "high")[0] == 0.6
    r1 = prep.members("house")[220]
    v, src = prep.resolver.spec(r1, "H1")
    assert src == "override" and v == PriorBeta(beta=(1.0, 1.0))
    # Shifts apply to each bound on the log-odds scale.
    lo = prep.probs("house", "H1", "I", bound="low")
    assert lo[221] == pytest.approx(1 / (1 + (0.8 / 0.2) * np.exp(-1.0)))


# ----------------------------------------------------------------- deterministic


def _gate(ev, stage: str):  # type: ignore[no-untyped-def]
    return next(g for g in ev.articles[0].gates if g.stage == stage)


def test_evaluate_uses_range_bounds(rules: RuleSet) -> None:
    comp = make_comp(*COMP)
    fixed = evaluate(make_prep(rules, comp, party_priors={"D": {"*": 0.95}, "R": {"*": 0.05}}))
    wide = evaluate(
        make_prep(
            rules,
            comp,
            party_priors={"D": {"*": {"low": 0.85, "high": 0.99}}, "R": {"*": 0.05}},
        )
    )
    h1f, h1w = _gate(fixed, "H1"), _gate(wide, "H1")
    assert (h1f.pro_min, h1f.pro_max) == (220, 220)
    # D's low bound 0.85 is under the 0.9 cutoff, so D members are no longer certain PRO.
    assert (h1w.pro_min, h1w.pro_max, h1w.uncertain) == (0, 220, 220)
    # A high bound above the low cutoff makes CON members uncertain too.
    up = evaluate(
        make_prep(
            rules, comp, party_priors={"D": {"*": 0.95}, "R": {"*": {"low": 0.0, "high": 0.2}}}
        )
    )
    assert (_gate(up, "H1").pro_min, _gate(up, "H1").pro_max) == (220, 435)


def test_evaluate_degenerate_range_equals_number(rules: RuleSet) -> None:
    comp = make_comp(*COMP)
    a = evaluate(make_prep(rules, comp, party_priors={"D": {"*": 0.95}, "R": {"*": 0.3}}))
    b = evaluate(
        make_prep(
            rules,
            comp,
            party_priors={"D": {"*": 0.95}, "R": {"*": {"low": 0.3, "high": 0.3}}},
        )
    )
    assert a == b


def test_evaluate_pivots_use_point_value(rules: RuleSet) -> None:
    prep = make_prep(
        rules,
        make_comp(*COMP),
        party_priors={"D": {"*": 0.95}, "R": {"*": 0.05}},
        overrides={"R-001": {"*": {"low": 0.3, "high": 0.7}}},
    )
    piv = evaluate(prep).articles[0].pivots
    top = piv[0]
    assert top.id == "R-001" and top.p == pytest.approx(0.5) and top.source == "override"


@pytest.mark.parametrize(("a", "pro_min"), [(30, 220), (5, 0)])
def test_evaluate_beta_bounds(rules: RuleSet, a: int, pro_min: int) -> None:
    # Beta(a, 1) has 5th percentile 0.05^(1/a): 0.905 for a = 30 (above the 0.9 cutoff), 0.55
    # for a = 5.
    comp = make_comp(*COMP)
    pp = {"D": {"*": {"beta": [a, 1]}}, "R": {"*": 0.05}}
    ev = evaluate(make_prep(rules, comp, party_priors=pp))
    assert (_gate(ev, "H1").pro_min, _gate(ev, "H1").pro_max) == (pro_min, 220)


# ------------------------------------------------------------------ simulation


def _prep(rules: RuleSet, **kw):  # type: ignore[no-untyped-def]
    data = {
        "party_priors": {"D": {"*": 0.97}, "R": {"*": {"low": 0.2, "high": 0.5}}},
        "seed": 5,
    }
    data.update(kw)
    return make_prep(rules, make_comp(*COMP), **data)


def test_outer_loop_off_uses_midpoint(rules: RuleSet) -> None:
    unc = simulate(_prep(rules), draws=4000)
    mid = simulate(_prep(rules, party_priors={"D": {"*": 0.97}, "R": {"*": 0.35}}), draws=4000)
    assert unc == mid
    assert unc.uncertainty_draws == 0 and unc.articles[0].p_complete_interval is None


def test_outer_loop_reports_interval(rules: RuleSet) -> None:
    s = simulate(_prep(rules, uncertainty_draws=40), draws=1000)
    a = s.articles[0]
    assert s.uncertainty_draws == 40 and s.draws == 1000
    assert a.p_complete_interval is not None
    lo, hi = a.p_complete_interval
    assert 0.0 <= lo < a.p_complete < hi <= 1.0
    assert hi - lo > 0.2  # R between 0.2 and 0.5 moves conviction a lot
    assert a.mc_se > 0
    # Reproducible, and the pooled gates cover every inner draw.
    assert simulate(_prep(rules, uncertainty_draws=40), draws=1000) == s
    assert a.gates[0].p_reached == 1.0


def test_outer_loop_argument_and_default_inner_draws(rules: RuleSet) -> None:
    s = simulate(_prep(rules), uncertainty_draws=3)
    assert s.uncertainty_draws == 3 and s.draws == 2000
    assert simulate(_prep(rules), draws=500).draws == 500
    with pytest.raises(ValueError, match=">= 0"):
        simulate(_prep(rules), uncertainty_draws=-1)


def test_degenerate_range_collapses_interval(rules: RuleSet) -> None:
    fixed = simulate(_prep(rules, party_priors={"D": {"*": 0.97}, "R": {"*": 0.35}}), draws=2000)
    deg = simulate(
        _prep(
            rules,
            party_priors={"D": {"*": 0.97}, "R": {"*": {"low": 0.35, "high": 0.35}}},
            uncertainty_draws=4,
        ),
        draws=2000,
    )
    p = fixed.articles[0].p_complete
    a = deg.articles[0]
    # Common random numbers: every outer draw repeats the fixed run exactly.
    assert a.p_complete == pytest.approx(p) and a.p_complete_interval == pytest.approx((p, p))
    assert [g.p_pass_given_reached for g in a.gates] == pytest.approx(
        [g.p_pass_given_reached for g in fixed.articles[0].gates]
    )


def test_no_uncertain_priors_ignores_outer_loop_and_warns(rules: RuleSet) -> None:
    prep = make_prep(rules, make_comp(*COMP), uncertainty_draws=10)
    assert any("uncertainty_draws has no effect" in w for w in prep.warnings)
    s = simulate(prep, draws=1000)
    assert s.uncertainty_draws == 0 and s.articles[0].p_complete_interval is None


def test_sampled_value_shared_across_bloc(rules: RuleSet) -> None:
    preps = sampled_preps(_prep(rules), 3, seed=5)
    vals = []
    for p in preps:
        h1 = p.probs("house", "H1", "I")[220:]
        s2 = p.probs("senate", "S2", "I")[50:]
        assert np.all(h1 == h1[0]) and np.all(s2 == h1[0])  # one "*" value: all R, all stages
        assert 0.2 <= h1[0] <= 0.5
        vals.append(float(h1[0]))
    assert len(set(vals)) == 3


def test_override_range_is_per_member(rules: RuleSet) -> None:
    prep = _prep(
        rules,
        party_priors={"D": {"*": 0.97}, "R": {"*": 0.1}},
        overrides={"R-001": {"*": {"low": 0.0, "high": 1.0}}, "R-002": {"*": {"beta": [1, 1]}}},
    )
    p = sampled_preps(prep, 1, seed=0)[0].probs("house", "H1", "I")
    assert p[220] != p[221] and p[222] == pytest.approx(0.1)


def test_multi_article_shares_prior_draws(rules: RuleSet) -> None:
    s = simulate(_prep(rules, articles=["I", "II"], uncertainty_draws=10), draws=500)
    a, b = s.articles
    # No article-specific shifts: both articles see the same priors and the same inner draws.
    assert a.p_complete == b.p_complete and a.p_complete_interval == b.p_complete_interval


def test_defection_prior_reapplied_per_draw(rules: RuleSet) -> None:
    house = [{"id": i, "name": i, "party": "R"} for i in ("HI", "LO")]
    comp = make_comp(house, {"R": 1})
    scen = make_scenario(
        party_priors={"R": {"*": {"low": 0.05, "high": 0.3}}},
        alignment="a.json",
        defection_prior={"beta": 1.0},
    )
    prep = prepare_objects(rules, comp, scen, _alignment({"HI": 40, "LO": 0}))
    # The prepared composition used the mean (0.175) as the party prior.
    assert prep.comp.bodies["house"].roster[0].p_pro["H1"] > 0.175
    assert prep.input_comp is comp
    samples = [p.comp.bodies["house"].roster[0].p_pro["H1"] for p in sampled_preps(prep, 4, 1)]
    assert len(set(samples)) == 4
    assert all(p.input_comp is comp for p in sampled_preps(prep, 1, 1))


# ------------------------------------------------------------------------- CLI

SCEN_TEXT = """\
schema_version: 1
target: {name: Placeholder Official, office: cabinet_secretary}
rules: us-federal
composition: comp.yaml
party_priors:
  D: {"*": 0.97}
  R: {"*": {low: 0.2, high: 0.5}, S2: {beta: [3, 7]}}
uncertainty_draws: 8
seed: 2
"""

COMP_TEXT = """\
schema_version: 1
name: placeholder
as_of: 2027-01-01
bodies:
  house: {seats: 435, party_shorthand: {D: 220, R: 215}}
  senate: {seats: 100, party_shorthand: {D: 50, R: 50}}
"""


def test_cli_simulate_with_uncertainty(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    (tmp_path / "comp.yaml").write_text(COMP_TEXT)
    scen = tmp_path / "scen.yaml"
    scen.write_text(SCEN_TEXT)
    assert main(["simulate", str(scen), "--draws", "500"]) == 0
    out = capsys.readouterr().out
    assert "8 outer draws over uncertain priors" in out and "5-95% over priors [" in out
    assert main(["--format", "json", "simulate", str(scen), "--uncertainty-draws", "3"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["uncertainty_draws"] == 3 and data["draws"] == 2000
    assert len(data["articles"][0]["p_complete_interval"]) == 2
    assert main(["simulate", str(scen), "--draws", "500", "--uncertainty-draws", "0"]) == 0
    assert "over priors" not in capsys.readouterr().out
    assert main(["validate", "us-federal", str(tmp_path / "comp.yaml"), str(scen)]) == 0
