# SPDX-FileCopyrightText: 2026 Justin Stanley
# SPDX-License-Identifier: MIT
"""One-notch sensitivity (tornado) data and its rendering."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from impsolver.model import RuleSet
from impsolver.portfolio import load, solve
from impsolver.prepare import prepare_objects
from impsolver.report import render, tornado_section, tornado_svg
from impsolver.tornado import Tornado, TornadoBar, fatigued, p_removal, tornado, with_scenario
from tests.conftest import make_comp, make_prep, make_scenario
from tests.test_priors import _alignment, _comp

REPO = Path(__file__).resolve().parents[1]
DRAWS = 2000


@pytest.fixture(scope="module")
def comp():  # type: ignore[no-untyped-def]
    return make_comp({"D": 214, "I": 1, "R": 220}, {"D": 45, "I": 2, "R": 53})


def _prep(rules: RuleSet, comp, **kw):  # type: ignore[no-untyped-def]
    priors = {"D": {"*": 0.97}, "I": {"*": 0.9}, "R": {"*": 0.3, "H1": 0.4, "S1": 0.45}}
    return make_prep(rules, comp, party_priors=kw.pop("party_priors", priors), **kw)


def test_bloc_prior_swings_are_monotonic(rules: RuleSet, comp) -> None:  # type: ignore[no-untyped-def]
    prep = _prep(rules, comp)
    t = tornado(prep, "I", DRAWS)
    assert t.base == pytest.approx(p_removal(prep, "I", DRAWS))
    blocs = [b for b in t.bars if b.kind == "bloc_prior"]
    assert {b.input for b in blocs} == {"D prior", "I prior", "R prior"}
    for b in blocs:
        # Common random numbers: raising a bloc's support can only help removal.
        assert b.p_low <= t.base <= b.p_high
        assert b.swing == pytest.approx(b.p_high - b.p_low)
    r = next(b for b in blocs if b.input == "R prior")
    assert r.p_high > r.p_low  # the swing bloc matters
    assert r.note is not None and "H1 0.45" in r.note and "S1 0.4" in r.note


def test_uncertain_priors_move_by_their_point_value(rules: RuleSet, comp) -> None:  # type: ignore[no-untyped-def]
    priors = {
        "D": {"*": {"beta": [97, 3]}},
        "I": {"*": 0.9},
        "R": {"*": {"low": 0.2, "high": 0.4}, "H1": 0.4, "S1": 0.45},
    }
    prep = _prep(rules, comp, party_priors=priors)
    t = tornado(prep, "I", DRAWS)
    assert t.base == pytest.approx(p_removal(prep, "I", DRAWS))
    r = next(b for b in t.bars if b.input == "R prior")
    assert r.note is not None and "down: * 0.25" in r.note and "up: * 0.35" in r.note
    assert r.p_low <= t.base <= r.p_high
    d = next(b for b in t.bars if b.input == "D prior")
    assert d.note is not None and "up: * 1" in d.note and d.high_setting.endswith("(clipped)")


def test_bars_sorted_by_swing(rules: RuleSet, comp) -> None:  # type: ignore[no-untyped-def]
    t = tornado(_prep(rules, comp), "I", DRAWS)
    swings = [b.swing for b in t.bars]
    assert swings == sorted(swings, reverse=True)


def test_clipping_is_reported(rules: RuleSet, comp) -> None:  # type: ignore[no-untyped-def]
    t = tornado(_prep(rules, comp, rho=0.9), "I", DRAWS)
    d = next(b for b in t.bars if b.input == "D prior")
    assert d.high_setting.endswith("(clipped)") and "up: * 1" in (d.note or "")
    assert not d.low_setting.endswith("(clipped)")
    rho = next(b for b in t.bars if b.kind == "rho")
    assert (rho.low_setting, rho.high_setting) == ("rho 0.7", "rho 1")
    assert 0.0 <= rho.p_low <= 1.0 and 0.0 <= rho.p_high <= 1.0


def test_rho_bar_moves_with_correlation(rules: RuleSet, comp) -> None:  # type: ignore[no-untyped-def]
    # P(removal) is not monotone in rho in general; with a case well under 50% more bloc
    # correlation spreads outcomes, so the two notches must differ.
    t = tornado(_prep(rules, comp), "I", DRAWS)
    rho = next(b for b in t.bars if b.kind == "rho")
    assert rho.p_low != rho.p_high


def test_fatigue_bar(rules: RuleSet, comp) -> None:  # type: ignore[no-untyped-def]
    prep = _prep(rules, comp)
    base = p_removal(prep, "I", DRAWS)
    t = tornado(prep, "I", DRAWS, fatigue=(0.1, 2), base=base)
    assert t.base == pytest.approx(fatigued(base, 0.1, 2))
    f = next(b for b in t.bars if b.kind == "fatigue")
    # More fatigue lowers P for a case tried after others.
    assert f.p_low > t.base > f.p_high
    assert (f.low_setting, f.high_setting) == ("-0.10", "+0.30")
    for b in t.bars:
        if b.kind == "bloc_prior":
            assert b.p_low <= t.base <= b.p_high
    first = tornado(prep, "I", DRAWS, fatigue=(0.1, 0), base=base)
    f0 = next(b for b in first.bars if b.kind == "fatigue")
    assert f0.swing == 0.0 and f0.note == "no effect: tried first in the order"
    assert "fatigue" not in {b.kind for b in tornado(prep, "I", DRAWS, base=base).bars}


def test_members_with_own_probability_do_not_move(rules: RuleSet) -> None:
    house = [{"id": f"h{i}", "name": f"h{i}", "party": "R", "p_pro": {"*": 0.5}} for i in range(5)]
    senate = [{"id": f"s{i}", "name": f"s{i}", "party": "R", "p_pro": {"*": 0.5}} for i in range(3)]
    prep = make_prep(rules, make_comp(house, senate), party_priors={"R": {"*": 0.1}})
    t = tornado(prep, "I", 500)
    r = next(b for b in t.bars if b.kind == "bloc_prior")
    assert r.p_low == r.p_high == t.base


def test_with_scenario_does_not_reapply_defection_prior(rules: RuleSet) -> None:
    scen = make_scenario(
        party_priors={"R": {"*": 0.1}}, alignment="a.json", defection_prior={"beta": 1.0}
    )
    raw = _comp()
    prep = prepare_objects(rules, raw, scen, _alignment({"HI": 40, "LO": 0, "OWN": 40}))
    assert prep.input_comp is raw
    again = with_scenario(prep, scen)
    assert again.comp == prep.comp
    up = with_scenario(prep, scen.model_copy(update={"party_priors": {"R": {"*": 0.15}}}))
    hi = {m.id: m for m in up.comp.bodies["house"].roster}["HI"]
    base_hi = {m.id: m for m in prep.comp.bodies["house"].roster}["HI"]
    assert hi.p_pro["H2"] > base_hi.p_pro["H2"]  # the prior follows the moved party prior
    plain = make_prep(rules, make_comp({"R": 3}, {"R": 1}))
    assert plain.input_comp is plain.comp


def test_portfolio_tornado_uses_recommended_order() -> None:
    loaded = load(REPO / "examples" / "portfolio-example.yaml")
    res = solve(loaded, joint=False)
    assert set(res.tornado) == set(loaded.preps)
    order = res.succession_order or res.plans[0].order
    slots = {s.id: s for s in res.plans[0].slots}
    for cid, t in res.tornado.items():
        assert cid in order
        assert t.base == pytest.approx(slots[cid].p)
        assert t.draws == loaded.pf.draws
        assert any(b.kind == "fatigue" for b in t.bars)
    html = render(res, loaded.pf)
    assert 'id="tornado"' in html and "official-a (Official A)" in html
    assert solve(loaded, joint=False, sensitivities=False).tornado == {}


def _write_portfolio(tmp_path: Path, scen_text: str, **extra: str) -> Path:
    (tmp_path / "s.yaml").write_text(scen_text)
    lines = "\n".join(f"{k}: {v}" for k, v in extra.items())
    pf = tmp_path / "p.yaml"
    pf.write_text(
        f"""schema_version: 1
