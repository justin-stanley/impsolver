# SPDX-FileCopyrightText: 2026 Justin Stanley
# SPDX-License-Identifier: MIT
"""``impsolver compare-plans``: two portfolios or two scenarios side by side."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from impsolver.cli import main
from impsolver.compare import CompareError, PortfolioSide, ScenarioSide, compare, kind_of
from impsolver.portfolio import load, solve
from impsolver.report import render_comparison

REPO = Path(__file__).resolve().parents[1]
EX = REPO / "examples"
NASTY = '<script>alert("x")</script>'


def _scenario(tmp_path: Path, name: str, target: str, r: float) -> Path:
    p = tmp_path / name
    p.write_text(
        f"""schema_version: 1
target: {{name: '{target}', office: judge}}
rules: us-federal
composition: {REPO / "compositions" / "shorthand-119.yaml"}
party_priors:
  D: {{"*": 0.96}}
  I: {{"*": 0.9}}
  R: {{"*": {r}}}
seed: 5
"""
    )
    return p


def _portfolio(tmp_path: Path, name: str, fatigue: float) -> Path:
    p = tmp_path / name
    p.write_text(
        f"""schema_version: 1
start: 2027-01-04
deadline: 2028-12-15
fatigue_delta: {fatigue}
draws: 400
candidates:
  - {{id: one, scenario: {EX / "scenario-cabinet-a.yaml"}, house_days: 20, senate_days: 10}}
  - {{id: two, p: 0.5, house_days: 20, senate_days: 10}}
"""
    )
    return p


def test_kind_of(tmp_path: Path) -> None:
    assert kind_of(EX / "portfolio-example.yaml") == "portfolio"
    assert kind_of(EX / "scenario-cabinet-a.yaml") == "scenario"
    bad = tmp_path / "x.yaml"
    bad.write_text("- 1\n- 2\n")
    with pytest.raises(CompareError, match="neither"):
        kind_of(bad)


def test_mixed_kinds_exit_2(capsys: pytest.CaptureFixture[str]) -> None:
    rc = main(
        ["compare-plans", str(EX / "portfolio-example.yaml"), str(EX / "scenario-cabinet-a.yaml")]
    )
    assert rc == 2 and "give two of a kind" in capsys.readouterr().err


def test_scenarios_side_by_side(tmp_path: Path) -> None:
    a = _scenario(tmp_path, "a.yaml", "Official A", 0.35)
    b = _scenario(tmp_path, "b.yaml", "Official B", 0.25)
    c, warnings = compare(a, b, draws=1000)
    assert c.kind == "scenario" and warnings == []
    assert isinstance(c.a, ScenarioSide) and isinstance(c.b, ScenarioSide)
    # Same seed, lower R prior: B cannot do better than A.
    assert c.b.p_removal <= c.a.p_removal
    assert c.a.tornado.base == pytest.approx(c.a.p_removal)
    assert all(bar.kind != "fatigue" for bar in c.a.tornado.bars)
    html = render_comparison(c)
    assert "Official A" in html and "Official B" in html
    assert html.count('class="tornado"') == 2
    # Each side shows the counted tally of every gate against its threshold.
    gates = c.a.gates["I"].gates
    assert [g.stage for g in gates] == [g.stage for g in c.a.simulation.articles[0].gates]
    assert html.count("<p class=facts>") == 2 * len(gates)
    assert f"{gates[0].required} needed" in html
    assert not re.search(r"""(src|href)=["']?https?://""", html)


