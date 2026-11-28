# SPDX-FileCopyrightText: 2026 Justin Stanley
# SPDX-License-Identifier: MIT
"""Self-contained HTML planning report for a portfolio result.

The page shows only what the user supplied and what the solver computed from it: the plans, the
timeline of House and Senate work, each case's gate-by-gate odds, succession branches, the
removals distribution, the members nearest each binding gate's threshold, sensitivity, and why
candidates were left out. It never adds targets.
"""

from __future__ import annotations

import html
import json
from collections.abc import Iterable

from .compare import Comparison, PortfolioSide, ScenarioSide
from .model import Portfolio
from .portfolio import PlanOut, PortfolioResult, Slot, TreeNode, excluded_reason_text
from .tornado import TORNADO_NOTE, Tornado, tornado_note
from .views_floor import FLOOR_CSS, left_out_table, plan_views, why_dates
from .views_votes import VOTES_CSS, votes_tab

OPTIONAL_GATES = {"S3"}
GATE_LABELS = {
    "H1": "House: motion to table fails",
    "H2": "House: article adopted",
    "S1": "Senate: motion to dismiss fails",
    "S2": "Senate: conviction (2/3)",
    "S3": "Senate: disqualification",
}

CSS = """
:root{--bg:#fbfaf7;--panel:#fff;--ink:#1d1d1b;--muted:#6b6a65;--line:#e4e2dc;--house:#2f6db5;
--committee:#8aa9d6;--trial:#c4642d;--wait:#b9b6ad;--recess:#efede7;--deadline:#a3312b;--ok:#2e7d4f;
--warn:#a76b00;--chip:#f3f1ec}
@media (prefers-color-scheme:dark){:root{--bg:#161614;--panel:#1f1f1c;--ink:#ecebe6;--muted:#a09e96;
--line:#34332f;--house:#6ea2e3;--committee:#45638f;--trial:#e08a55;--wait:#5d5b55;--recess:#262622;
--deadline:#e0736b;--ok:#6cc38f;--warn:#e0b05a;--chip:#2a2a26}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);
font:15px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Inter,Roboto,sans-serif}
main{max-width:1180px;margin:0 auto;padding:28px 16px 64px}
h1{font-size:24px;margin:0 0 4px}h2{font-size:17px;margin:32px 0 10px}
.sub{color:var(--muted);margin:0 0 18px}.panel{background:var(--panel);border:1px solid var(--line);
border-radius:10px;padding:16px;overflow-x:auto}
.kpis{display:flex;gap:12px;flex-wrap:wrap;margin:16px 0}.kpi{background:var(--panel);
border:1px solid var(--line);border-radius:10px;padding:10px 14px;min-width:150px}
.kpi b{display:block;font-size:22px}.kpi span{color:var(--muted);font-size:13px}
.tabs{display:flex;gap:6px;flex-wrap:wrap;margin-bottom:10px}.tabs button{font:inherit;
border:1px solid var(--line);background:var(--chip);color:var(--ink);border-radius:999px;
padding:5px 12px;cursor:pointer}.tabs button[aria-selected=true]{background:var(--ink);
color:var(--bg);border-color:var(--ink)}.plan{display:none}.plan.on{display:block}
table{border-collapse:collapse;width:100%;font-size:14px}th,td{text-align:left;padding:6px 8px;
border-bottom:1px solid var(--line);vertical-align:top}th{color:var(--muted);font-weight:600}
td.num,th.num{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}
.legend{display:flex;gap:16px;flex-wrap:wrap;color:var(--muted);font-size:13px;margin-top:8px}
.sw{display:inline-block;width:14px;height:10px;border-radius:2px;margin-right:6px;
vertical-align:middle}
.path{display:flex;align-items:center;flex-wrap:wrap;gap:4px;margin:4px 0}
.gate{background:var(--chip);border:1px solid var(--line);border-radius:8px;padding:4px 8px;
font-size:13px;line-height:1.3}
.gate b{display:block;font-size:14px}.gate small{color:var(--muted)}.arrow{color:var(--muted)}
.gate.weak{border-color:var(--deadline)}.fragile{color:var(--deadline);font-weight:600}
.tree ul{list-style:none;margin:0;padding-left:22px;border-left:1px dashed var(--line)}
.tree>ul{padding-left:0;border:none}.tree li{margin:6px 0}
.tree .node{display:inline-block;background:var(--chip);border:1px solid var(--line);
border-radius:8px;padding:4px 8px;font-size:13px}
.tree .yes{color:var(--ok)}.tree .no{color:var(--warn)}.note{color:var(--muted);font-size:13px}
svg text{fill:var(--ink);font-size:12px}svg .muted{fill:var(--muted)}
.tornado{max-width:560px}.tornado svg text{font-size:13px}
.tgrid{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(300px,100%),1fr));gap:16px}
.cols{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(320px,100%),1fr));gap:16px}
.cols>.panel{min-width:0}h3{font-size:15px;margin:14px 0 6px}
.file{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:13px;color:var(--muted);
overflow-wrap:anywhere}
"""

