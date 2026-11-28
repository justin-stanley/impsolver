# SPDX-FileCopyrightText: 2026 Justin Stanley
# SPDX-License-Identifier: MIT
"""The Votes tab of the planning page: one gate at a time, as a count against a line.

For each scenario case the tab draws a gate ladder (how much of the probability survives to each
gate), and for each gate a tally strip (who is counted, who is uncertain, how many are needed),
a table by bloc, a member strip (every member by supplied probability, with the rank pivot) and
the threshold as members go absent. Everything is drawn from the report's ``gates``,
``gate_paths`` and ``pivots``. It restates the inputs and the simulation; it suggests no one.
"""

from __future__ import annotations

import html
from collections import Counter

from .contract import CaseGates, GateDetail
from .model import ThresholdRule
from .portfolio import PortfolioResult
from .results import SimGate
from .thresholds import required_pro
from .views_whatif import WHATIF_BAR, gate_whatif

MEMBER_HEADING = "Members nearest the threshold (by the supplied probabilities)"
MEMBER_NOTE = (
    "Every member at this gate, most to least likely PRO by the supplied probability (ties by "
    "id). The rank pivot is the member whose vote would reach the threshold if members voted in "
    "that order. It restates the inputs; it is not a forecast."
)
GATE_NAMES = {
    "H1": "House: motion to table fails",
    "H2": "House: article adopted",
    "S1": "Senate: motion to dismiss fails",
    "S2": "Senate: conviction (2/3)",
    "S3": "Senate: disqualification",
}
CLASS_WORDS = {"P": "counted PRO", "U": "uncertain", "C": "counted CON", "A": "absent"}
GROUP_MIN = 4  # identical neighbours in the member list are folded into one row from this size
ABSENCE_STEPS = 6

VOTES_CSS = """
.caserail{display:flex;gap:6px;flex-wrap:wrap;margin:0 0 14px}
.caserail button,.ladder button{font:inherit;color:var(--ink);cursor:pointer}
.caserail button{border:1px solid var(--line);background:var(--chip);border-radius:999px;
padding:5px 12px}.caserail button[aria-pressed=true]{background:var(--ink);color:var(--bg);
border-color:var(--ink)}
.js .case{display:none}.js .case.on{display:block}
.js .gatepanel{display:none}.js .gatepanel.on{display:block}
.case+.case,.gatepanel+.gatepanel{margin-top:28px}
.ladder{list-style:none;display:flex;flex-wrap:wrap;gap:8px;margin:10px 0 16px;padding:0}
.ladder li{flex:1 1 150px;min-width:140px}
.ladder button{display:block;width:100%;text-align:left;background:var(--panel);
border:1px solid var(--line);border-radius:8px;padding:8px 10px;min-height:44px}
.ladder button[aria-pressed=true]{border:2px solid var(--house);padding:7px 9px;
background:var(--chip)}
.ladder b{display:block}.ladder small{display:block;color:var(--muted);font-size:13px}
.ladder .tag{display:inline-block;font-size:12px;border:1px solid var(--ink);border-radius:4px;
padding:0 4px;margin-left:4px;font-weight:600}
.surv{display:block;height:6px;border-radius:3px;border:1px solid var(--line);margin-top:6px}
.surv i{display:block;height:100%;border-radius:3px;background:var(--house)}
.rule{margin:4px 0 10px}.facts{margin:6px 0 12px}
.vgrid{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(520px,100%),1fr));gap:18px}
.vgrid>div{min-width:0;overflow-x:auto}.scrollx{overflow-x:auto}
.scrollx svg{max-width:920px}.halo{paint-order:stroke;stroke:var(--recess);stroke-width:4px}
.pivotrow td{font-weight:600}.memlist summary{cursor:pointer;margin:8px 0}
.memlist details details{margin:2px 0}.key{display:flex;gap:14px;flex-wrap:wrap;font-size:13px;
color:var(--muted);margin:6px 0}
.key svg{vertical-align:middle;margin-right:5px}
:focus-visible{outline:2px solid var(--house);outline-offset:2px}
.src{display:inline-block;font-size:11px;line-height:16px;padding:0 5px;border-radius:4px;
border:1px solid var(--muted);color:var(--ink);text-transform:uppercase;letter-spacing:.03em}
.src.counted{background:var(--chip)}.src.simulated{border-style:dashed}
.halo2{paint-order:stroke;stroke:var(--panel);stroke-width:4px}
"""


