"""Deterministic bounds: classify members by cutoffs and bound each gate."""

from __future__ import annotations

from collections import Counter

import numpy as np

from .paths import Path, path_for
from .prepare import Prepared
from .results import BlocCount, DeterministicArticle, DeterministicGate, Evaluation, Verdict
from .thresholds import has_quorum, membership_base, pro_wins, required_pro, tie_mode


def default_path(prep: Prepared) -> str:
    return "B" if prep.scenario.committee_reports else "A"


def _counts(blocs: list[str]) -> list[BlocCount]:
    c = Counter(blocs)
    return [
        BlocCount(bloc=b, count=n) for b, n in sorted(c.items(), key=lambda kv: (-kv[1], kv[0]))
    ]


def evaluate_article(prep: Prepared, article: str, path: Path) -> DeterministicArticle:
    lo, hi = prep.scenario.cutoffs
    gates: list[DeterministicGate] = []
    nonpro_by_gate: dict[str, list[BlocCount]] = {}
    for st in path.all_stages:
        body = prep.comp.bodies[st.chamber]
        members = body.roster
        p = prep.probs(st.chamber, st.id, article)
        present = prep.present_mask(st.chamber)
        is_pro = present & (p >= hi)
        is_con = present & (p <= lo)
        is_unc = present & ~is_pro & ~is_con
        voting = int(present.sum())
        pro_min = int(is_pro.sum())
        pro_max = pro_min + int(is_unc.sum())
        base = membership_base(st.rule, body.seats, body.vacancies)
        tie = tie_mode(st, prep.scenario.senate_tie_break)
        need = required_pro(st.rule, st.pass_direction, voting, 0, base, tie)
        verdict: Verdict
        if not has_quorum(voting, body.sworn):
            verdict = "NO_QUORUM"
        elif pro_wins(st.rule, st.pass_direction, pro_min, voting - pro_min, 0, base, tie):
            verdict = "PASS"
        elif not pro_wins(st.rule, st.pass_direction, pro_max, voting - pro_max, 0, base, tie):
            verdict = "FAIL"
        else:
            verdict = "CONTESTED"
        officer = (
            st.presiding_officer.officer(prep.scenario.target.office)
            if st.presiding_officer
            else None
        )
        gates.append(
            DeterministicGate(
                stage=st.id,
                chamber=st.chamber,
                label=st.label,
                pro_min=pro_min,
                pro_max=pro_max,
                uncertain=int(is_unc.sum()),
                absent=int((~present).sum()) + body.vacancies,
                required=need,
                verdict=verdict,
                short_at_min=max(0, need - pro_min),
                presiding_officer=officer,
                uncertain_by_bloc=_counts(
                    [m.bloc for m, u in zip(members, is_unc, strict=True) if u]
                ),
            )
        )
        nonpro_by_gate[st.id] = _counts(
            [m.bloc for m, x in zip(members, present & ~is_pro, strict=True) if x]
        )
    required_ids = {s.id for s in path.stages}
    req = [g for g in gates if g.stage in required_ids]
    ends_at = next((g.stage for g in req if g.verdict in ("FAIL", "NO_QUORUM")), None)
    overall: Verdict
    if ends_at is not None:
        overall = next(g.verdict for g in req if g.stage == ends_at)
    elif any(g.verdict == "CONTESTED" for g in req):
        overall = "CONTESTED"
    else:
        overall = "PASS"
    # The binding gate is the first one PRO cannot win; otherwise the largest shortfall.
    if ends_at is not None:
        binding = next(g for g in req if g.stage == ends_at)
    else:
        binding = req[int(np.argsort([-g.short_at_min for g in req], kind="stable")[0])]
    return DeterministicArticle(
        article=article,
        path=path.name,
        verdict=overall,
        ends_at=ends_at,
        binding_gate=binding.stage,
        controlling_coalition=nonpro_by_gate[binding.stage],
        gates=gates,
    )


def evaluate(prep: Prepared, path_name: str | None = None) -> Evaluation:
    path = path_for(prep.rules, prep.scenario, path_name or default_path(prep))
    return Evaluation(
        target=prep.scenario.target.name,
        office=prep.scenario.target.office,
        composition=prep.comp.name,
        cutoffs=prep.scenario.cutoffs,
        articles=[evaluate_article(prep, a, path) for a in prep.scenario.articles],
    )