SHELL_CSS = """
.maintabs{display:none;gap:4px;flex-wrap:wrap;margin:22px 0 0;border-bottom:1px solid var(--line)}
.js .maintabs{display:flex}
.maintabs button{font:inherit;font-weight:600;color:var(--muted);background:none;border:0;
border-bottom:3px solid transparent;padding:10px 14px;cursor:pointer;min-height:44px}
.maintabs button[aria-selected=true]{color:var(--ink);border-bottom-color:var(--ink)}
.js .tabpanel{display:none}.js .tabpanel.on{display:block}
h4{font-size:14px;margin:16px 0 6px}
@media print{.maintabs,.caserail,.tabs{display:none!important}
.js .tabpanel,.js .case,.js .gatepanel,.plan{display:block!important}}
"""

JS = """
(function(){var d=document;d.documentElement.classList.add('js');
function all(s,r){return Array.prototype.slice.call((r||d).querySelectorAll(s));}
all('.tabs button').forEach(function(b){b.addEventListener('click',function(){
all('.tabs button').forEach(function(x){x.setAttribute('aria-selected','false');});
all('.plan').forEach(function(x){x.classList.remove('on');});
b.setAttribute('aria-selected','true');d.getElementById(b.dataset.plan).classList.add('on');});});
var tabs=all('.maintabs [role=tab]'),state={tab:null,cid:null,gate:null};
function showTab(id,focus){var hit=false;tabs.forEach(function(t){var on=t.dataset.tab===id;
hit=hit||on;});if(!hit)return false;tabs.forEach(function(t){var on=t.dataset.tab===id;
t.setAttribute('aria-selected',on?'true':'false');t.tabIndex=on?0:-1;
d.getElementById(t.getAttribute('aria-controls')).classList.toggle('on',on);
if(on&&focus)t.focus();});state.tab=id;return true;}
function caseOf(cid){return all('.case').filter(function(s){return s.dataset.cid===cid;})[0];}
function showGate(sec,gate){var hit=false;all('.gatebtn',sec).forEach(function(b){
hit=hit||b.dataset.gate===gate;});if(!hit)return false;
all('.gatebtn',sec).forEach(function(b){
b.setAttribute('aria-pressed',b.dataset.gate===gate?'true':'false');});
all('.gatepanel',sec).forEach(function(p){p.classList.toggle('on',p.dataset.gate===gate);});
state.gate=gate;return true;}
function showCase(cid){var sec=caseOf(cid);if(!sec)return false;
all('.casebtn').forEach(function(b){
b.setAttribute('aria-pressed',b.dataset.cid===cid?'true':'false');});
all('.case').forEach(function(s){s.classList.toggle('on',s===sec);});state.cid=cid;
var g=all('.gatebtn[aria-pressed=true]',sec)[0];state.gate=g?g.dataset.gate:null;return true;}
function save(){var h='#'+state.tab;if(state.tab==='votes'&&state.cid){
h+='/'+encodeURIComponent(state.cid);if(state.gate)h+='/'+encodeURIComponent(state.gate);}
if(history.replaceState)history.replaceState(null,'',h);}
function load(){var parts=location.hash.replace(/^#/,'').split('/').map(decodeURIComponent);
if(parts[0])showTab(parts[0]);if(parts[1]&&showCase(parts[1])&&parts[2]){
showGate(caseOf(parts[1]),parts[2]);}}
tabs.forEach(function(t,i){t.addEventListener('click',function(){showTab(t.dataset.tab);save();});
t.addEventListener('keydown',function(ev){var n=tabs.length,j=-1,k=ev.key;
if(k==='ArrowRight')j=(i+1)%n;else if(k==='ArrowLeft')j=(i+n-1)%n;else if(k==='Home')j=0;
else if(k==='End')j=n-1;if(j>=0){ev.preventDefault();
showTab(tabs[j].dataset.tab,true);save();}});});
all('.casebtn').forEach(function(b){b.addEventListener('click',function(){
showCase(b.dataset.cid);save();});});
all('.case').forEach(function(sec){all('.gatebtn',sec).forEach(function(b){
b.addEventListener('click',function(){showGate(sec,b.dataset.gate);save();});});});
var first=tabs.filter(function(t){return t.getAttribute('aria-selected')==='true';})[0];
if(first)state.tab=first.dataset.tab;var c0=all('.casebtn[aria-pressed=true]')[0];
if(c0)showCase(c0.dataset.cid);load();window.addEventListener('hashchange',load);})();
"""