def e(x: object) -> str:
    return html.escape(str(x), quote=True)


def pct(p: float, se: float | None = None) -> str:
    """A percentage. With a standard error over half a point it is rounded to a whole percent,
    so the page never prints more digits than the simulation supports."""
    if se is not None and se > 0.005:
        return f"{100 * p:.0f}%"
    return f"{100 * p:.1f}%"


def tag(kind: str) -> str:
    """A small label saying where a number comes from: supplied, counted or simulated."""
    return f'<span class="src {kind}">{kind}</span>'


def in_100(p: float) -> str:
    """A frequency wording for a probability: 'about 28 in 100'."""
    n = round(100 * p)
    if 0 < p < 0.005:
        return "fewer than 1 in 100"
    if 0.995 <= p < 1:
        return "more than 99 in 100"
    return f"about {n} in 100"


def gate_name(stage: str, label: str = "") -> str:
    return GATE_NAMES.get(stage, f"{stage}: {label}" if label else stage)


# ---------------------------------------------------------------------- ladder


def ladder(cid_key: str, case: CaseGates, sims: dict[str, SimGate], binding: str) -> str:
    """The gates in path order, as buttons that pick the gate shown below."""
    items: list[str] = []
    for g in case.gates:
        sim = sims.get(g.stage)
        tags = ""
        if g.stage == binding:
            tags += '<span class="tag">binding</span>'
        lines = f"<small>{e(gate_name(g.stage, g.label))}</small>"
        bar = ""
        if sim is not None:
            reach = sim.p_reached
            lines += f"<small>reached: {pct(reach)}</small>"
            passes = pct(sim.p_pass_given_reached, sim.pass_se)
            if g.optional:
                lines += f"<small>Optional, after conviction; then passes: {passes}</small>"
            else:
                weak = sim.p_pass_given_reached < 0.5
                lines += f"<small>then passes: {passes}{' (under 50%)' if weak else ''}</small>"
            bar = f'<span class="surv"><i style="width:{100 * reach:.1f}%"></i></span>'
        pressed = "true" if g.stage == binding else "false"
        items.append(
            f'<li><button type="button" class="gatebtn" data-gate="{e(g.stage)}" '
            f'aria-pressed="{pressed}" aria-controls="{cid_key}-{e(g.stage)}">'
            f"<b>{e(g.stage)}{tags}</b>{lines}{bar}</button></li>"
        )
    return f'<ol class="ladder" aria-label="Gates in order">{"".join(items)}</ol>'


# ----------------------------------------------------------------- tally strip

DECISIVE_NOTE = (
    " Decisive share is simulated: the share of all draws in which this gate's result would "
    "flip if that one member's vote flipped."
)

KEY = (
    '<div class="key" aria-hidden="true">'
    '<span><svg width="18" height="12"><rect width="18" height="12" fill="var(--house)"/></svg>'
    "counted PRO</span>"
    '<span><svg width="18" height="12"><rect x="1" y="1" width="16" height="10" fill="none" '
    'stroke="var(--ink)" stroke-dasharray="4 3"/></svg>uncertain</span>'
    '<span><svg width="18" height="12"><rect width="18" height="12" fill="var(--muted)"/></svg>'
    "counted CON</span>"
    '<span><svg width="18" height="12"><rect x="1" y="1" width="16" height="10" fill="none" '
    'stroke="var(--muted)" stroke-dasharray="1 3"/></svg>absent or vacant</span></div>'
)

_SEG_STYLE = {
    "P": 'fill="var(--house)" stroke="var(--panel)"',
    "U": 'fill="none" stroke="var(--ink)" stroke-dasharray="4 3"',
    "C": 'fill="var(--muted)" stroke="var(--panel)"',
    "A": 'fill="none" stroke="var(--muted)" stroke-dasharray="1 3"',
}
_SEG_TEXT = {"P": "var(--bg)", "U": "var(--ink)", "C": "var(--bg)", "A": "var(--muted)"}


