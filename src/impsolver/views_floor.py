# SPDX-FileCopyrightText: 2026 Justin Stanley
# SPDX-License-Identifier: MIT
"""The Floor time tab of the planning page: the plan drawn by resource, not by case.

The lane calendar has one row per House lane, one for cases waiting for the Senate floor, one
for Senate committee work and one for the single Senate floor, so queues and idle time show as
gaps on a row. Beside it: the session-day budget, the rule behind each date, the numbers behind
each left-out case, and what the order costs each case in fatigue. Everything is drawn from the
report's ``inputs``, the annotated slots, ``budget`` and ``dropped``.
"""

from __future__ import annotations

import datetime as dt
import html

from .model import Portfolio
from .portfolio import Dropped, PlanOut, PortfolioResult, Slot, excluded_reason_text

ONE = dt.timedelta(days=1)

FLOOR_CSS = """
.lanes text{font-size:12px}.scrollx svg.lanes{max-width:none}
.why summary{cursor:pointer;margin:4px 0}
.why ol{margin:4px 0 10px;padding-left:22px}.why li{margin:2px 0}
.minibar{vertical-align:middle;margin-right:8px}
details.full{margin:10px 0}details.full>summary{cursor:pointer;color:var(--muted)}
"""

RESOURCE_NAMES = {
    "house_lanes": "House lanes",
    "senate_committee": "Senate committee",
    "senate_floor": "Senate floor",
}
UNITS = {
    "house_lanes": "House session days, summed over lanes",
    "senate_committee": "Senate session days",
    "senate_floor": "trial days",
}


def e(x: object) -> str:
    return html.escape(str(x), quote=True)


def _pct(p: float) -> str:
    return f"{100 * p:.1f}%"


def _day(d: dt.date) -> str:
    return f"{d:%b} {d.day}, {d.year}"


def floor_ready(s: Slot) -> dt.date:
    """The first day the Senate floor could take the case."""
    if s.committee_end is not None:
        return s.committee_end + ONE
    return s.ready or s.house_end + ONE


def _fit(label: str, width: float, short: str = "") -> str:
    """The label, or ``short``, or a cut ``short``: whatever a bar of ``width`` can hold."""
    room = int((width - 8) / 6.6)
    if room >= len(label):
        return label
    short = short or label
    if room >= len(short):
        return short
    return short[: room - 1] + "…" if room >= 4 else ""


# --------------------------------------------------------------- lane calendar


def calendar_summary(plan: PlanOut) -> str:
    waits = [(s.wait_trial_days or 0, s.id) for s in plan.slots]
    longest = max(waits, default=(0, ""))
    floor = next((b for b in plan.budget if b.resource == "senate_floor"), None)
    text = f"{len(plan.slots)} case(s) across the House lanes and the Senate floor."
    if floor is not None:
        text += f" The Senate floor is used on {floor.used} of {floor.available} trial days."
    if longest[0] > 0:
        text += f" Longest wait for the floor: {longest[1]}, {longest[0]} trial days."
    else:
        text += " No case waits for the floor."
    return text