def e(x: object) -> str:
    return html.escape(str(x), quote=True)


def _pct(p: float) -> str:
    return f"{100 * p:.1f}%"


def _label(res: PortfolioResult, cid: str) -> str:
    name = res.labels.get(cid)
    return f"{cid} ({name})" if name and name != cid else cid


# ----------------------------------------------------------------------- timeline


def slot_table(slots: Iterable[Slot], res: PortfolioResult) -> str:
    rows = "".join(
        f"<tr><td>{e(_label(res, s.id))}</td><td>{s.house_start} to {s.house_end}</td>"
        f"<td>{s.trial_start} to {s.trial_end}</td><td class=num>{_pct(s.p0)}"
        + (f"<br>(roster from {res.epochs[s.epoch - 1]})" if s.epoch else "")
        + "</td>"
        f"<td class=num>{_pct(s.p)}</td><td class=num>{s.weight:g}</td></tr>"
        for s in slots
    )
    return (
        "<table><tr><th>Candidate</th><th>House</th><th>Senate trial</th><th class=num>P "
        "alone</th><th class=num>P in this order</th><th class=num>Weight</th></tr>"
        f"{rows}</table>"
    )


# --------------------------------------------------------------------- gate paths


def gate_paths(res: PortfolioResult, pf: Portfolio) -> str:
    out: list[str] = []
    for c in pf.candidates:
        sim = res.gate_paths.get(c.id)
        if sim is None:
            p = res.p0.get(c.id)
            if p is not None:
                out.append(
                    f"<tr><td>{e(_label(res, c.id))}</td><td><span class=note>P "
                    f"{_pct(p)} supplied directly; no gate breakdown</span></td></tr>"
                )
            continue
        chips: list[str] = []
        optional: list[str] = []
        for g in sim.gates:
            weak = " weak" if g.p_pass_given_reached < 0.5 else ""
            chip = (
                f'<span class="gate{weak}" title="{e(GATE_LABELS.get(g.stage, g.stage))}">'
                f"<b>{e(g.stage)} {_pct(g.p_pass_given_reached)}</b>"
                f"<small>{e(GATE_LABELS.get(g.stage, ''))}<br>reached {_pct(g.p_reached)} · "
                f"median PRO {g.pro_count.p50:.0f}</small></span>"
            )
            (optional if g.stage in OPTIONAL_GATES else chips).append(chip)
        extra = (
            f'<div class="path"><span class=note>Optional, after conviction:</span>'
            f"{''.join(optional)}</div>"
            if optional
            else ""
        )
        p_rm = res.p0.get(c.id, sim.p_complete)
        art_note = (
            f"article {e(sim.article)}"
            if abs(p_rm - sim.p_complete) < 1e-12
            else f"gates for article {e(sim.article)} ({_pct(sim.p_complete)} alone), "
            "the likeliest; removal on any article"
        )
        out.append(
            f"<tr><td>{e(_label(res, c.id))}<br><span class=note>path {e(sim.path)}, "
            f"{art_note}<br>P(removal) {_pct(p_rm)}</span></td><td>"
            f'<div class="path">{"<span class=arrow>→</span>".join(chips)}</div>{extra}</td></tr>'
        )
    if not out:
        return "<p class=note>No candidates.</p>"
    return (
        "<table><tr><th>Candidate</th><th>Gates in order: chance of passing once reached "
        "(red border: under 50%)</th></tr>" + "".join(out) + "</table>"
    )


# ----------------------------------------------------------------------- pivots