start: 2027-01-04
deadline: 2028-12-15
draws: 400
{lines}
candidates:
  - {{id: x, scenario: s.yaml, house_days: 10, senate_days: 5}}
"""
    )
    return pf


SCEN = f"""schema_version: 1
target: {{name: Official X, office: judge}}
articles: [I, II]
rules: us-federal
composition: {REPO / "compositions" / "shorthand-119.yaml"}
party_priors:
  D: {{"*": 0.9}}
  I: {{"*": 0.9}}
  R: {{"*": 0.4, S2: 0.35}}
rho: 0.5
seed: 3
"""


def test_portfolio_tornado_any_article_and_left_out(tmp_path: Path) -> None:
    loaded = load(_write_portfolio(tmp_path, SCEN))
    res = solve(loaded, joint=False)
    t = res.tornado["x"]
    assert t.base == pytest.approx(res.p0["x"])  # first in the order: no fatigue
    assert "removal on any article" in t.notes
    dropped = load(_write_portfolio(tmp_path, SCEN, p_floor="0.99"))
    td = solve(dropped, joint=False).tornado["x"]
    assert td.basis == "P(removal) alone"
    assert "not in the recommended order; measured alone" in td.notes
    assert all(b.kind != "fatigue" for b in td.bars)


NASTY = '<script>alert("x")</script>&'


def _nasty() -> Tornado:
    bar = TornadoBar(
        input=f"{NASTY} prior",
        kind="bloc_prior",
        low_setting="-0.05",
        high_setting="+0.05",
        p_low=0.2,
        p_high=0.4,
        swing=0.2,
        note=f"down: {NASTY}",
    )
    return Tornado(
        id=NASTY, label=f"<b>{NASTY}</b>", base=0.3, basis="P", draws=10, bars=[bar], notes=[NASTY]
    )


def test_tornado_svg_escapes_user_text() -> None:
    html = tornado_svg(_nasty()) + tornado_section([_nasty()])
    assert "<script>" not in html and "<b>" not in html
    assert "&lt;script&gt;alert(&quot;x&quot;)&lt;/script&gt;&amp;" in html
    assert html.count("<svg") == 2 and 'role="img"' in html


def test_tornado_svg_handles_flat_and_empty() -> None:
    flat = Tornado(id="f", label="f", base=1.0, basis="P", draws=10, bars=[])
    svg = tornado_svg(flat)
    assert "base 100.0%" in svg
    assert not re.search(r'width="-', svg)
    assert tornado_section([]) == ""