def lane_calendar(pf: Portfolio, plan: PlanOut, res: PortfolioResult, full: bool = False) -> str:
    """Inline SVG: one row per resource, a bar per phase, gaps for waiting and idle time."""
    slots = plan.slots
    start = pf.start
    last = max((s.trial_end for s in slots), default=pf.start)
    end = max(pf.deadline, last) if full else min(max(pf.deadline, last), last + 45 * ONE)
    span = max(1, (end - start).days)
    left, width, row_h, top = 150.0, 850.0, 34.0, 34.0
    lanes = pf.house_concurrency
    has_committee = any(s.committee_start is not None for s in slots)
    rows: list[tuple[str, str]] = [(f"lane{n}", f"House lane {n}") for n in range(1, lanes + 1)]
    rows.append(("wait", "Waiting for the floor"))
    if has_committee:
        rows.append(("committee", "Senate committee"))
    rows.append(("floor", "Senate floor"))
    row_y = {key: top + i * row_h for i, (key, _) in enumerate(rows)}
    bottom = top + row_h * len(rows)
    height = bottom + 30

    def x(d: dt.date) -> float:
        return left + width * (d - start).days / span

    def clip(a: dt.date, b: dt.date) -> tuple[float, float] | None:
        """Pixel extent of the days a..b inclusive, cut to the drawn range."""
        if b < start or a > end or b < a:
            return None
        return x(max(a, start)), x(min(b + ONE, end))

    parts: list[str] = []
    # Recess bands sit only on the rows of the chamber in recess.
    house_rows = [k for k, _ in rows if k.startswith("lane")]
    senate_rows = [k for k, _ in rows if not k.startswith("lane")]
    for who, spans, keys in (
        ("House", pf.calendar.house.recess, house_rows),
        ("Senate", pf.calendar.senate.recess, senate_rows),
    ):
        for a, b in spans:
            ext = clip(a, b)
            if ext is None:
                continue
            y0 = row_y[keys[0]]
            parts.append(
                f'<rect x="{ext[0]:.1f}" y="{y0 + 1}" width="{max(1.0, ext[1] - ext[0]):.1f}" '
                f'height="{row_h * len(keys) - 2}" fill="var(--recess)"><title>{who} recess '
                f"{a} to {b}</title></rect>"
            )
    # Month ticks.
    d = dt.date(start.year, start.month, 1)
    parts.append(f'<text x="{left}" y="{top - 12}" class="muted">{start:%b} {start.day}</text>')
    while d <= end:
        if d > start:
            parts.append(
                f'<line x1="{x(d):.1f}" x2="{x(d):.1f}" y1="{top - 6}" y2="{bottom}" '
                f'stroke="var(--line)"/>'
            )
            if (span < 400 or d.month in (1, 4, 7, 10)) and x(d) - left > 46:
                label = f"{d:%b %Y}" if d.month == 1 or span >= 400 else f"{d:%b}"
                parts.append(
                    f'<text x="{x(d) + 3:.1f}" y="{top - 12}" class="muted">{label}</text>'
                )
        d = dt.date(d.year + (d.month == 12), d.month % 12 + 1, 1)
    for key, name in rows:
        y = row_y[key]
        weight = ' style="font-weight:600"' if key == "floor" else ""
        parts.append(
            f'<line x1="0" x2="{left + width}" y1="{y + row_h}" y2="{y + row_h}" '
            f'stroke="var(--line)"/><text x="4" y="{y + 21}"{weight}>{name}</text>'
        )

    def bar(
        key: str, a: dt.date, b: dt.date, style: str, label: str, title: str, short: str = ""
    ) -> None:
        ext = clip(a, b)
        if ext is None:
            return
        w = max(2.0, ext[1] - ext[0] - 1)
        y = row_y[key] + 6
        parts.append(
            f'<rect x="{ext[0] + 0.5:.1f}" y="{y}" width="{w:.1f}" height="{row_h - 12}" rx="4" '
            f"{style}><title>{e(title)}</title></rect>"
        )
        text = _fit(label, w, short)
        if text:
            parts.append(
                f'<text x="{ext[0] + w / 2:.1f}" y="{y + 15}" text-anchor="middle">{e(text)}</text>'
            )

    solid = 'fill="var(--chip)" stroke="var(--muted)"'
    floor = 'fill="var(--trial)" fill-opacity="0.35" stroke="var(--trial)" stroke-width="1.5"'
    dashed = 'fill="none" stroke="var(--muted)" stroke-dasharray="4 3"'
    dotted = 'fill="none" stroke="var(--muted)" stroke-dasharray="1 3"'
    for s in slots:
        lane = s.house_lane if s.house_lane and 1 <= s.house_lane <= lanes else 1
        days = f" · {s.house_days} days" if s.house_days is not None else ""
        bar(
            f"lane{lane}",
            s.house_start,
            s.house_end,
            solid,
            f"{s.id}{days}",
            f"{s.id}: House work {s.house_start} to {s.house_end}{days.replace(' · ', ', ')}",
            s.id,
        )
        if s.committee_start is not None and s.committee_end is not None:
            bar(
                "committee",
                s.committee_start,
                s.committee_end,
                solid,
                s.id,
                f"{s.id}: Senate committee {s.committee_start} to {s.committee_end}",
            )
        if s.wait_trial_days:
            bar(
                "wait",
                floor_ready(s),
                s.trial_start - ONE,
                dashed,
                f"{s.id} waits {s.wait_trial_days}",
                f"{s.id}: ready {floor_ready(s)}, waits {s.wait_trial_days} trial days for the "
                f"floor" + (f" (in use by {s.trial_start_after})" if s.trial_start_after else ""),
                f"waits {s.wait_trial_days}",
            )
        tdays = f" · {s.trial_days} days" if s.trial_days is not None else ""
        bar(
            "floor",
            s.trial_start,
            s.trial_end,
            floor,
            f"{s.id}{tdays}",
            f"{s.id}: Senate trial {s.trial_start} to {s.trial_end}{tdays.replace(' · ', ', ')}",
            s.id,
        )
    trials = sorted(slots, key=lambda s: s.trial_start)
    for t0, t1 in zip(trials, trials[1:], strict=False):
        if (t1.trial_start - t0.trial_end).days > 1:
            bar(
                "floor",
                t0.trial_end + ONE,
                t1.trial_start - ONE,
                dotted,
                "idle",
                f"Senate floor idle {t0.trial_end + ONE} to {t1.trial_start - ONE}",
            )
    for n, day in enumerate(res.epochs, 1):
        if start <= day <= end:
            parts.append(
                f'<line x1="{x(day):.1f}" x2="{x(day):.1f}" y1="{top - 6}" y2="{bottom}" '
                f'stroke="var(--ink)" stroke-dasharray="2 2"><title>roster change {n}: {day}'
                "</title></line>"
            )
    if pf.deadline <= end:
        xd = x(pf.deadline)
        parts.append(
            f'<line x1="{xd:.1f}" x2="{xd:.1f}" y1="{top - 6}" y2="{bottom}" '
            f'stroke="var(--deadline)" stroke-width="2" stroke-dasharray="4 3"/>'
            f'<text x="{xd - 4:.1f}" y="{bottom + 18}" text-anchor="end" '
            f'style="fill:var(--deadline)">deadline {pf.deadline}</text>'
        )
    else:
        parts.append(
            f'<text x="{left + width}" y="{bottom + 18}" text-anchor="end" class="muted">'
            f"deadline {pf.deadline} is past the right edge</text>"
        )
    label = f"Lane calendar. {calendar_summary(plan)}"
    return (
        f'<div class="scrollx" tabindex="0"><svg class="lanes" '
        f'viewBox="0 0 {left + width + 10:.0f} '
        f'{height:.0f}" width="100%" style="min-width:640px" role="img" '
        f'aria-label="{e(label)}">{"".join(parts)}</svg></div>'
    )