PIVOT_HEADING = "Members nearest the threshold (by the supplied probabilities)"
PIVOT_NOTE = (
    "For each case built from a scenario: the members at its binding gate who are not counted PRO "
    "at the scenario cutoffs, highest supplied probability first (ties by id). The list covers the "
    "shortfall at the minimum plus five, up to 25. It restates the inputs; it is not a forecast."
)


def pivots_html(res: PortfolioResult, pf: Portfolio) -> str:
    blocks: list[str] = []
    for c in pf.candidates:
        art = res.pivots.get(c.id)
        if art is None:
            continue
        gate = next(g for g in art.gates if g.stage == art.binding_gate)
        rows = (
            "".join(
                f"<tr><td>{e(m.id)}</td><td>{e(m.name)}</td><td>{e(m.bloc)}</td>"
                f"<td class=num>{m.p:.3f}</td><td>{e(m.source)}</td></tr>"
                for m in art.pivots
            )
            or "<tr><td colspan=5 class=note>No non-PRO members at this gate.</td></tr>"
        )
        blocks.append(
            f"<h3>{e(_label(res, c.id))}</h3><p class=note>Article {e(art.article)}, path "
            f"{e(art.path)}: binding gate {e(art.binding_gate)} "
            f"({e(GATE_LABELS.get(art.binding_gate, gate.label))}); {gate.pro_min} counted PRO "
            f"of {gate.required} needed, short {gate.short_at_min} at the minimum.</p>"
            "<table><tr><th>Id</th><th>Name</th><th>Bloc</th><th class=num>p</th>"
            f"<th>Source</th></tr>{rows}</table>"
        )
    if not blocks:
        return ""
    return (
        f'<section id="pivots"><h2>{e(PIVOT_HEADING)}</h2><div class="panel">'
        f"<p class=note>{e(PIVOT_NOTE)}</p>{''.join(blocks)}</div></section>"
    )


# ----------------------------------------------------------------------- tornado

TORNADO_HEADING = "What moves each case (one notch per input)"


def tornado_svg(t: Tornado) -> str:
    """Inline SVG tornado chart: one row per input, sorted by swing, labels above the bars.

    The upper bar of each row is the input moved down a notch, the lower bar the input moved up.
    Values are printed as text so the chart does not depend on color.
    """
    w, pad, row_h, top = 400, 12, 46, 8
    vals = [t.base] + [v for b in t.bars for v in (b.p_low, b.p_high)]
    lo, hi = min(vals), max(vals)
    if hi - lo < 0.02:
        lo, hi = max(0.0, t.base - 0.01), min(1.0, t.base + 0.01)
        if hi - lo < 1e-9:
            lo, hi = lo - 0.01, hi + 0.01
    span = hi - lo
    height = top + row_h * max(1, len(t.bars)) + 34

    def x(p: float) -> float:
        return pad + (w - 2 * pad) * (p - lo) / span

    xb = x(t.base)
    parts = [
        f'<svg viewBox="0 0 {w} {height}" width="100%" role="img" '
        f'aria-label="{e(f"Tornado chart for {t.label}: P(removal) when each input moves")}">'
        f"<title>{e(t.label)}: base {_pct(t.base)}</title>"
    ]
    for i, b in enumerate(t.bars):
        y = top + i * row_h
        parts.append(
            f'<text x="{pad}" y="{y + 13}">{e(b.input)}</text>'
            f'<text x="{w - pad}" y="{y + 13}" text-anchor="end" class="muted">'
            f"{e(b.low_setting)}: {_pct(b.p_low)} · {e(b.high_setting)}: {_pct(b.p_high)}</text>"
        )
        parts.append(
            f'<line x1="{xb:.1f}" x2="{xb:.1f}" y1="{y + 17}" y2="{y + 40}" stroke="var(--ink)" '
            f'stroke-width="1.5" stroke-dasharray="3 2"/>'
        )
        for k, (p, fill, setting) in enumerate(
            ((b.p_low, "var(--house)", b.low_setting), (b.p_high, "var(--trial)", b.high_setting))
        ):
            x1, x2 = sorted((xb, x(p)))
            parts.append(
                f'<rect x="{x1:.1f}" y="{y + 19 + 10 * k}" width="{max(1.5, x2 - x1):.1f}" '
                f'height="9" rx="2" fill="{fill}"><title>{e(b.input)} {e(setting)}: '
                f"{_pct(p)}{' (' + e(b.note) + ')' if b.note else ''}</title></rect>"
            )
    yb = top + row_h * max(1, len(t.bars))
    parts.append(
        f'<line x1="{pad}" x2="{w - pad}" y1="{yb + 2}" y2="{yb + 2}" stroke="var(--line)"/>'
        f'<text x="{pad}" y="{yb + 18}" class="muted">{_pct(lo)}</text>'
        f'<text x="{w - pad}" y="{yb + 18}" text-anchor="end" class="muted">{_pct(hi)}</text>'
        f'<text x="{xb:.1f}" y="{yb + 32}" text-anchor="middle">base {_pct(t.base)}</text>'
        "</svg>"
    )
    legend = (
        '<div class="legend"><span><i class="sw" style="background:var(--house)"></i>input '
        'one notch down</span><span><i class="sw" style="background:var(--trial)"></i>input one '
        "notch up</span></div>"
    )
    notes = "".join(f"<br>{e(n)}" for n in t.notes)
    return (
        f'<div class="tornado"><h3>{e(t.id or t.label)}'
        f"{' (' + e(t.label) + ')' if t.id and t.label != t.id else ''}</h3>"
        f"<p class=note>{e(t.basis)}: {_pct(t.base)}; {t.draws:,} draws per run{notes}</p>"
        f"{''.join(parts)}{legend}</div>"
    )


