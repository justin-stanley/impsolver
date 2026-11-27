# SPDX-FileCopyrightText: 2026 Justin Stanley
# SPDX-License-Identifier: MIT
import random
from typing import Any

import pytest

from impsolver import portfolio
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


def _squeeze(v_house: int) -> Any:
    """One House lane: once T is removed, V (fresh House time) and Y cannot both fit."""
    succ = [{"on_removal_of": "T", "becomes": "V"}]
    return pf(
        [
            c("T", 0.5),
            c("X", 0.7, succession=succ, release="2027-03-01"),
            c("V", 0.2, h=v_house, variant_of="X"),
            c("Y", 0.6, release="2027-03-01"),
        ],
        deadline="2027-04-01" if v_house == 30 else "2027-05-10",
        house_concurrency=1,
    )


def test_removed_branch_reorders_when_that_beats_keeping_order() -> None:
    ctx = _ctx(_squeeze(60))
    kept, _ = evaluate_branching(ctx, ("T", "X", "Y"), adaptive=False)
    value, tree = evaluate_branching(ctx, ("T", "X", "Y"))
    # Not removed: X (0.7) and Y (0.6) both fit. Removed: V's long House phase leaves no room
    # for Y, so keeping order gets V (0.2); trying Y first gets 0.6 and V no longer fits.
    # Kept: 0.5 + 0.5 * 0.2 + 0.5 * 1.3 = 1.25. Re-ordered: 0.5 + 0.5 * 0.6 + 0.5 * 1.3 = 1.45.
    assert kept == pytest.approx(1.25) and value == pytest.approx(1.45) and value > kept
    assert tree.removed is not None and tree.not_removed is not None and tree.verdict is not None
    assert tree.removed.order == ["Y", "V"] and tree.removed.reordered
    assert tree.not_removed.order == ["X", "Y"] and not tree.not_removed.reordered
    for line in tree.removed.schedule:  # re-planned work starts after the verdict
        assert line.split("House ")[1][:10] > tree.verdict.isoformat()


def test_adaptive_branches_change_the_recommended_order(monkeypatch: pytest.MonkeyPatch) -> None:
    ctx = _ctx(_squeeze(30))
    r = solve(Loaded(ctx.pf, {}, ctx.p0), joint=False)
    monkeypatch.setattr(portfolio, "ADAPTIVE_REORDER", 1)  # keep order in every branch
    fixed = solve(Loaded(ctx.pf, {}, ctx.p0), joint=False)
    assert fixed.succession_value == pytest.approx(1.10)
    assert r.succession_value == pytest.approx(1.15)
    assert r.succession_order == ["T", "X", "Y"] and fixed.succession_order == ["T", "Y"]
    assert r.decision_tree is not None and r.decision_tree.removed is not None
    assert r.decision_tree.removed.reordered


def test_reordering_is_skipped_above_the_limit() -> None:
    succ = [{"on_removal_of": "T", "becomes": None}]
    later = [c(f"Y{i}", 0.1 * (i + 1), h=3, s=3, release="2027-06-01") for i in range(7)]
    p = pf([c("T", 0.5, h=3, s=3), c("X", 0.3, h=3, s=3, succession=succ), *later])
    ctx = _ctx(p)
    order = ("T", "X", *[f"Y{i}" for i in range(7)])
    value, tree = evaluate_branching(ctx, order)
    assert value == pytest.approx(evaluate_branching(ctx, order, adaptive=False)[0])
    assert tree.removed is not None and tree.not_removed is not None
    assert tree.removed.order == [f"Y{i}" for i in range(7)] and not tree.removed.reordered
    assert not tree.not_removed.reordered  # eight cases not started in this branch


def test_adaptive_never_loses_and_keeps_started_work() -> None:
    """Random small portfolios: re-ordering is never worse, and a re-ordered branch keeps every
    House start that came on or before the verdict in the plan without branching."""
    rng = random.Random(7)
    reordered = 0
    for _ in range(60):
        succ = [{"on_removal_of": "T", "becomes": "V" if rng.random() < 0.6 else None}]
        cands = [c("T", rng.uniform(0.2, 0.8), h=rng.randint(3, 30), s=rng.randint(3, 20))]
        for i in range(rng.randint(3, 4)):
            kw: dict[str, Any] = {"succession": succ} if i == 0 else {}
            if i == 1 and rng.random() < 0.5:  # a second trigger: C1 changes if C0 is removed
                kw["succession"] = [{"on_removal_of": "C0", "becomes": None}]
            if rng.random() < 0.4:
                kw["release"] = f"2027-0{rng.randint(1, 4)}-1{rng.randint(0, 9)}"
            cands.append(c(f"C{i}", rng.uniform(0.2, 0.8), rng.randint(3, 40), 10, **kw))
        cands.append(c("V", rng.uniform(0.1, 0.9), rng.randint(3, 40), 10, variant_of="C0"))
        p = pf(
            cands,
            deadline=f"2027-0{rng.randint(4, 9)}-15",
            house_concurrency=rng.randint(1, 3),
            fatigue_delta=rng.choice([0.0, 0.2]),
        )
        ctx = _ctx(p)
        rest = [x.id for x in p.candidates if x.id not in ("T", "V")]
        order = ("T", *rng.sample(rest, len(rest)))
        value, tree = evaluate_branching(ctx, order)
        assert value >= evaluate_branching(ctx, order, adaptive=False)[0] - 1e-12
        if tree.at != "T" or tree.removed is None or tree.not_removed is None:
            continue
        assert tree.verdict is not None
        verdict = tree.verdict.isoformat()
        _, plain = evaluate_branching(ctx, order, adaptive=False)
        assert plain.not_removed is not None
        before = {
            cid: start
            for cid, start in _house_starts(plain.not_removed).items()
            if start <= verdict
        }
        for branch in (tree.removed, tree.not_removed):
            if not branch.reordered:
                continue
            reordered += 1
            for cid, start in _house_starts(branch).items():
                assert before.get(cid) == start or start > verdict
    assert reordered > 0


def _house_starts(node: Any) -> dict[str, str]:
    """House start of every case in a branch, following its not-removed path."""
    out: dict[str, str] = {}
    while node is not None:
        for line in node.schedule:
            cid, rest = line.split(" ", 1)
            out.setdefault(cid, rest.split("House ")[1][:10])
        node = node.not_removed
    return out