CALENDAR_KEY = (
    '<div class="key" aria-hidden="true">'
    '<span><svg width="18" height="12"><rect x="1" y="1" width="16" height="10" rx="3" '
    'fill="var(--chip)" stroke="var(--muted)"/></svg>House or committee work</span>'
    '<span><svg width="18" height="12"><rect x="1" y="1" width="16" height="10" rx="3" '
    'fill="var(--trial)" fill-opacity="0.35" stroke="var(--trial)"/></svg>Senate trial</span>'
    '<span><svg width="18" height="12"><rect x="1" y="1" width="16" height="10" rx="3" '
    'fill="none" stroke="var(--muted)" stroke-dasharray="4 3"/></svg>waiting for the floor</span>'
    '<span><svg width="18" height="12"><rect x="1" y="1" width="16" height="10" rx="3" '
    'fill="none" stroke="var(--muted)" stroke-dasharray="1 3"/></svg>floor idle</span>'
    '<span><svg width="18" height="12"><rect width="18" height="12" fill="var(--recess)"/></svg>'
    "recess</span></div>"
)


# ------------------------------------------------------------------ day budget


def budget_table(pf: Portfolio, plan: PlanOut) -> str:
    if not plan.budget:
        return ""
    rows = "".join(
        f"<tr><th scope=row>{RESOURCE_NAMES[b.resource]}"
        f"{f' ({pf.house_concurrency})' if b.resource == 'house_lanes' else ''}"
        f"<br><span class=note>{UNITS[b.resource]}</span></th>"
        f"<td class=num>{b.available}</td><td class=num>{b.used}</td>"
        f"<td class=num>{b.available - b.used}</td>"
        f"<td class=num>{_pct(b.used / b.available) if b.available else 'n/a'}</td></tr>"
        for b in plan.budget
    )
    sat = " Trial days include Saturdays." if pf.calendar.trial_saturdays else ""
    return (
        "<table><caption class=note style='text-align:left'>Session days between the window's "
        f"start and deadline ({pf.start} to {pf.deadline}), and what this plan uses.{sat}"
        "</caption><tr><th scope=col>Resource</th><th scope=col class=num>In the window</th>"
        "<th scope=col class=num>Used</th><th scope=col class=num>Left</th>"
        f"<th scope=col class=num>Share used</th></tr>{rows}</table>"
    )