def tornado_section(tornadoes: Iterable[Tornado]) -> str:
    charts = [tornado_svg(t) for t in tornadoes]
    if not charts:
        return ""
    return (
        f'<section id="tornado"><h2>{e(TORNADO_HEADING)}</h2><div class="panel">'
        f'<p class=note>{e(TORNADO_NOTE)}</p><div class="tgrid">{"".join(charts)}</div>'
        "</div></section>"
    )


# ------------------------------------------------------------------ succession


def _branch_order(node: TreeNode) -> str:
    """The order a branch works through its remaining cases, and whether it was re-ordered."""
    if not node.order:
        return ""
    tag = " (re-ordered after the verdict)" if node.reordered else ""
    return f' <span class="note">order: {e(" → ".join(node.order))}{tag}</span>'


def tree_html(node: TreeNode) -> str:
    seg = ", ".join(e(t) for t in node.tried) or "nothing new"
    if node.at == "(end)" or node.removed is None or node.not_removed is None:
        return f'<li><span class="node">Then: {seg} · expected {node.value:.2f}</span></li>'
    when = f" (verdict {node.verdict})" if node.verdict else ""
    return (
        f'<li><span class="node">Trials: {seg}. At <b>{e(node.at)}</b>{when}: removed with '
        f"P {_pct(node.p_removed)}</span><ul>"
        f'<li><span class="yes">If removed</span>{_branch_order(node.removed)}'
        f"<ul>{tree_html(node.removed)}</ul></li>"
        f'<li><span class="no">If not removed</span>{_branch_order(node.not_removed)}'
        f"<ul>{tree_html(node.not_removed)}</ul></li>"
        "</ul></li>"
    )


# --------------------------------------------------------------------- removals


def removals_svg(res: PortfolioResult) -> str:
    d = res.removals_dist
    if d is None:
        return "<p class=note>No removals distribution.</p>"
    probs = d.probabilities
    w, h, left, bottom = 520, 180, 30, 26
    bw = (w - left) / max(1, len(probs))
    top = max(probs) or 1.0
    bars = []
    for k, p in enumerate(probs):
        bh = (h - bottom - 14) * p / top
        x = left + k * bw
        bars.append(
            f'<rect x="{x + 4:.1f}" y="{h - bottom - bh:.1f}" width="{bw - 8:.1f}" '
            f'height="{bh:.1f}" rx="2" fill="var(--house)"><title>{k} removals: {_pct(p)}'
            f"</title></rect>"
            f'<text x="{x + bw / 2:.1f}" y="{h - 8}" text-anchor="middle">{k}</text>'
            f'<text x="{x + bw / 2:.1f}" y="{h - bottom - bh - 4:.1f}" text-anchor="middle" '
            f'class="muted">{_pct(p)}</text>'
        )
    notes = "".join(f"<li>{e(n)}</li>" for n in d.notes)
    return (
        f'<svg viewBox="0 0 {w} {h}" width="100%" style="max-width:{w}px" role="img" '
        f'aria-label="Distribution of the number of removals">{"".join(bars)}</svg>'
        f"<p>Mean {d.mean:.2f} removals, standard deviation {d.sd:.2f}"
        + (
            f" ({d.spread_ratio:.2f}× the spread if outcomes were independent)"
            if d.method == "joint_monte_carlo" and d.spread_ratio != 1.0
            else ""
        )
        + f". Method: {e(d.method)}"
        + (f", {d.draws:,} draws" if d.draws else "")
        + f".</p><ul class=note>{notes}</ul>"
    )


