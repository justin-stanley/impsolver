# SPDX-FileCopyrightText: 2026 Justin Stanley
# SPDX-License-Identifier: MIT
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


def test_branches_agree_on_work_started_before_the_verdict() -> None:
    """Audit case: two House lanes, X is cancelled if T is removed, Y is unrelated."""
    succ = [{"on_removal_of": "T", "becomes": None}]
    p = pf(
        [
            c("T", 0.5, h=30, s=30),
            c("X", 0.5, h=30, s=10, succession=succ),
            c("Y", 0.5, h=30, s=10),
        ],
        deadline="2027-05-07",
        house_concurrency=2,
    )
    _, tree = evaluate_branching(_ctx(p), ("T", "X", "Y"))
    assert tree.at == "T" and tree.verdict is not None and tree.removed and tree.not_removed
    verdict = tree.verdict.isoformat()

    def house_starts(node: Any) -> dict[str, str]:
        out = {}
        for line in node.schedule:
            cid, rest = line.split(" ", 1)
            out[cid] = rest.split("House ")[1][:10]
        return out

    kept, gone = house_starts(tree.not_removed), house_starts(tree.removed)
    for cid, start in kept.items():
        if start <= verdict:
            assert gone.get(cid) == start  # committed in both branches
    for cid, start in gone.items():
        if cid not in kept or kept[cid] != start:
            assert start > verdict  # anything re-planned starts after the verdict
    assert any("cancelled, time lost" in ln for ln in tree.removed.schedule)


def test_variant_needs_fresh_house_time_after_verdict() -> None:
    succ = [{"on_removal_of": "T", "becomes": "V"}]
    p = pf(
        [
            c("T", 0.5, h=10, s=10),
            c("X", 0.5, h=10, s=5, succession=succ),
            c("V", 0.5, h=10, s=5, variant_of="X"),
        ],
        house_concurrency=2,
    )
    _, tree = evaluate_branching(_ctx(p), ("T", "X"))
    assert tree.removed is not None and tree.verdict is not None
    v_line = next(ln for ln in tree.removed.schedule if ln.startswith("V "))
    assert v_line.split("House ")[1][:10] > tree.verdict.isoformat()


def test_sensitivity_uses_recommended_order() -> None:
    ctx = _ctx(_pf(0.9))
    r = solve(Loaded(ctx.pf, {}, ctx.p0), joint=False)
    base = next(row for row in r.sensitivity if row.label == "fatigue delta +0.0")
    assert r.succession_order == ["T", "X"]
    assert base.base_rescheduled == pytest.approx(1.06) and base.regret == pytest.approx(0.0)