def _segments(g: GateDetail) -> list[tuple[str, str, int]]:
    """(class letter, bloc, count) in strip order: PRO, uncertain, CON, absent, vacant."""
    out: list[tuple[str, str, int]] = []
    for letter, field in (("P", "pro"), ("U", "uncertain"), ("C", "con"), ("A", "absent")):
        out += [(letter, b.bloc, getattr(b, field)) for b in g.blocs if getattr(b, field)]
    if g.vacancies:
        out.append(("A", "vacant", g.vacancies))
    return out


def tally_summary(g: GateDetail) -> str:
    pro = sum(b.pro for b in g.blocs)
    unc = sum(b.uncertain for b in g.blocs)
    con = sum(b.con for b in g.blocs)
    absent = sum(b.absent for b in g.blocs)
    gap = g.required - pro
    if gap > 0:
        where = f"{gap} short at the minimum"
    else:
        where = f"{-gap} over the line at the minimum" if gap < 0 else "exactly at the line"
    text = f"{pro} counted PRO, {unc} uncertain, {con} counted CON"
    if absent or g.vacancies:
        text += f", {absent} absent, {g.vacancies} vacant"
    return f"{text}; {g.required} needed; {where}."


def tally_svg(g: GateDetail, sim: SimGate | None) -> str:
    """One bar with one unit per seat, the threshold line, and the simulated range."""
    left, span, y, h = 12.0, 736.0, 44.0, 34.0
    seats = max(1, g.seats)

    def x(n: float) -> float:
        return left + span * n / seats

    parts: list[str] = []
    at = 0
    for letter, bloc, n in _segments(g):
        x0, x1 = x(at), x(at + n)
        word = "vacant" if bloc == "vacant" else f"{bloc} {CLASS_WORDS[letter]}"
        parts.append(
            f'<rect x="{x0 + 0.5:.1f}" y="{y}" width="{max(1.0, x1 - x0 - 1):.1f}" height="{h}" '
            f"{_SEG_STYLE[letter]}><title>{n} {e(word)}</title></rect>"
        )
        label = f"{n} {bloc}"
        if x1 - x0 >= 7.2 * len(label) + 10:
            parts.append(
                f'<text x="{(x0 + x1) / 2:.1f}" y="{y + h / 2 + 4:.1f}" text-anchor="middle" '
                f'style="fill:{_SEG_TEXT[letter]}">{e(label)}</text>'
            )
        at += n
    pro = sum(b.pro for b in g.blocs)
    need = min(g.required, seats)
    xn = x(need)
    anchor = "start" if xn < 120 else "end" if xn > left + span - 120 else "middle"
    parts.append(
        f'<line x1="{xn:.1f}" x2="{xn:.1f}" y1="{y - 12}" y2="{y + h + 8}" stroke="var(--ink)" '
        f'stroke-width="2.5"/><text x="{xn:.1f}" y="{y - 18}" text-anchor="{anchor}" '
        f'style="font-weight:600">{g.required} needed</text>'
    )
    if g.required > pro:
        xa = x(pro)
        mid_anchor = "end" if xn > 200 else "start"
        tx = xn - 6 if mid_anchor == "end" else xa + 6
        parts.append(
            f'<path d="M{xa:.1f} {y + h + 6}v6H{xn:.1f}v-6" fill="none" stroke="var(--muted)"/>'
            f'<text x="{tx:.1f}" y="{y + h + 28}" text-anchor="{mid_anchor}">'
            f"{g.required - pro} short at the minimum</text>"
        )
    height = y + h + 40
    if sim is not None:
        c = sim.pro_count_reached or sim.pro_count
        wy = height + 8
        parts.append(
            f"<g><title>Simulated PRO count: median {c.p50:.0f}, 5 to 95% range {c.p5:.0f} to "
            f'{c.p95:.0f}</title><line x1="{x(c.p5):.1f}" x2="{x(c.p95):.1f}" y1="{wy}" y2="{wy}" '
            f'stroke="var(--ink)" stroke-width="1.5"/>'
            f'<line x1="{x(c.p5):.1f}" x2="{x(c.p5):.1f}" y1="{wy - 5}" y2="{wy + 5}" '
            f'stroke="var(--ink)" stroke-width="1.5"/>'
            f'<line x1="{x(c.p95):.1f}" x2="{x(c.p95):.1f}" y1="{wy - 5}" y2="{wy + 5}" '
            f'stroke="var(--ink)" stroke-width="1.5"/>'
            f'<circle cx="{x(c.p50):.1f}" cy="{wy}" r="5" fill="var(--ink)"/></g>'
        )
        height = wy + 14
    ticks = sorted({0, seats // 4, seats // 2, 3 * seats // 4, seats})
    ty = height + 14
    for t in ticks:
        a = "start" if t == 0 else "end" if t == seats else "middle"
        parts.append(f'<text x="{x(t):.1f}" y="{ty}" text-anchor="{a}" class="muted">{t}</text>')
    label = f"Tally at {g.stage}: {tally_summary(g)}"
    return (
        f'<div class="scrollx"><svg viewBox="0 0 760 {ty + 8:.0f}" width="100%" '
        f'style="min-width:520px" role="img" aria-label="{e(label)}">{"".join(parts)}</svg></div>'
    )


def count_curve(g: GateDetail, sim: SimGate | None) -> str:
    """Histogram of the simulated PRO count over the draws that reach the gate.

    It shares the tally strip's seat scale. Bars at or past the threshold are filled; the share
    on each side is stated as a frequency.
    """
    if sim is None or sim.pro_hist is None or not sim.pro_hist.counts:
        return ""
    hist = sim.pro_hist
    left, span, base, tall = 12.0, 736.0, 124.0, 84.0
    seats = max(1, g.seats)
    unit = span / seats
    most = max(hist.counts)
    total = sum(hist.counts)
    bars: list[str] = []
    for i, n in enumerate(hist.counts):
        if not n:
            continue
        k = hist.start + i
        hgt = max(1.0, tall * n / most)
        style = (
            'fill="var(--house)"' if k >= g.required else 'fill="var(--muted)" fill-opacity="0.55"'
        )
        bars.append(
            f'<rect x="{left + unit * (k - 0.5):.1f}" y="{base - hgt:.1f}" '
            f'width="{max(1.0, unit - 0.6):.1f}" height="{hgt:.1f}" {style}/>'
        )
    xn = left + unit * (min(g.required, seats) - 0.5)
    hit = sim.p_pass_given_reached
    miss_words = f"{in_100(1 - hit)} fall short"
    hit_words = f"{in_100(hit)} get there"
    label = (
        f"Simulated PRO count at {g.stage} over the {total} draws that reach it: "
        f"{hit_words}, {miss_words}."
    )
    if xn < 250:
        words = (
            f'<text x="{xn + 8:.1f}" y="14" style="font-weight:600" class="halo2">'
            f'{e(hit_words)}</text><text x="{xn + 8:.1f}" y="30" class="halo2">'
            f"{e(miss_words)}</text>"
        )
    else:
        words = (
            f'<text x="{xn + 8:.1f}" y="14" style="font-weight:600" class="halo2">'
            f'{e(hit_words)}</text><text x="{xn - 8:.1f}" y="14" text-anchor="end" '
            f'class="halo2">{e(miss_words)}</text>'
        )
    return (
        "<h4>How often the count gets there</h4>"
        f'<div class="scrollx"><svg viewBox="0 0 760 {base + 22:.0f}" width="100%" '
        f'style="min-width:520px" role="img" aria-label="{e(label)}">{"".join(bars)}'
        f'<line x1="{left}" x2="{left + span}" y1="{base}" y2="{base}" stroke="var(--muted)"/>'
        f'<line x1="{xn:.1f}" x2="{xn:.1f}" y1="20" y2="{base}" '
        f'stroke="var(--ink)" stroke-width="2.5"/>{words}'
        f'<text x="{xn:.1f}" y="{base + 16}" text-anchor="middle" style="font-weight:600">'
        f"{g.required}</text></svg></div>"
        f"<p class=note>{tag('simulated')} One bar per PRO count, on the same scale as the strip "
        f"above, over the {total:,} draws that reach this gate. Bloc swings move many members "
        "together, so the shape can have two humps and a single average would mislead.</p>"
    )


def bloc_table(g: GateDetail) -> str:
    rows = "".join(
        f"<tr><th scope=row>{e(b.bloc)}</th><td class=num>{b.seats}</td><td class=num>{b.pro}</td>"
        f"<td class=num>{b.uncertain}</td><td class=num>{b.con}</td><td class=num>{b.absent}</td>"
        f"<td class=num>{b.expected_pro:.1f}</td></tr>"
        for b in g.blocs
    )
    tot = [sum(getattr(b, k) for b in g.blocs) for k in ("seats", "pro", "uncertain", "con")]
    absent = sum(b.absent for b in g.blocs)
    exp = sum(b.expected_pro for b in g.blocs)
    rows += (
        f"<tr><th scope=row>Total</th><td class=num>{tot[0]}</td><td class=num>{tot[1]}</td>"
        f"<td class=num>{tot[2]}</td><td class=num>{tot[3]}</td><td class=num>{absent}</td>"
        f"<td class=num>{exp:.1f}</td></tr>"
    )
    vac = f" {g.vacancies} seat(s) are vacant and in no row." if g.vacancies else ""
    return (
        "<table><caption class=note style='text-align:left'>Count by bloc at the scenario "
        f"cutoffs. Expected PRO is the sum of the supplied probabilities.{vac}</caption>"
        "<tr><th scope=col>Bloc</th><th scope=col class=num>Members</th>"
        "<th scope=col class=num>Counted PRO</th><th scope=col class=num>Uncertain</th>"
        "<th scope=col class=num>Counted CON</th><th scope=col class=num>Absent</th>"
        f"<th scope=col class=num>Expected PRO</th></tr>{rows}</table>"
    )


# ---------------------------------------------------------------- member strip


def _ranked(g: GateDetail, case: CaseGates) -> list[int]:
    """Present members, most to least likely PRO (ties by id); absent members last."""
    ids = case.rosters[g.chamber].ids
    present = sorted((i for i, k in enumerate(g.cls) if k != "A"), key=lambda i: (-g.p[i], ids[i]))
    absent = [i for i, k in enumerate(g.cls) if k == "A"]
    return present + absent


def member_svg(g: GateDetail, case: CaseGates, cutoffs: tuple[float, float]) -> str:
    """Members stacked by supplied probability, with the cutoffs and the rank pivot."""
    roster = case.rosters[g.chamber]
    lo, hi = cutoffs
    left, span, base, tall = 40.0, 680.0, 150.0, 84.0

    def x(p: float) -> float:
        return left + span * p

    bins: dict[int, list[int]] = {}
    for i, k in enumerate(g.cls):
        if k != "A":
            bins.setdefault(round(100 * g.p[i]), []).append(i)
    most = max((len(v) for v in bins.values()), default=1)
    parts = [
        f'<rect x="{x(lo):.1f}" y="{base - tall - 26}" width="{x(hi) - x(lo):.1f}" '
        f'height="{tall + 26}" fill="var(--recess)"/>'
    ]
    for cut in (lo, hi):
        parts.append(
            f'<line x1="{x(cut):.1f}" x2="{x(cut):.1f}" y1="{base - tall - 26}" y2="{base}" '
            f'stroke="var(--muted)" stroke-dasharray="4 4"/>'
        )
    zones = [
        (lo / 2, "CON"),
        ((lo + hi) / 2, "uncertain: between the cutoffs"),
        ((1 + hi) / 2, "PRO"),
    ]
    for zp, word in zones:
        parts.append(
            f'<text x="{x(zp):.1f}" y="{base - tall - 32}" text-anchor="middle" class="muted">'
            f"{word}</text>"
        )
    pivot_i = roster.ids.index(g.rank_pivot) if g.rank_pivot in roster.ids else None
    for b, idx in sorted(bins.items()):
        hgt = max(3.0, tall * len(idx) / most)
        kinds = Counter(g.cls[i] for i in idx)
        letter = kinds.most_common(1)[0][0]
        blocs = Counter(roster.blocs[i] for i in idx)
        who = ", ".join(f"{n} {bl}" for bl, n in blocs.most_common())
        parts.append(
            f'<rect x="{x(b / 100) - 4:.1f}" y="{base - hgt:.1f}" width="8" height="{hgt:.1f}" '
            f"{_SEG_STYLE[letter]}><title>{e(who)} at {b / 100:.2f}: {CLASS_WORDS[letter]}"
            "</title></rect>"
        )
    # Name the three largest stacks, staggered so the labels do not collide.
    big = sorted(bins.items(), key=lambda kv: (-len(kv[1]), kv[0]))[:3]
    for row, (b, idx) in enumerate(sorted(big)):
        blocs = Counter(roster.blocs[i] for i in idx)
        who = ", ".join(f"{n} {bl}" for bl, n in blocs.most_common(2))
        if len(blocs) > 2:
            who = f"{len(idx)} members"
        right = b >= 50
        tx = x(b / 100) + (-10 if right else 10)
        parts.append(
            f'<text x="{tx:.1f}" y="{base - tall + 4 + 16 * row:.1f}" '
            f'text-anchor="{"end" if right else "start"}" class="halo">{e(who)} at '
            f"{b / 100:.2f}</text>"
        )
    if pivot_i is not None:
        px = x(round(100 * g.p[pivot_i]) / 100)
        parts.append(
            f'<path d="M{px:.1f} {base + 4}l6 9h-12z" fill="var(--ink)"><title>rank pivot: '
            f"{e(roster.ids[pivot_i])}</title></path>"
            f'<text x="{px:.1f}" y="{base + 40}" text-anchor="'
            f'{"end" if px > 560 else "start" if px < 200 else "middle"}" style="font-weight:600">'
            f"rank pivot: vote {g.required} of {g.required} needed, at "
            f"{g.p[pivot_i]:.2f}</text>"
        )
    parts.append(
        f'<line x1="{x(0):.1f}" x2="{x(1):.1f}" y1="{base}" y2="{base}" stroke="var(--muted)"/>'
    )
    for tp in sorted({0.0, lo, 0.5, hi, 1.0}):
        parts.append(
            f'<text x="{x(tp):.1f}" y="{base + 26}" text-anchor="middle" class="muted">'
            f"{tp:.2f}</text>"
        )
    label = f"Members at {g.stage} by supplied probability of a PRO vote. " + (
        f"The rank pivot is {roster.ids[pivot_i]} at {g.p[pivot_i]:.2f}."
        if pivot_i is not None
        else "No rank pivot: the threshold cannot be reached with the members present."
    )
    return (
        f'<div class="scrollx"><svg viewBox="0 0 760 {base + 50:.0f}" width="100%" '
        f'style="min-width:520px" role="img" aria-label="{e(label)}">{"".join(parts)}</svg></div>'
    )


def member_list(g: GateDetail, case: CaseGates, sim: SimGate | None = None) -> str:
    """Every member in rank order; identical neighbours are folded into one row.

    With simulation detail, a last column gives each member's decisive share: the share of draws
    in which the gate's result would flip if that one member's vote flipped.
    """
    roster = case.rosters[g.chamber]
    order = _ranked(g, case)
    dec = sim.decisive_share if sim is not None else None
    if dec is not None and len(dec) != len(roster.ids):
        dec = None

    def decisive(run: list[int]) -> str:
        if dec is None:
            return ""
        vals = [dec[i] for i in run]
        lo, hi = min(vals), max(vals)
        text = pct(lo) if hi - lo < 0.0005 else f"{pct(lo)} to {pct(hi)}"
        return f"<td class=num>{text}</td>"

    def key(i: int) -> tuple[str, float, int, str]:
        return (roster.blocs[i], g.p[i], g.source[i], g.cls[i])

    rows: list[str] = []
    rank = 0
    j = 0
    while j < len(order):
        k = j
        while k + 1 < len(order) and key(order[k + 1]) == key(order[j]):
            k += 1
        run = order[j : k + 1]
        i0 = run[0]
        present = g.cls[i0] != "A"
        first = rank + 1 if present else 0
        if present:
            rank += len(run)
        has_pivot = g.rank_pivot is not None and any(roster.ids[i] == g.rank_pivot for i in run)
        mark = " class=pivotrow" if has_pivot else ""
        tail = (
            f"<td class=num>{g.p[i0]:.3f}</td><td>{e(g.sources[g.source[i0]])}</td>"
            f"<td>{CLASS_WORDS[g.cls[i0]]}</td>"
        )
        if len(run) >= GROUP_MIN:
            names = ", ".join(f"{e(roster.ids[i])} {e(roster.names[i])}" for i in run)
            ranks = f"{first} to {rank}" if present else ""
            note = f" Rank pivot: {e(g.rank_pivot)}, vote {g.required}." if has_pivot else ""
            rows.append(
                f"<tr{mark}><td class=num>{ranks}</td><td colspan=2><details><summary>"
                f"{e(roster.ids[run[0]])} to {e(roster.ids[run[-1]])}: {len(run)} members."
                f"{note}</summary>{names}</details></td><td>{e(roster.blocs[i0])}</td>{tail}"
                f"{decisive(run)}</tr>"
            )
        else:
            for n, i in enumerate(run):
                is_pivot = roster.ids[i] == g.rank_pivot
                rows.append(
                    f"<tr{' class=pivotrow' if is_pivot else ''}>"
                    f"<td class=num>{first + n if present else ''}</td><td>{e(roster.ids[i])}"
                    f"{' (rank pivot)' if is_pivot else ''}</td><td>{e(roster.names[i])}</td>"
                    f"<td>{e(roster.blocs[i])}</td>{tail}{decisive([i])}</tr>"
                )
        j = k + 1
    return (
        f'<details class="memlist"><summary>Member list ({len(order)})</summary>'
        "<table><tr><th scope=col class=num>Rank</th><th scope=col>Id</th><th scope=col>Name</th>"
        "<th scope=col>Bloc</th><th scope=col class=num>p</th><th scope=col>Source</th>"
        f"<th scope=col>Class</th>"
        f"{'<th scope=col class=num>Decisive share</th>' if dec is not None else ''}</tr>"
        f"{''.join(rows)}</table></details>"
    )


# ------------------------------------------------------------- threshold steps


def required_with_absences(g: GateDetail, absent: int) -> int:
    """Votes PRO needs at this gate when ``absent`` more of the present members are away."""
    rule = ThresholdRule(
        kind=g.rule.kind,  # type: ignore[arg-type]
        p=g.rule.p,
        q=g.rule.q,
        present_in_denominator=g.rule.present_in_denominator,
    )
    return required_pro(
        rule,
        g.rule.direction,  # type: ignore[arg-type]
        max(0, g.present - absent),
        0,
        g.base,
        g.rule.tie_break,
    )


def threshold_steps(g: GateDetail) -> str:
    cols = range(min(ABSENCE_STEPS, g.present + 1))
    head = "".join(f"<th scope=col class=num>{k}</th>" for k in cols)
    present = "".join(f"<td class=num>{g.present - k}</td>" for k in cols)
    need = "".join(f"<td class=num>{required_with_absences(g, k)}</td>" for k in cols)
    return (
        "<table><caption class=note style='text-align:left'>How the line moves when more members "
        "are absent. Exact arithmetic from the gate's rule; the simulation is not re-run."
        f"</caption><tr><th scope=row>More members absent</th>{head}</tr>"
        f"<tr><th scope=row>Members voting</th>{present}</tr>"
        f"<tr><th scope=row>PRO votes needed</th>{need}</tr></table>"
    )


# ------------------------------------------------------------------------- tab


def gate_panel(
    key: str,
    g: GateDetail,
    case: CaseGates,
    sim: SimGate | None,
    cutoffs: tuple[float, float],
    on: bool,
    cid: str = "",
    uncertain: bool = False,
) -> str:
    facts = f"<p class=facts>{tag('counted')} {e(tally_summary(g))}"
    if sim is not None:
        c = sim.pro_count_reached or sim.pro_count
        scope = (
            "over the draws that reach this gate"
            if sim.pro_count_reached is not None
            else "over every draw"
        )
        se = f", standard error {100 * sim.pass_se:.1f} points" if sim.pass_se is not None else ""
        facts += (
            f"<br>{tag('simulated')} PRO count {scope}: median {c.p50:.0f}, "
            f"5 to 95% range {c.p5:.0f} to {c.p95:.0f}. The gate passes "
            f"{pct(sim.p_pass_given_reached, sim.pass_se)} of the times it is reached "
            f"({in_100(sim.p_pass_given_reached)}{se}); {in_100(sim.p_reached)} draws reach it."
        )
        if sim.present_count is not None:
            pc = sim.present_count
            needs = [required_with_absences(g, g.present - int(v)) for v in (pc.p5, pc.p95)]
            facts += (
                f" Attendance is drawn at random: {pc.p5:.0f} to {pc.p95:.0f} members vote "
                f"(5 to 95% range), so the votes needed range from {min(needs)} to {max(needs)}."
            )
    facts += "</p>"
    return (
        f'<div class="gatepanel{" on" if on else ""}" id="{key}-{e(g.stage)}" '
        f'data-gate="{e(g.stage)}"><h4>{e(g.stage)} · {e(gate_name(g.stage, g.label))}</h4>'
        f"<p class=rule>{e(g.rule.sentence)}</p>{tally_svg(g, sim)}{KEY}{facts}"
        f"{count_curve(g, sim)}"
        f'<div class="vgrid"><div>{bloc_table(g)}</div><div>{threshold_steps(g)}</div></div>'
        f"{gate_whatif(cid, g, case, cutoffs, uncertain) if cid else ''}"
        f"<h4>{e(MEMBER_HEADING)}</h4><p class=note>{tag('supplied')} {e(MEMBER_NOTE)}"
        f"{DECISIVE_NOTE if sim is not None and sim.decisive_share else ''}</p>"
        f"{member_svg(g, case, cutoffs)}{member_list(g, case, sim)}</div>"
    )


def case_keys(res: PortfolioResult) -> dict[str, str]:
    """A stable element-id prefix for every candidate with a probability."""
    return {cid: f"case{n}" for n, cid in enumerate(res.p0)}


def _label(res: PortfolioResult, cid: str) -> str:
    name = res.labels.get(cid)
    return f"{cid} ({name})" if name and name != cid else cid


def votes_tab(res: PortfolioResult) -> str:
    """The Votes tab: a case selector, and for each case its ladder and gate panels."""
    keys = case_keys(res)
    if not keys:
        return "<p class=note>No candidates.</p>"
    first = next((cid for cid in keys if cid in res.gates), next(iter(keys)))
    rail = "".join(
        f'<button type="button" class="casebtn" data-cid="{e(cid)}" '
        f'aria-pressed="{"true" if cid == first else "false"}" aria-controls="{key}">'
        f"{e(_label(res, cid))} · {pct(res.p0[cid])}</button>"
        for cid, key in keys.items()
    )
    sections: list[str] = []
    for cid, key in keys.items():
        on = " on" if cid == first else ""
        head = (
            f'<section class="case{on}" id="{key}" data-cid="{e(cid)}">'
            f"<h3>{e(_label(res, cid))}</h3>"
        )
        case = res.gates.get(cid)
        if case is None:
            sections.append(
                f"{head}<p>{tag('supplied')} <span class=note>P {pct(res.p0[cid])} supplied "
                "directly; no gate breakdown</span></p></section>"
            )
            continue
        sim = res.gate_paths.get(cid)
        sims = {g.stage: g for g in sim.gates} if sim else {}
        det = res.pivots.get(cid)
        binding = det.binding_gate if det else case.gates[0].stage
        p_rm = res.p0[cid]
        if sim is not None and abs(p_rm - sim.p_complete) >= 1e-12:
            art = (
                f"gates for article {e(case.article)} ({pct(sim.p_complete)} alone), the "
                "likeliest; removal on any article"
            )
        else:
            art = f"article {e(case.article)}"
        se = f", standard error {100 * sim.mc_se:.1f} points" if sim is not None else ""
        mc = sim.mc_se if sim is not None else None
        if sim is not None and sim.p_complete_interval is not None:
            lo_i, hi_i = sim.p_complete_interval
            inputs = (
                f"Across the uncertain inputs, the 5 to 95% range is {pct(lo_i)} to {pct(hi_i)}."
            )
        else:
            inputs = "Inputs are taken as exact: no range is drawn over the supplied priors."
        sm = res.meta.scenarios.get(cid) if res.meta else None
        cutoffs = sm.cutoffs if sm else (0.1, 0.9)
        unc = sm.uncertain_priors if sm else True
        panels = "".join(
            gate_panel(key, g, case, sims.get(g.stage), cutoffs, g.stage == binding, cid, unc)
            for g in case.gates
        )
        sections.append(
            f"{head}<p class=note>path {e(case.path)}, {art}<br>{tag('simulated')} P(removal) "
            f"{pct(p_rm, mc)} ({in_100(p_rm)}{se}). {inputs} Pick a gate to see its count.</p>"
            f"{ladder(key, case, sims, binding)}{panels}</section>"
        )
    return (
        f'{WHATIF_BAR}<div class="caserail" role="group" aria-label="Cases">{rail}</div>'
        f"{''.join(sections)}"
    )