# ----------------------------------------------------------------------- page


def _plan_section(idx: str, title: str, plan: PlanOut, pf: Portfolio, res: PortfolioResult) -> str:
    return (
        f'<div class="plan" id="{idx}"><p><b>{e(title)}</b>: expected removals '
        f"{plan.expected_removals:.2f}; order {e(' → '.join(plan.order))}</p>"
        f"{plan_views(pf, plan, res)}<h3>Dates</h3>{slot_table(plan.slots, res)}"
        f"<h3>Why these dates</h3>{why_dates(pf, plan, res)}</div>"
    )


def render(res: PortfolioResult, pf: Portfolio, title: str = "Impeachment plan") -> str:
    """Return a self-contained HTML planning page for a portfolio result."""
    plans: list[tuple[str, str, PlanOut]] = []
    for i, p in enumerate(res.plans, 1):
        plans.append((f"plan{i}", f"Plan {i}", p))
    rec_value = (
        res.succession_value
        if res.succession_value is not None
        else (res.plans[0].expected_removals if res.plans else 0.0)
    )
    rec_order = res.succession_order or (res.plans[0].order if res.plans else [])
    tabs = "".join(
        f'<button data-plan="{pid}" aria-selected="{"true" if k == 0 else "false"}">'
        f"{e(name)} · {p.expected_removals:.2f}</button>"
        for k, (pid, name, p) in enumerate(plans)
    )
    sections = "".join(
        _plan_section(pid, name, p, pf, res).replace('class="plan"', 'class="plan on"', k == 0)
        for k, (pid, name, p) in enumerate(plans)
    )
    sens = "".join(
        f"<tr><td>{e(r.label)}</td><td class=num>{r.best:.2f}</td>"
        f"<td class=num>{r.base_rescheduled:.2f}</td><td class=num>{r.regret:.2f}</td><td>"
        f"{'<span class=fragile>fragile</span>' if r.fragile else 'robust'}</td></tr>"
        for r in res.sensitivity
    )
    succession = ""
    if res.decision_tree is not None:
        succession = (
            "<h2>Succession branches</h2><div class='panel tree'><p class=note>Recommended order "
            f"once removals can change later cases: {e(' → '.join(res.succession_order or []))}"
            f". Expected removals {res.succession_value or 0:.2f}. Branches differ only in work "
            "that starts after each verdict; each branch re-orders the cases not yet started "
            "when that helps.</p>"
            + (
                "<p>In this order every dependent case is tried before the case it depends on, "
                "so no removal changes a later case and the plan has no branches.</p>"
                if res.decision_tree.removed is None
                else f"<ul>{tree_html(res.decision_tree)}</ul>"
            )
            + "</div>"
        )
    data = json.dumps(res.model_dump(mode="json"), default=str).replace("</", "<\\/")
    start = "votes" if res.gates else "floor"
    names = [("votes", "Votes"), ("floor", "Floor time"), ("outcomes", "Outcomes")]
    names.append(("moves", "What moves it"))
    tablist = (
        '<div class="maintabs" role="tablist" aria-label="Page sections">'
        + "".join(
            f'<button type="button" role="tab" id="tab-{k}" data-tab="{k}" '
            f'aria-controls="panel-{k}" aria-selected="{"true" if k == start else "false"}" '
            f'tabindex="{0 if k == start else -1}">{name}</button>'
            for k, name in names
        )
        + "</div>"
    )

    def on(k: str) -> str:
        return " on" if k == start else ""

    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{e(title)}</title><style>{CSS}{SHELL_CSS}{VOTES_CSS}{FLOOR_CSS}</style></head><body><main>
<h1>{e(title)}</h1>
<p class="sub">Window {pf.start} to {pf.deadline}; {pf.house_concurrency} House
lane(s), one Senate trial at a time.</p>
<div class="kpis">
<div class="kpi"><b>{rec_value:.2f}</b><span>expected removals, recommended plan</span></div>
<div class="kpi"><b>{len(rec_order)}</b><span>cases attempted</span></div>
<div class="kpi"><b>{len(res.dropped)}</b><span>left out</span></div>
<div class="kpi"><b class="{"fragile" if res.fragile else ""}">{
        "Fragile" if res.fragile else "Robust"
    }</b><span>to fatigue and duration changes</span></div>