# --------------------------------------------------------------- why this date


def date_reasons(pf: Portfolio, s: Slot) -> list[str]:
    """The rule behind each of a case's dates, in order, as plain sentences."""
    out: list[str] = []
    lane = f"lane {s.house_lane}" if s.house_lane else "a lane"
    why = {
        "window_start": "the window opens that day",
        "lane_free": f"{lane} became free when {s.house_start_after}'s House work ended",
        "release": "that is its release date",
        "after": f"it waits on {s.house_start_after}, whose trial ended the day before",
        "not_before": "the plan was revised after a verdict",
    }.get(s.house_start_reason or "", "")
    out.append(f"House start {_day(s.house_start)}, in {lane}" + (f": {why}." if why else "."))
    days = f": {s.house_days} House session days" if s.house_days is not None else ""
    out.append(f"House end {_day(s.house_end)}{days}.")
    if s.committee_start is not None and s.committee_end is not None:
        out.append(
            f"Senate committee {_day(s.committee_start)} to {_day(s.committee_end)}; it does "
            "not use the floor."
        )
    ready = floor_ready(s)
    if s.trial_start_reason == "floor_busy":
        out.append(
            f"Trial start {_day(s.trial_start)}: ready on {_day(ready)}, but the floor was in "
            f"use by {s.trial_start_after}. It waited {s.wait_trial_days} trial days."
        )
    else:
        out.append(f"Trial start {_day(s.trial_start)}: the floor was free when it was ready.")
    tdays = f": {s.trial_days} trial days" if s.trial_days is not None else ""
    sat = ", Saturdays included" if pf.calendar.trial_saturdays and s.trial_days else ""
    out.append(f"Trial end {_day(s.trial_end)}{tdays}{sat}.")
    if s.slack_days is not None:
        out.append(f"Slack: {s.slack_days} trial days from the verdict to its deadline.")
    if s.p != s.p0:
        out.append(
            f"Chance: {_pct(s.p0)} alone, {_pct(s.p)} as trial {s.attempt + 1} in this order."
        )
    else:
        out.append(f"Chance: {_pct(s.p)}, the same as alone (trial {s.attempt + 1}).")
    return out


def why_dates(pf: Portfolio, plan: PlanOut, res: PortfolioResult) -> str:
    blocks = "".join(
        f"<details{' open' if n == 0 else ''}><summary>{e(_name(res, s.id))}</summary><ol>"
        + "".join(f"<li>{e(line)}</li>" for line in date_reasons(pf, s))
        + "</ol></details>"
        for n, s in enumerate(plan.slots)
    )
    return f'<div class="why">{blocks}</div>'


def _name(res: PortfolioResult, cid: str) -> str:
    name = res.labels.get(cid)
    return f"{cid} ({name})" if name and name != cid else cid


# ---------------------------------------------------------------- why left out


