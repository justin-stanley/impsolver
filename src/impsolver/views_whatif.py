# SPDX-FileCopyrightText: 2026 Justin Stanley
# SPDX-License-Identifier: MIT
"""What-if controls for the planning page.

Votes: each gate panel carries a small form. The browser redoes the gate's counted arithmetic
(who is counted, how many vote, where the line sits) from the embedded report data. It never
re-runs the simulation, and the page says so beside every result.

Floor time: the solver re-schedules the recommended order under other settings when the page is
made, so these are plain server-rendered calendars with no script.
"""

from __future__ import annotations

import datetime as dt
import html

from .contract import CaseGates, GateDetail
from .model import Portfolio
from .portfolio import PlanOut, PortfolioResult, SensRow, Slot
from .views_floor import lane_calendar

WHATIF_CSS = """
.whatif,.wifbar{display:none}.js .whatif{display:block;margin:14px 0;border:1px solid var(--line);
border-radius:8px;padding:8px 12px}.js .wifbar.on{display:block}
.whatif>summary{cursor:pointer;font-weight:600;min-height:28px}
.wifrow{display:flex;flex-wrap:wrap;gap:8px 14px;align-items:center;margin:8px 0}
.wifrow input,.wifrow select,.whatif button,.wifbar button{font:inherit;color:var(--ink);
background:var(--panel);border:1px solid var(--muted);border-radius:6px;padding:4px 6px;
min-height:32px}.wifrow input{width:5.5em}
.wifout{border-left:3px solid var(--house);padding:4px 10px;margin:10px 0}
.wifbar{border:1px solid var(--house);border-radius:8px;padding:6px 12px;margin:0 0 12px}
details.alt{margin:6px 0}details.alt>summary{cursor:pointer}
@media print{.whatif,.wifbar{display:none!important}}
"""

# The arithmetic below mirrors thresholds.motion_carries, pro_wins and required_pro, with nobody
# answering "present". tests/test_views_whatif.py checks the two agree.
WHATIF_MATH = """
function carries(r,yea,nay,base){if(r.kind==='majority_of_votes_cast')return yea>nay;
if(r.kind==='fraction_of_present')return r.q*yea>=r.p*(yea+nay);return r.q*yea>=r.p*base;}
function wins(r,pro,con,base){var out=r.direction==='pass'?carries(r,pro,con,base):
!carries(r,con,pro,base);if(r.tie_break==='none'||r.kind!=='majority_of_votes_cast')return out;
return pro===con?r.tie_break==='pro':out;}
function need(r,voting,base){if(r.direction==='pass'&&r.tie_break==='none'){
if(r.kind==='majority_of_votes_cast')return Math.floor(voting/2)+1;
if(r.kind==='fraction_of_present')return Math.ceil(r.p*voting/r.q);
return Math.ceil(r.p*base/r.q);}
for(var k=0;k<=voting;k++){if(wins(r,k,voting-k,base))return k;}
return voting+1;}
function tally(g,blocs,lo,hi,recut){var t={};for(var i=0;i<g.cls.length;i++){var c=g.cls[i];
if(recut&&c!=='A')c=g.p[i]>=hi?'P':g.p[i]<=lo?'C':'U';var b=blocs[i];
if(!t[b])t[b]={P:0,U:0,C:0,A:0};t[b][c]++;}return t;}
function sum(t,k){var n=0;for(var b in t)n+=t[b][k];return n;}
function gap(n,line){return n>=line?'reaches the line':'is '+(line-n)+' short of the line';}
function compute(g,blocs,q){var notes=[],recut=q.lo!==q.lo0||q.hi!==q.hi0;
if(recut&&!(q.lo<q.hi)){notes.push('The cutoffs are out of order, so the supplied ones are '+
'used.');recut=false;}
var base=tally(g,blocs,q.lo0,q.hi0,false),t=tally(g,blocs,q.lo,q.hi,recut);
var a=Math.max(0,q.absn|0),row=t[q.absb];if(row&&a>0){if(a>row[q.absc]){a=row[q.absc];
notes.push('Only '+a+' such members in '+q.absb+'; using '+a+'.');}row[q.absc]-=a;row.A+=a;}
var f=Math.max(0,q.flipn|0);row=t[q.flipb];if(row&&f>0){if(f>row.U){f=row.U;
notes.push('Only '+f+' uncertain members in '+q.flipb+'; using '+f+'.');}row.U-=f;row.P+=f;}
var P=sum(t,'P'),U=sum(t,'U'),C=sum(t,'C'),voting=P+U+C;
return {changed:recut||a>0||f>0,voting:voting,need:need(g.rule,voting,g.base),P:P,U:U,C:C,
P0:sum(base,'P'),U0:sum(base,'U'),C0:sum(base,'C'),notes:notes};}
"""

