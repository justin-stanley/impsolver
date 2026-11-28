# SPDX-FileCopyrightText: 2026 Justin Stanley
# SPDX-License-Identifier: MIT
"""What-if controls: the browser's gate arithmetic and the other-settings calendars."""

import itertools
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from impsolver.model import ThresholdRule
from impsolver.portfolio import Loaded, PortfolioResult, load, solve
from impsolver.report import render
from impsolver.thresholds import required_pro
from impsolver.views_whatif import WHATIF_MATH, gate_whatif, other_settings

REPO = Path(__file__).resolve().parents[1]
EXAMPLE = REPO / "examples" / "portfolio-example.yaml"


@pytest.fixture(scope="module")
def loaded() -> Loaded:
    return load(EXAMPLE)


@pytest.fixture(scope="module")
def res(loaded: Loaded) -> PortfolioResult:
    return solve(loaded, joint=False)


def _node(script: str) -> str:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed")
    out = subprocess.run(
        [node, "-e", WHATIF_MATH + script], capture_output=True, text=True, check=True
    )
    return out.stdout


def test_browser_threshold_matches_python() -> None:
    rules = [
        {"kind": k, "p": p, "q": q, "direction": d, "tie_break": t}
        for (k, p, q), d, t in itertools.product(
            [
                ("majority_of_votes_cast", 1, 2),
                ("fraction_of_present", 2, 3),
                ("fraction_of_present", 3, 5),
                ("fraction_of_membership", 1, 2),
            ],
            ["pass", "fail"],
            ["none", "pro", "con"],
        )
    ]
    votings = [0, 1, 2, 50, 51, 97, 98, 99, 100, 434, 435]
    script = (
        f"var rules={json.dumps(rules)},vs={json.dumps(votings)},out=[];"
        "rules.forEach(function(r){vs.forEach(function(v){out.push(need(r,v,100));});});"
        "console.log(JSON.stringify(out));"
    )
    got = json.loads(_node(script))
    want = [
        required_pro(
            ThresholdRule(kind=r["kind"], p=r["p"], q=r["q"]),  # type: ignore[arg-type]
            r["direction"],  # type: ignore[arg-type]
            v,
            0,
            100,
            r["tie_break"],  # type: ignore[arg-type]
        )
        for r in rules
        for v in votings
    ]
    assert got == want


def test_browser_recount_of_a_gate(res: PortfolioResult) -> None:
    case = res.gates["official-a"]
    g = next(x for x in case.gates if x.stage == "S2")
    blocs = case.rosters[g.chamber].blocs
    assert res.meta is not None
    lo, hi = res.meta.scenarios["official-a"].cutoffs
    bloc = next(b for b in g.blocs if b.uncertain > 0)
    q = {
        "absn": 2,
        "absb": bloc.bloc,
        "absc": "U",
        "flipn": 1,
        "flipb": bloc.bloc,
        "lo": lo,
        "hi": hi,
        "lo0": lo,
        "hi0": hi,
    }
    script = (
        f"var g={json.dumps(g.model_dump(mode='json'))},blocs={json.dumps(blocs)};"
        f"var q={json.dumps(q)};var a=compute(g,blocs,q);q.absn=0;q.flipn=0;"
        "var b=compute(g,blocs,q);q.absn=9999;var c=compute(g,blocs,q);"
        "q.absn=0;q.lo=0.9;q.hi=0.1;var d=compute(g,blocs,q);"
        "console.log(JSON.stringify([a,b,c,d]));"
    )
    a, b, c, d = json.loads(_node(script))
    pro = sum(x.pro for x in g.blocs)
    unc = sum(x.uncertain for x in g.blocs)
    con = sum(x.con for x in g.blocs)
    take = min(2, bloc.uncertain)
    flip = min(1, bloc.uncertain - take)
    assert not b["changed"]
    assert (b["P"], b["U"], b["C"], b["voting"], b["need"]) == (
        pro,
        unc,
        con,
        g.present,
        g.required,
    )
    assert a["changed"] and a["voting"] == g.present - take
    assert (a["P"], a["U"], a["C"]) == (pro + flip, unc - take - flip, con)
    rule = ThresholdRule(kind=g.rule.kind, p=g.rule.p, q=g.rule.q)  # type: ignore[arg-type]
    assert a["need"] == required_pro(
        rule,
        g.rule.direction,  # type: ignore[arg-type]
        g.present - take,
        0,
        g.base,
        g.rule.tie_break,
    )
    # Asking for more members than the bloc has uses what is there and says so.
    assert c["U"] == unc - bloc.uncertain and c["notes"]
    # Cutoffs out of order are ignored with a note.
    assert not d["changed"] and "out of order" in d["notes"][0]


def test_gate_form_lists_blocs_and_locks_cutoffs_for_ranges(res: PortfolioResult) -> None:
    case = res.gates["official-a"]
    g = case.gates[0]
    form = gate_whatif("official-a", g, case, (0.1, 0.9), False)
    assert 'data-cid="official-a"' in form and f'data-gate="{g.stage}"' in form
    for b in g.blocs:
        assert f"<option>{b.bloc}</option>" in form
    assert "disabled" not in form and "The simulation is not re-run" in form
    locked = gate_whatif("official-a", g, case, (0.1, 0.9), True)
    assert locked.count("disabled") == 2 and "The cutoffs are fixed here" in locked


def test_what_if_rows_cover_lanes_saturdays_and_swaps(res: PortfolioResult) -> None:
    labels = [r.label for r in res.what_if]
    assert labels[:3] == ["House lanes 1", "House lanes 3", "trial Saturdays off"]
    by = {r.label: r for r in res.what_if}
    base_end = max(s.trial_end for s in res.plans[0].slots)
    assert max(s.trial_end for s in by["House lanes 1"].slots) > base_end
    assert by["House lanes 1"].house_lanes == 1 and by["House lanes 1"].kind == "setting"
    assert max(s.house_lane or 0 for s in by["House lanes 1"].slots) == 1
    swaps = [r for r in res.what_if if r.kind == "order"]
    order = res.plans[0].order
    assert len(swaps) == len(order) - 1
    assert swaps[0].label == f"order: {order[1]} before {order[0]}"
    for r in swaps:
        # No swap beats the order the solver chose.
        assert r.base_rescheduled <= r.best + 1e-9 and not r.fragile


def test_other_settings_section(loaded: Loaded, res: PortfolioResult) -> None:
    section = other_settings(loaded.pf, res)
    assert "<th scope=row>As supplied</th>" in section
    assert "<th scope=row>House lanes 3</th>" in section
    assert "set house_concurrency: 3 in the portfolio file" in section
    assert "set calendar.trial_saturdays: false in the portfolio file" in section
    assert "durations x1.25" in section and "fatigue" not in section
    n = len([r for r in [*res.what_if, *res.sensitivity] if "fatigue" not in r.label])
    assert section.count('<details class="alt">') == n
    assert " later)" in section
    page = render(res, loaded.pf)
    assert "<h2>Other settings</h2>" in page and 'class="wifbar"' in page
    assert page.count('<details class="whatif"') == sum(len(c.gates) for c in res.gates.values())


def test_no_other_settings_without_sensitivities(loaded: Loaded) -> None:
    quick = solve(loaded, joint=False, sensitivities=False)
    assert quick.what_if == []
    assert "<th scope=row>House lanes" not in other_settings(loaded.pf, quick)
