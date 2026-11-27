from typing import Any

import pytest

from impsolver.portfolio import Loaded, evaluate_branching, make_ctx, solve
from tests.test_portfolio import c, pf


def _pf(variant_p: float | None) -> Any:
    succ = [{"on_removal_of": "T", "becomes": "V" if variant_p is not None else None}]
    cands = [c("T", 0.4), c("X", 0.5, succession=succ)]
    if variant_p is not None:
        cands.append(c("V", variant_p, variant_of="X"))
    return pf(cands)


def _ctx(p: Any) -> Any:
    return make_ctx(p, {x.id: x.p or 0 for x in p.candidates})[0]


def test_harder_variant_puts_dependent_first() -> None:
    ctx = _ctx(_pf(0.2))
    assert evaluate_branching(ctx, ("X", "T"))[0] == pytest.approx(0.90)
    assert evaluate_branching(ctx, ("T", "X"))[0] == pytest.approx(0.78)
    r = solve(Loaded(ctx.pf, {}, ctx.p0), joint=False)
    assert r.succession_order == ["X", "T"] and r.succession_value == pytest.approx(0.90)


def test_easier_variant_puts_trigger_first() -> None:
    ctx = _ctx(_pf(0.9))
    assert evaluate_branching(ctx, ("T", "X"))[0] == pytest.approx(1.06)
    assert evaluate_branching(ctx, ("X", "T"))[0] == pytest.approx(0.90)
    r = solve(Loaded(ctx.pf, {}, ctx.p0), joint=False)
    assert r.succession_order == ["T", "X"]
    tree = r.decision_tree
    assert tree is not None and tree.at == "T" and tree.p_removed == pytest.approx(0.4)


def test_cancel() -> None:
    ctx = _ctx(_pf(None))
    assert evaluate_branching(ctx, ("T", "X"))[0] == pytest.approx(0.4 + 0.6 * 0.5)


def test_depth_cap() -> None:
    succ = [{"on_removal_of": f"T{i}", "becomes": None} for i in range(4)]
    p = pf([c(f"T{i}", 0.3, h=3, s=3) for i in range(4)] + [c("D", 0.5, h=3, s=3, succession=succ)])
    ctx = _ctx(p)
    _, tree = evaluate_branching(ctx, ("T0", "T1", "T2", "T3", "D"))
    depth = 0
    while tree is not None and tree.at != "(end)":
        depth += 1
        tree = tree.not_removed
    assert depth == 3
