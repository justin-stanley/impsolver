import re
from pathlib import Path

import pytest

from impsolver.cli import main
from impsolver.portfolio import Loaded, load, solve
from impsolver.report import render
from tests.test_portfolio import c, pf

REPO = Path(__file__).resolve().parents[1]


def _html(cands, **kw):  # type: ignore[no-untyped-def]
    p = pf(cands, **kw)
    res = solve(Loaded(p, {}, {x.id: x.p or 0 for x in p.candidates}), joint=True)
    return render(res, p), res


def test_self_contained_and_neutral() -> None:
    html, res = _html([c("a", 0.6), c("b", 0.4)])
    assert "does not nominate targets" in html
    assert not re.search(r"""(src|href)=["']?https?://""", html)
    for s in res.plans[0].slots:
        assert s.id in html


def test_user_text_is_escaped() -> None:
    html, _ = _html([c("<script>x</script>", 0.6)])
    assert "<script>x</script>" not in html.split('id="impsolver-data"')[0]
    assert "&lt;script&gt;" in html


def test_succession_tree_branches() -> None:
    succ = [{"on_removal_of": "T", "becomes": "V"}]
    html, res = _html([c("T", 0.4), c("X", 0.5, succession=succ), c("V", 0.9, variant_of="X")])
    assert res.succession_order == ["T", "X"]
    assert "If removed" in html and "If not removed" in html


def test_gate_paths_from_scenarios() -> None:
    loaded = load(REPO / "examples" / "portfolio-example.yaml")
    res = solve(loaded, joint=False)
    html = render(res, loaded.pf)
    assert "Senate: conviction (2/3)" in html and "Optional, after conviction" in html
    assert res.gate_paths["official-a"].p_complete == pytest.approx(res.p0["official-a"])


def test_cli_html(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    out = tmp_path / "plan.html"
    rc = main(["portfolio", str(REPO / "examples" / "portfolio-example.yaml"), "--html", str(out)])
    assert rc == 0 and out.read_text().startswith("<!doctype html>")
    assert "wrote" in capsys.readouterr().err