def test_portfolios_side_by_side(tmp_path: Path) -> None:
    a = _portfolio(tmp_path, "a.yaml", 0.0)
    b = _portfolio(tmp_path, "b.yaml", 0.4)
    c, _ = compare(a, b)
    assert c.kind == "portfolio"
    assert isinstance(c.a, PortfolioSide) and isinstance(c.b, PortfolioSide)
    # Same cases, more fatigue: the recommended plan cannot gain expected removals.
    assert c.b.expected_removals <= c.a.expected_removals + 1e-9
    assert c.a.result.p0 == c.b.result.p0
    alone = solve(load(a))
    assert c.a.expected_removals == pytest.approx(alone.plans[0].expected_removals)
    assert [s.id for s in c.a.slots] == c.a.recommended_order
    html = render_comparison(c)
    assert "Expected removals, recommended plan" in html and "B − A" in html
    assert html.count('class="tornado"') == 2  # one scenario candidate per side
    # Each side draws its recommended order on the lane calendar.
    assert html.count("<h3>Floor time</h3>") == 2 and html.count('class="lanes"') == 2
    assert all(s.house_lane is not None for s in c.a.slots)


def test_portfolio_side_with_succession_and_left_out() -> None:
    c, _ = compare(EX / "portfolio-example.yaml", EX / "portfolio-example.yaml")
    html = render_comparison(c)
    assert "Chance of removal is below p_floor." in html  # official-e
    assert "not scheduled unless a succession rule applies" in html  # official-f-acting


def test_cli_text_json_and_html(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    a = _scenario(tmp_path, "a&b.yaml", NASTY, 0.35)
    b = _scenario(tmp_path, "b.yaml", "Official B", 0.25)
    out = tmp_path / "cmp.html"
    rc = main(["compare-plans", str(a), str(b), "--draws", "500", "--html", str(out)])
    cap = capsys.readouterr()
    assert rc == 0 and "wrote" in cap.err
    assert "P(removal)=" in cap.out and "R prior" in cap.out
    page = out.read_text()
    visible = page.split('id="impsolver-data"')[0]
    assert "<script>alert" not in visible and "a&b" not in visible
    assert "&lt;script&gt;alert(&quot;x&quot;)&lt;/script&gt;" in visible
    assert "a&amp;b.yaml" in visible
    assert "</script>" not in page.split('id="impsolver-data">')[1].split("</script>")[0]
    rc = main(["--format", "json", "compare-plans", str(a), str(b), "--draws", "500"])
    data = json.loads(capsys.readouterr().out)
    assert rc == 0 and data["kind"] == "scenario" and data["a"]["target"] == NASTY


def test_cli_portfolio_text(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    a = _portfolio(tmp_path, "a.yaml", 0.0)
    b = _portfolio(tmp_path, "b.yaml", 0.4)
    assert main(["compare-plans", str(a), str(b)]) == 0
    out = capsys.readouterr().out
    assert "E[removals]=" in out and "fatigue delta" in out


def test_warnings_are_printed(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    a = _scenario(tmp_path, "a.yaml", "Official A", 0.35)
    text = a.read_text().replace('  R: {"*": 0.35}', '  R: {"*": 0.35}\n  Q: {"*": 0.5}')
    a.write_text(text)
    assert main(["compare-plans", str(a), str(a), "--draws", "200"]) == 0
    assert "warning:" in capsys.readouterr().err


def test_scenario_page_omits_fatigue_and_portfolio_json_has_tornado(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    a = _scenario(tmp_path, "a.yaml", "Official A", 0.35)
    c, _ = compare(a, a, draws=300)
    assert "fatigue delta" not in render_comparison(c)
    pf = _portfolio(tmp_path, "p.yaml", 0.1)
    assert main(["--format", "json", "portfolio", str(pf)]) == 0
    data = json.loads(capsys.readouterr().out)
    assert set(data["tornado"]) == {"one"}


def test_scenario_side_uses_point_priors_throughout(tmp_path: Path) -> None:
    from impsolver.compare import scenario_side
    from impsolver.prepare import prepare

    p = _scenario(tmp_path, "u.yaml", "Placeholder", 0.3)
    p.write_text(
        p.read_text().replace('R: {"*": 0.3}', 'R: {"*": {low: 0.2, high: 0.4}}')
        + "uncertainty_draws: 50\n"
    )
    side = scenario_side(prepare(p), p, 2000)
    assert side.simulation.articles[0].p_complete == pytest.approx(side.p_removal)
    assert side.simulation.articles[0].p_complete_interval is None