WHATIF_JS = (
    """
(function(){var d=document,el=d.getElementById('impsolver-data');if(!el)return;
var data;try{data=JSON.parse(el.textContent);}catch(err){return;}
function all(s,r){return Array.prototype.slice.call((r||d).querySelectorAll(s));}
"""
    + WHATIF_MATH
    + """
function was(now,then){return now===then?now+' (unchanged)':now+' (was '+then+')';}
function text(g,r){if(!r.changed)return (r.notes.join(' ')+' No change is being tried.').trim();
return 'With this change '+was(r.voting,g.present)+' members vote and PRO needs '+
was(r.need,g.required)+'. Counted PRO '+was(r.P,r.P0)+', uncertain '+was(r.U,r.U0)+
', counted CON '+was(r.C,r.C0)+'. Counted PRO alone '+gap(r.P,r.need)+
'. With every uncertain member counted as PRO, '+(r.P+r.U)+' '+gap(r.P+r.U,r.need)+'. '+
r.notes.join(' ');}
var boxes=all('.whatif'),bar=d.querySelector('.wifbar');
function refreshBar(){if(!bar)return;var n=boxes.filter(function(b){
return b.dataset.changed==='1';}).length;bar.classList.toggle('on',n>0);
var s=bar.querySelector('span');if(s)s.textContent=n===1?'A change is being tried at 1 gate.':
'Changes are being tried at '+n+' gates.';}
boxes.forEach(function(box){var c=(data.gates||{})[box.dataset.cid];if(!c)return;
var g=c.gates.filter(function(x){return x.stage===box.dataset.gate;})[0];if(!g)return;
var blocs=c.rosters[g.chamber].blocs,out=box.querySelector('.wifout');
function v(k){return box.querySelector('[data-k='+k+']');}
function run(){var q={absn:+v('absn').value,absb:v('absb').value,absc:v('absc').value,
flipn:+v('flipn').value,flipb:v('flipb').value,lo:+v('lo').value,hi:+v('hi').value,
lo0:+v('lo').defaultValue,hi0:+v('hi').defaultValue};var r=compute(g,blocs,q);
out.textContent=text(g,r);box.dataset.changed=r.changed?'1':'0';refreshBar();}
function reset(){all('input',box).forEach(function(i){i.value=i.defaultValue;});
all('select',box).forEach(function(s){s.selectedIndex=0;});run();}
all('input,select',box).forEach(function(i){i.addEventListener('input',run);
i.addEventListener('change',run);});
box.querySelector('.wifreset').addEventListener('click',reset);box._reset=reset;});
if(bar){var rb=bar.querySelector('button');if(rb)rb.addEventListener('click',function(){
boxes.forEach(function(b){if(b._reset)b._reset();});});}
})();
"""
)


def e(x: object) -> str:
    return html.escape(str(x), quote=True)


WHATIF_BAR = (
    '<p class="wifbar" role="status"><span></span> The simulated figures on this page still '
    'describe the supplied inputs. <button type="button">Reset every gate</button></p>'
)