def _minibar(p: float, floor: float) -> str:
    """A 0-to-1 bar with the case's chance (dot) against the floor (tick)."""
    w = 120.0
    return (
        f'<svg class="minibar" width="{w + 8:.0f}" height="16" role="img" '
        f'aria-label="chance {_pct(p)} against a floor of {_pct(floor)}">'
        f'<line x1="4" x2="{w + 4}" y1="8" y2="8" stroke="var(--muted)"/>'
        f'<line x1="{4 + w * floor:.1f}" x2="{4 + w * floor:.1f}" y1="2" y2="14" '
        f'stroke="var(--ink)" stroke-width="2"/>'
        f'<circle cx="{4 + w * p:.1f}" cy="8" r="4" fill="var(--house)"/></svg>'
    )


def drop_numbers_text(d: Dropped) -> str:
    """One or two sentences built from the numbers behind a dropped reason (HTML)."""
    n = d.numbers
    if (
        d.reason == "LOW_P"
        and isinstance(n.get("p"), float)
        and isinstance(n.get("p_floor"), float)
    ):
        p, floor = float(n["p"]), float(n["p_floor"])  # type: ignore[arg-type]
        return f"{_minibar(p, floor)}Chance {_pct(p)} is under the floor of {_pct(floor)}."
    if d.reason == "EXCLUDED" and isinstance(n.get("by"), list):
        by = ", ".join(str(x) for x in n["by"])  # type: ignore[union-attr]
        text = f"It cannot run alongside {e(by)}, which the plan keeps."
        if isinstance(n.get("value"), float) and isinstance(n.get("swap_value"), float):
            text += (
                f" Expected removals are {n['value']:.2f} with this plan and "
                f"{n['swap_value']:.2f} for the best plan without {e(by)}."
            )
        return text
    if d.reason == "NO_FIT" and n.get("deadline"):
        if n.get("earliest_end"):
            return (
                f"Scheduled first, with no deadline, it would finish on {e(n['earliest_end'])}: "
                f"{e(n['days_over'])} days after its deadline of {e(n['deadline'])}."
            )
        return (
            f"Even scheduled first it would not finish within three years of its deadline of "
            f"{e(n['deadline'])}."
        )
    if d.reason == "DEPENDENCY_DROPPED" and isinstance(n.get("waits_on"), list):
        on = ", ".join(str(x) for x in n["waits_on"])  # type: ignore[union-attr]
        return f"It waits on {e(on)}, which is not in the plan."
    if d.reason == "NOT_SELECTED" and isinstance(n.get("value_with"), float):
        return (
            f"Expected removals are {n['value_without']:.2f} without it and at best "
            f"{n['value_with']:.2f} with it added anywhere in this order."
        )
    return ""


def left_out_table(res: PortfolioResult) -> str:
    rows = (
        "".join(
            f"<tr><td>{e(_name(res, d.id))}</td><td>{e(d.reason)}</td><td>"
            f"{e(excluded_reason_text(d.reason))} ({e(d.detail)})"
            f"{'<br>' + drop_numbers_text(d) if drop_numbers_text(d) else ''}</td></tr>"
            for d in res.dropped
        )
        or "<tr><td colspan=3 class=note>Every candidate is in the recommended plan.</td></tr>"
    )
    return (
        "<table><tr><th scope=col>Candidate</th><th scope=col>Reason</th>"
        f"<th scope=col>Detail</th></tr>{rows}</table>"
    )


# --------------------------------------------------------------------- section


def plan_views(pf: Portfolio, plan: PlanOut, res: PortfolioResult) -> str:
    """The lane calendar, its full-window version, the day budget and the date reasons."""
    return (
        f"<p class=note>{e(calendar_summary(plan))} Bar labels count session days. Durations "
        "are the supplied numbers; no range is drawn around them.</p>"
        f"{lane_calendar(pf, plan, res)}{CALENDAR_KEY}"
        '<details class="full"><summary>Show the whole window to the deadline</summary>'
        f"{lane_calendar(pf, plan, res, full=True)}</details>"
        f"<h3>Day budget</h3>{budget_table(pf, plan)}"
    )
