# SPDX-FileCopyrightText: 2026 Justin Stanley
# SPDX-License-Identifier: MIT
"""Self-contained HTML planning report for a portfolio result.

The page shows only what the user supplied and what the solver computed from it: the plans, the
timeline of House and Senate work, each case's gate-by-gate odds, succession branches, the
removals distribution, the members nearest each binding gate's threshold, sensitivity, and why
candidates were left out. It never adds targets.
"""

from __future__ import annotations

import datetime as dt
import html
import json
from collections.abc import Iterable

from .model import Portfolio
from .portfolio import PlanOut, PortfolioResult, Slot, TreeNode, excluded_reason_text

OPTIONAL_GATES = {"S3"}
NEUTRALITY = "Plans cover only the candidates you supplied. impsolver does not nominate targets."
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
td.num,th.num{text-align:right;font-variant-numeric:tabular-nums}
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
"""

JS = """
document.querySelectorAll('.tabs button').forEach(b=>b.addEventListener('click',()=>{
document.querySelectorAll('.tabs button').forEach(x=>x.setAttribute('aria-selected','false'));
document.querySelectorAll('.plan').forEach(x=>x.classList.remove('on'));
b.setAttribute('aria-selected','true');document.getElementById(b.dataset.plan).classList.add('on');}));
"""


def e(x: object) -> str:
    return html.escape(str(x), quote=True)


def _pct(p: float) -> str:
    return f"{100 * p:.1f}%"


def _label(res: PortfolioResult, cid: str) -> str:
    name = res.labels.get(cid)
    return f"{cid} ({name})" if name and name != cid else cid


# ----------------------------------------------------------------------- timeline


def _recess_bands(pf: Portfolio) -> list[tuple[dt.date, dt.date, str]]:
    out = [(a, b, "House") for a, b in pf.calendar.house.recess]
    out += [(a, b, "Senate") for a, b in pf.calendar.senate.recess]
    return out


def timeline_svg(pf: Portfolio, slots: Iterable[Slot], res: PortfolioResult) -> str:
    slots = sorted(slots, key=lambda s: s.house_start)
    start = pf.start
    last = max((s.trial_end for s in slots), default=pf.start)
    # Zoom to the planned work; the session deadline is drawn only when it is in view.
    end = min(max(pf.deadline, last), last + dt.timedelta(days=60))
    span = max(1, (end - start).days)
    left, width, row_h, top = 230, 860, 34, 30
    height = top + row_h * max(1, len(slots)) + 30

    def x(d: dt.date) -> float:
        return left + width * (d - start).days / span

    parts = [
        f'<svg viewBox="0 0 {left + width + 20} {height}" width="100%" style="min-width:760px" '
        f'role="img" '
        f'aria-label="Timeline of House and Senate work per candidate">'
    ]
    for a, b, who in _recess_bands(pf):
        if b < start or a > end:
            continue
        a2, b2 = max(a, start), min(b, end)
        parts.append(
            f'<rect x="{x(a2):.1f}" y="{top - 6}" width="{max(1, x(b2) - x(a2)):.1f}" '
            f'height="{height - top - 18}" fill="var(--recess)"><title>{e(who)} recess '
            f"{a}..{b}</title></rect>"
        )
    # month ticks
    d = dt.date(start.year, start.month, 1)
    first = True
    while d <= end:
        if first:
            parts.append(
                f'<text x="{left}" y="{top - 12}" class="muted">{start.strftime("%b %Y")}</text>'
            )
            first = False
        elif d >= start:
            parts.append(
                f'<line x1="{x(d):.1f}" x2="{x(d):.1f}" y1="{top - 8}" y2="{height - 22}" '
                f'stroke="var(--line)"/>'
            )
            if span < 400 or d.month in (1, 4, 7, 10):
                parts.append(
                    f'<text x="{x(d) + 3:.1f}" y="{top - 12}" class="muted">'
                    f"{d.strftime('%b %Y')}</text>"
                )
        d = dt.date(d.year + (d.month == 12), d.month % 12 + 1, 1)
    if pf.deadline <= end:
        xd = x(pf.deadline)
        parts.append(
            f'<line x1="{xd:.1f}" x2="{xd:.1f}" y1="{top - 8}" y2="{height - 22}" '
            f'stroke="var(--deadline)" stroke-width="2" stroke-dasharray="4 3"/>'
            f'<text x="{xd - 4:.1f}" y="{height - 8}" text-anchor="end" fill="var(--deadline)">'
            f"deadline {pf.deadline}</text>"
        )
    else:
        parts.append(
            f'<text x="{left + width}" y="{height - 8}" text-anchor="end" class="muted">'
            f"session deadline {pf.deadline} is past the right edge</text>"
        )
    cands = {c.id: c for c in pf.candidates}
    for i, s in enumerate(slots):
        y = top + i * row_h
        c = cands[s.id]
        parts.append(
            f'<text x="{left - 10}" y="{y + 15}" text-anchor="end">{e(_label(res, s.id))}</text>'
            f'<text x="{left - 10}" y="{y + 28}" text-anchor="end" class="muted">'
            f"P {_pct(s.p)}{' (fatigued from ' + _pct(s.p0) + ')' if s.p != s.p0 else ''}"
            f"</text>"
        )
        h1, h2 = x(s.house_start), x(s.house_end + dt.timedelta(days=1))
        parts.append(
            f'<rect x="{h1:.1f}" y="{y + 4}" width="{max(2, h2 - h1):.1f}" height="18" rx="3" '
            f'fill="var(--house)"><title>{e(s.id)}: House {s.house_start}..{s.house_end}'
            f"</title></rect>"
        )
        if c.senate_committee:
            com_start = s.house_end + dt.timedelta(days=1)
            com_end = s.trial_start - dt.timedelta(days=1)
            if com_end >= com_start:
                c1, c2 = x(com_start), x(com_end + dt.timedelta(days=1))
                parts.append(
                    f'<rect x="{c1:.1f}" y="{y + 7}" width="{max(2, c2 - c1):.1f}" height="12" '
                    f'rx="3" fill="var(--committee)"><title>{e(s.id)}: Senate committee and '
                    f"wait {com_start}..{com_end}</title></rect>"
                )
        else:
            w1, w2 = h2, x(s.trial_start)
            if w2 > w1 + 1:
                parts.append(
                    f'<line x1="{w1:.1f}" x2="{w2:.1f}" y1="{y + 13}" y2="{y + 13}" '
                    f'stroke="var(--wait)" stroke-width="2" stroke-dasharray="2 3">'
                    f"<title>waiting for the Senate</title></line>"
                )
        t1, t2 = x(s.trial_start), x(s.trial_end + dt.timedelta(days=1))
        parts.append(
            f'<rect x="{t1:.1f}" y="{y + 4}" width="{max(2, t2 - t1):.1f}" height="18" rx="3" '
            f'fill="var(--trial)"><title>{e(s.id)}: Senate trial {s.trial_start}..{s.trial_end}'
            f"</title></rect>"
        )
        if c.deadline and c.deadline <= end:
            xc = x(c.deadline)
            parts.append(
                f'<path d="M{xc - 4:.1f},{y + 1} h8 l-4,6 z" fill="var(--deadline)">'
                f"<title>{e(s.id)} deadline {c.deadline}</title></path>"
            )
    parts.append("</svg>")
    legend = (
        '<div class="legend"><span><i class="sw" style="background:var(--house)"></i>House '
        'work</span><span><i class="sw" style="background:var(--committee)"></i>Senate committee'
        '</span><span><i class="sw" style="background:var(--trial)"></i>Senate trial</span>'
        '<span><i class="sw" style="background:var(--recess)"></i>Recess</span>'
        '<span><i class="sw" style="background:var(--deadline)"></i>Deadline</span></div>'
    )
    return "".join(parts) + legend


def slot_table(slots: Iterable[Slot], res: PortfolioResult) -> str:
    rows = "".join(
        f"<tr><td>{e(_label(res, s.id))}</td><td>{s.house_start} to {s.house_end}</td>"
        f"<td>{s.trial_start} to {s.trial_end}</td><td class=num>{_pct(s.p0)}</td>"
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


# ------------------------------------------------------------------ succession


def tree_html(node: TreeNode) -> str:
    seg = ", ".join(e(t) for t in node.tried) or "nothing new"
    if node.at == "(end)" or node.removed is None or node.not_removed is None:
        return f'<li><span class="node">Then: {seg} · expected {node.value:.2f}</span></li>'
    when = f" (verdict {node.verdict})" if node.verdict else ""
    return (
        f'<li><span class="node">Trials: {seg}. At <b>{e(node.at)}</b>{when}: removed with '
        f"P {_pct(node.p_removed)}</span><ul>"
        f'<li><span class="yes">If removed</span><ul>{tree_html(node.removed)}</ul></li>'
        f'<li><span class="no">If not removed</span><ul>{tree_html(node.not_removed)}</ul></li>'
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
        f"{timeline_svg(pf, plan.slots, res)}<h3>Dates</h3>{slot_table(plan.slots, res)}</div>"
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
    dropped = (
        "".join(
            f"<tr><td>{e(_label(res, d.id))}</td><td>{e(d.reason)}</td><td>"
            f"{e(excluded_reason_text(d.reason))} ({e(d.detail)})</td></tr>"
            for d in res.dropped
        )
        or "<tr><td colspan=3 class=note>Every candidate is in the recommended plan.</td></tr>"
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
            "that starts after each verdict.</p>"
            + (
                "<p>In this order every dependent case is tried before the case it depends on, "
                "so no removal changes a later case and the plan has no branches.</p>"
                if res.decision_tree.removed is None
                else f"<ul>{tree_html(res.decision_tree)}</ul>"
            )
            + "</div>"
        )
    data = json.dumps(res.model_dump(mode="json"), default=str).replace("</", "<\\/")
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{e(title)}</title><style>{CSS}</style></head><body><main>
<h1>{e(title)}</h1>
<p class="sub">{e(NEUTRALITY)} Window {pf.start} to {pf.deadline}; {pf.house_concurrency} House
lane(s), one Senate trial at a time.</p>
<div class="kpis">
<div class="kpi"><b>{rec_value:.2f}</b><span>expected removals, recommended plan</span></div>
<div class="kpi"><b>{len(rec_order)}</b><span>cases attempted</span></div>
<div class="kpi"><b>{len(res.dropped)}</b><span>left out</span></div>
<div class="kpi"><b class="{"fragile" if res.fragile else ""}">{
        "Fragile" if res.fragile else "Robust"
    }</b><span>to fatigue and duration changes</span></div>
</div>
<h2>Plans and timeline</h2><div class="panel"><div class="tabs">{tabs}</div>{sections}</div>
<h2>Gate paths</h2><div class="panel">{gate_paths(res, pf)}</div>
{pivots_html(res, pf)}
{succession}
<h2>Removals</h2><div class="panel">{removals_svg(res)}</div>
<h2>Left out</h2><div class="panel"><table><tr><th>Candidate</th><th>Reason</th><th>Detail</th>
</tr>{dropped}</table></div>
<h2>Sensitivity</h2><div class="panel"><p class=note>Regret is the expected removals lost by keeping
the recommended order when an input changes. It is flagged fragile above max(0.01, 5% of the
best).</p><table><tr><th>Change</th><th class=num>Best</th><th class=num>Recommended order
</th><th class=num>Regret</th><th></th></tr>{sens}</table></div>
<script type="application/json" id="impsolver-data">{data}</script>
<script>{JS}</script></main></body></html>
"""