def gate_whatif(
    cid: str, g: GateDetail, case: CaseGates, cutoffs: tuple[float, float], uncertain: bool
) -> str:
    """A form that redoes one gate's counted arithmetic in the browser."""
    blocs = "".join(f"<option>{e(b.bloc)}</option>" for b in g.blocs)
    lo, hi = cutoffs
    off = " disabled" if uncertain else ""
    cut_note = (
        "<p class=note>The cutoffs are fixed here: this scenario supplies ranges for some "
        "priors, and the page holds only one probability per member.</p>"
        if uncertain
        else ""
    )
    return (
        f'<details class="whatif" data-cid="{e(cid)}" data-gate="{e(g.stage)}">'
        "<summary>Try a change at this gate</summary>"
        "<p class=note>Exact arithmetic on the counted tally. The simulation is not re-run, so "
        "the simulated figures stay as they are. To keep a change, edit the scenario file "
        "(attendance, shifts or cutoffs) and run the command again.</p>"
        '<div class="wifrow"><label>More members absent '
        f'<input type="number" data-k="absn" min="0" max="{g.present}" value="0"></label>'
        f'<label>from bloc <select data-k="absb">{blocs}</select></label>'
        '<label>among the <select data-k="absc"><option value="U">uncertain</option>'
        '<option value="P">counted PRO</option><option value="C">counted CON</option></select>'
        "</label></div>"
        '<div class="wifrow"><label>Count uncertain members as PRO '
        f'<input type="number" data-k="flipn" min="0" max="{g.present}" value="0"></label>'
        f'<label>from bloc <select data-k="flipb">{blocs}</select></label></div>'
        '<div class="wifrow"><label>Counted CON at or below p '
        f'<input type="number" data-k="lo" min="0" max="1" step="0.01" value="{lo:g}"{off}>'
        "</label><label>Counted PRO at or above p "
        f'<input type="number" data-k="hi" min="0" max="1" step="0.01" value="{hi:g}"{off}>'
        f"</label></div>{cut_note}"
        '<p class="wifout" role="status">No change is being tried.</p>'
        '<button type="button" class="wifreset">Reset this gate</button></details>'
    )


# ----------------------------------------------------------------- floor time


def _last(slots: list[Slot]) -> dt.date | None:
    return max((s.trial_end for s in slots), default=None)


def _keep_hint(row: SensRow, pf: Portfolio) -> str:
    if row.house_lanes is not None:
        return f"To keep it, set house_concurrency: {row.house_lanes} in the portfolio file."
    if row.label.startswith("trial Saturdays"):
        now = "false" if pf.calendar.trial_saturdays else "true"
        return f"To keep it, set calendar.trial_saturdays: {now} in the portfolio file."
    if row.kind == "order":
        return (
            "The solver picks the order itself; a fixed order can be forced with each "
            "candidate's after list."
        )
    return "To keep it, change house_days and senate_days in the portfolio file."


def other_settings(pf: Portfolio, res: PortfolioResult) -> str:
    """The recommended order re-scheduled under one changed setting at a time."""
    rows = [r for r in [*res.what_if, *res.sensitivity] if r.slots and "fatigue" not in r.label]
    if not rows or not res.plans:
        return ""
    base = res.plans[0]
    base_end = _last(base.slots)
    base_value = (
        res.succession_value if res.succession_value is not None else base.expected_removals
    )
    body = (
        "<tr><th scope=row>As supplied</th>"
        f"<td>{base_end or ''}</td><td class=num>{len(base.slots)}</td>"
        f"<td class=num>{base_value:.2f}</td><td class=num>{base_value:.2f}</td></tr>"
    )
    blocks: list[str] = []
    for r in rows:
        end = _last(r.slots)
        moved = ""
        if end and base_end and end != base_end:
            n = (end - base_end).days
            moved = f" ({abs(n)} day{'s' if abs(n) != 1 else ''} {'later' if n > 0 else 'earlier'})"
        body += (
            f"<tr><th scope=row>{e(r.label)}</th><td>{end or ''}{moved}</td>"
            f"<td class=num>{len(r.slots)}</td><td class=num>{r.base_rescheduled:.2f}</td>"
            f"<td class=num>{r.best:.2f}</td></tr>"
        )
        alt_pf = (
            pf.model_copy(update={"house_concurrency": r.house_lanes})
            if r.house_lanes is not None
            else pf
        )
        order = r.order or [s.id for s in r.slots]
        plan = PlanOut(order=order, expected_removals=r.base_rescheduled, slots=r.slots)
        blocks.append(
            f'<details class="alt"><summary>Calendar: {e(r.label)}</summary>'
            f"<p class=note>Order {e(' → '.join(order))}. {e(_keep_hint(r, pf))}</p>"
            f"{lane_calendar(alt_pf, plan, res)}</details>"
        )
    return (
        "<h2>Other settings</h2><div class=panel><p class=note>One change at a time, worked out "
        "by the solver when this page was made. The order rows swap two neighbours in the "
        "recommended order; the other rows keep that order and change a setting. These "
        "calendars leave out succession branches. Best is the best order the solver finds "
        "under that setting.</p>"
        "<table><tr><th scope=col>Change</th><th scope=col>Last trial ends</th>"
        "<th scope=col class=num>Cases that fit</th>"
        "<th scope=col class=num>Expected removals</th><th scope=col class=num>Best</th></tr>"
        f"{body}</table>{''.join(blocks)}</div>"
    )