</div>
{tablist}
<section class="tabpanel{on("votes")}" id="panel-votes" role="tabpanel" aria-labelledby="tab-votes">
<h2>Votes</h2><div class="panel">{votes_tab(res)}</div></section>
<section class="tabpanel{on("floor")}" id="panel-floor" role="tabpanel" aria-labelledby="tab-floor">
<h2>Plans and timeline</h2><div class="panel"><div class="tabs">{tabs}</div>{sections}</div>
<h2>Left out</h2><div class="panel">{left_out_table(res)}</div></section>
<section class="tabpanel{on("outcomes")}" id="panel-outcomes" role="tabpanel"
aria-labelledby="tab-outcomes">
{succession}
<h2>Removals</h2><div class="panel">{removals_svg(res)}</div></section>
<section class="tabpanel{on("moves")}" id="panel-moves" role="tabpanel" aria-labelledby="tab-moves">
{tornado_section(res.tornado.values())}
<h2>Sensitivity</h2><div class="panel"><p class=note>Regret is the expected removals lost by keeping
the recommended order when an input changes. It is flagged fragile above max(0.01, 5% of the
best).</p><table><tr><th>Change</th><th class=num>Best</th><th class=num>Recommended order
</th><th class=num>Regret</th><th></th></tr>{sens}</table></div></section>
<script type="application/json" id="impsolver-data">{data}</script>
<script>{JS}</script></main></body></html>
"""


# ------------------------------------------------------------------- comparison

COMPARE_NOTE = (
    "Each side is computed on its own, exactly as the single-file commands would. The page only "
    "lines them up."
)


def _diff_rows(rows: list[tuple[str, float | None, float | None, str]]) -> str:
    out: list[str] = []
    for label, a, b, fmt in rows:

        def f(v: float | None, fmt: str = fmt) -> str:
            if v is None:
                return "—"
            return _pct(v) if fmt == "pct" else f"{v:.2f}"

        if a is None or b is None:
            d = "—"
        elif fmt == "pct":
            d = f"{100 * (b - a):+.1f} pts"
        else:
            d = f"{b - a:+.2f}"
        out.append(
            f"<tr><td>{e(label)}</td><td class=num>{f(a)}</td><td class=num>{f(b)}</td>"
            f"<td class=num>{d}</td></tr>"
        )
    return (
        "<table><tr><th>Measure</th><th class=num>A</th><th class=num>B</th>"
        f"<th class=num>B − A</th></tr>{''.join(out)}</table>"
    )


def _portfolio_column(tag: str, side: PortfolioSide) -> str:
    res = side.result
    in_order = {s.id: s for s in side.slots}
    left = {d.id: d for d in res.dropped}
    rows = []
    for cid, p0 in res.p0.items():
        slot = in_order.get(cid)
        status = (
            f"trial {slot.attempt + 1}: {_pct(slot.p)}"
            if slot is not None
            else (
                e(excluded_reason_text(left[cid].reason) or left[cid].reason)
                if cid in left
                else "not scheduled unless a succession rule applies"
            )
        )
        rows.append(
            f"<tr><td>{e(_label(res, cid))}</td><td class=num>{_pct(p0)}</td><td>{status}</td></tr>"
        )
    rd = res.removals_dist
    dist = (
        f"<p>Removals: mean {rd.mean:.2f}, standard deviation {rd.sd:.2f} ({e(rd.method)}).</p>"
        if rd is not None
        else ""
    )
    return (
        f'<div class="panel"><h2>{e(tag)}</h2><p class="file">{e(side.file)}</p>'
        f'<div class="kpis"><div class="kpi"><b>{side.expected_removals:.2f}</b><span>expected '
        f'removals</span></div><div class="kpi"><b>{len(side.recommended_order)}</b><span>cases '
        f'attempted</span></div><div class="kpi"><b class="{"fragile" if res.fragile else ""}">'
        f"{'Fragile' if res.fragile else 'Robust'}</b><span>to fatigue and durations</span></div>"
        f"</div><p>Order: {e(' → '.join(side.recommended_order) or 'none')}</p>{dist}"
        "<table><tr><th>Candidate</th><th class=num>P alone</th><th>In the plan</th></tr>"
        f"{''.join(rows)}</table>"
        + "".join(tornado_svg(t) for t in res.tornado.values())
        + "</div>"
    )


def _scenario_column(tag: str, side: ScenarioSide) -> str:
    parts = [
        f'<div class="panel"><h2>{e(tag)}: {e(side.target)}</h2><p class="file">{e(side.file)}'
        f"</p><p class=note>Office {e(side.office)}; composition {e(side.composition)}; "
        f"{side.simulation.draws:,} draws, rho {side.simulation.rho:g}</p>"
        f'<div class="kpis"><div class="kpi"><b>{_pct(side.p_removal)}</b><span>P(removal)'
        "</span></div></div>"
    ]
    ev = {a.article: a for a in side.evaluation.articles}
    for art in side.simulation.articles:
        det = ev.get(art.article)
        gates = "".join(
            f"<tr><td>{e(g.stage)}</td><td>{e(GATE_LABELS.get(g.stage, ''))}</td>"
            f"<td class=num>{_pct(g.p_reached)}</td><td class=num>{_pct(g.p_pass_given_reached)}"
            f"</td><td class=num>{g.pro_count.p50:.0f}</td></tr>"
            for g in art.gates
        )
        verdict = (
            f"; deterministic {e(det.verdict)}, binding gate {e(det.binding_gate)}"
            if det is not None
            else ""
        )
        parts.append(
            f"<h3>Article {e(art.article)}, path {e(art.path)}</h3><p class=note>P(complete) "
            f"{_pct(art.p_complete)}{verdict}</p><table><tr><th>Gate</th><th>Vote</th>"
            "<th class=num>Reached</th><th class=num>Pass if reached</th><th class=num>Median "
            f"PRO</th></tr>{gates}</table>"
        )
    parts.append(tornado_svg(side.tornado) + "</div>")
    return "".join(parts)


def _summary(cmp: Comparison) -> str:
    a, b = cmp.a, cmp.b
    rows: list[tuple[str, float | None, float | None, str]] = []
    if isinstance(a, PortfolioSide) and isinstance(b, PortfolioSide):
        ra, rb = a.result, b.result
        rows.append(
            ("Expected removals, recommended plan", a.expected_removals, b.expected_removals, "num")
        )
        rows.append(
            (
                "Cases attempted",
                float(len(a.recommended_order)),
                float(len(b.recommended_order)),
                "num",
            )
        )
        rows.append(("Left out", float(len(ra.dropped)), float(len(rb.dropped)), "num"))
        for cid in list(dict.fromkeys([*ra.p0, *rb.p0])):
            rows.append((f"P alone: {cid}", ra.p0.get(cid), rb.p0.get(cid), "pct"))
    elif isinstance(a, ScenarioSide) and isinstance(b, ScenarioSide):
        rows.append(("P(removal)", a.p_removal, b.p_removal, "pct"))
        pa = {x.article: x.p_complete for x in a.simulation.articles}
        pb = {x.article: x.p_complete for x in b.simulation.articles}
        for art in list(dict.fromkeys([*pa, *pb])):
            rows.append((f"Article {art}: P(complete)", pa.get(art), pb.get(art), "pct"))
    return _diff_rows(rows)


def render_comparison(cmp: Comparison, title: str = "Plan comparison") -> str:
    """Return a self-contained HTML page with two portfolios or two scenarios side by side."""
    cols = "".join(
        _portfolio_column(tag, side)
        if isinstance(side, PortfolioSide)
        else _scenario_column(tag, side)
        for tag, side in (("A", cmp.a), ("B", cmp.b))
    )
    data = json.dumps(cmp.model_dump(mode="json"), default=str).replace("</", "<\\/")
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{e(title)}</title><style>{CSS}</style></head><body><main>
<h1>{e(title)}</h1>
<p class="sub">{e(COMPARE_NOTE)}</p>
<p class="file">A: {e(cmp.a.file)}<br>B: {e(cmp.b.file)}</p>
<h2>Summary</h2><div class="panel">{_summary(cmp)}</div>
<h2>Side by side</h2><p class=note>{e(tornado_note(cmp.kind == "portfolio"))}</p>
<div class="cols">{cols}</div>
<script type="application/json" id="impsolver-data">{data}</script>
</main></body></html>
"""
