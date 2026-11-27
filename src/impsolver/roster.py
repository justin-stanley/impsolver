# SPDX-FileCopyrightText: 2026 Justin Stanley
# SPDX-License-Identifier: MIT
"""Build a composition (who holds each seat now) from Voteview member and vote files."""

from __future__ import annotations

import argparse
import datetime as dt
import io
import sys
import textwrap
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path

from ruamel.yaml import YAML

from .alignment import (
    VVMember,
    parse_caucus,
    parse_mapping,
    read_members,
    read_votes,
    voteview_source,
)
from .model import Body, Composition, Member

SEATS = {"house": 435, "senate": 100}
TERRITORIES = {"DC", "PR", "GU", "VI", "AS", "MP", "USA"}
VOTED = set(range(1, 10))


@dataclass
class RosterReport:
    comp: Composition
    lines: list[str]


def resolve_caucus(
    mid: str, party: str, member_caucus: dict[str, str], caucus: dict[str, str]
) -> tuple[str | None, str | None]:
    """(caucus, note): ``--member-caucus`` beats ``--caucus``; the note flags a party mapping."""
    if mid in member_caucus:
        c = member_caucus[mid]
        return (None if c.lower() == "none" else c), None
    if party in caucus:
        cau = caucus[party]
        return cau, f"caucus {cau} set from party mapping {party}={cau}"
    return None, None


def chamber_summary(chamber: str, members: list[Member], seats: int, extra: str) -> str:
    """The per-chamber header line, e.g. ``house: 432 members (217R/214D/1I), 3 vacancies, ...``."""
    parties = Counter(m.party for m in members)
    return (
        f"{chamber}: {len(members)} members ("
        + "/".join(f"{n}{p}" for p, n in sorted(parties.items(), key=lambda kv: -kv[1]))
        + f"), {seats - len(members)} vacancies, {extra}"
    )


def last_votes(
    vote_paths: list[Path],
) -> tuple[dict[str, dict[int, tuple[int, int]]], dict[str, tuple[int, int]]]:
    """(chamber -> icpsr -> last (congress, roll) voted), (chamber -> last roll overall)."""
    rolls = read_votes(vote_paths)
    last: dict[str, dict[int, tuple[int, int]]] = defaultdict(dict)
    end: dict[str, tuple[int, int]] = {}
    for chamber, rc in rolls.items():
        for key, casts in rc.items():
            end[chamber] = max(end.get(chamber, key), key)
            for ic, code in casts.items():
                if code in VOTED and key > last[chamber].get(ic, (0, 0)):
                    last[chamber][ic] = key
    return last, end


def build_roster(
    member_paths: list[Path],
    vote_paths: list[Path],
    caucus: dict[str, str] | None = None,
    member_caucus: dict[str, str] | None = None,
    keep: list[str] | None = None,
    vacancy_gap: int = 50,
    as_of: dt.date | None = None,
    name: str = "us-119",
    vacate: list[str] | None = None,
    accessed: dt.date | None = None,
) -> RosterReport:
    caucus = caucus or {}
    member_caucus = member_caucus or {}
    keep_set = set(keep or [])
    vacate_set = set(vacate or [])
    known_ids: set[str] = set()
    members = read_members(member_paths)
    last, end = last_votes(vote_paths)
    lines: list[str] = [
        "Data: " + voteview_source([*member_paths, *vote_paths], accessed or dt.date.today())
    ]
    bodies: dict[str, Body] = {}
    newest = (10**9, 10**9)
    for chamber in ("house", "senate"):
        ms = [m for m in members if m.chamber == chamber and m.state not in TERRITORIES]

        def last_of(m: VVMember, chamber: str = chamber) -> tuple[int, int]:
            got = [last[chamber][ic] for ic in m.icpsrs if ic in last[chamber]]
            return max(got) if got else newest

        seats: dict[tuple[str, int | None], list[VVMember]] = defaultdict(list)
        for m in ms:
            seats[(m.state, m.district if chamber == "house" else None)].append(m)
        per_seat = 1 if chamber == "house" else 2
        holders: list[VVMember] = []
        suspected: list[str] = []
        end_c = end.get(chamber, (0, 0))
        for key, group in sorted(seats.items(), key=lambda kv: (kv[0][0], kv[0][1] or 0)):
            group.sort(key=last_of, reverse=True)
            winners = group[:per_seat]
            for w in winners:
                known_ids.add(w.id)
                if w.id in vacate_set:
                    suspected.append(f"{w.name} ({w.id}) vacated by --vacate")
                    continue
                sole = len(group) <= per_seat
                lv = last_of(w)
                stale = lv != newest and (lv[0] < end_c[0] or end_c[1] - lv[1] > vacancy_gap)
                if sole and stale and w.id not in keep_set:
                    suspected.append(
                        f"{w.name} ({w.id}, {key[0]}"
                        + (f"-{key[1]}" if key[1] is not None else "")
                        + f") last voted on roll {lv[1]}"
                    )
                    continue
                holders.append(w)
        out: list[Member] = []
        flagged: list[str] = []
        for h in holders:
            notes: list[str] = []
            cau, note = resolve_caucus(h.id, h.party, member_caucus, caucus)
            if note:
                notes.append(note)
                flagged.append(f"{h.name} ({h.id})")
            if len(h.icpsrs) > 1:
                notes.append("party switch merged from multiple Voteview rows")
            out.append(
                Member(
                    id=h.id,
                    name=h.name,
                    party=h.party,
                    caucus=cau,
                    state=h.state,
                    district=h.district if chamber == "house" else None,
                    notes="; ".join(notes) or None,
                )
            )
        total = SEATS[chamber]
        if len(out) > total:
            raise ValueError(f"{chamber}: {len(out)} holders for {total} seats")
        bodies[chamber] = Body(seats=total, vacancies=total - len(out), members=out)
        lines.append(chamber_summary(chamber, out, total, f"{len(suspected)} suspected"))
        lines += [f"  suspected vacancy: {s}" for s in suspected]
        lines += [f"  caucus from party mapping: {f}" for f in flagged]
    unknown = sorted((vacate_set | keep_set | set(member_caucus)) - known_ids)
    if unknown:
        raise ValueError(f"ids not found among current seat holders: {', '.join(unknown)}")
    comp = Composition(schema_version=1, name=name, as_of=as_of or dt.date.today(), bodies=bodies)  # type: ignore[arg-type]
    return RosterReport(comp, lines)


def dump_composition(report: RosterReport) -> str:
    y = YAML()
    y.default_flow_style = False
    y.width = 120
    buf = io.StringIO()
    data = report.comp.model_dump(mode="json", exclude_defaults=True)
    data["schema_version"] = 1
    y.dump(data, buf)
    out: list[str] = []
    for ln in ["Generated by impsolver roster.", *report.lines]:
        out += textwrap.wrap(ln, 96, subsequent_indent="    ", drop_whitespace=False) or [""]
    header = "".join(f"# {ln.rstrip()}\n" for ln in out)
    return header + buf.getvalue()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="impsolver roster",
        description="Build a composition (who holds each seat) from Voteview member and vote "
        "files, or, with --from-results, from a CSV of certified election results.",
    )
    vv = ap.add_argument_group("from Voteview")
    vv.add_argument("--members", action="append", default=[], type=Path)
    vv.add_argument("--votes", action="append", default=[], type=Path)
    vv.add_argument("--keep", action="append", default=[], help="never mark ID as a vacancy")
    vv.add_argument("--vacancy-gap", type=int, default=None, help="default 50")
    rs = ap.add_argument_group("from certified results")
    rs.add_argument(
        "--from-results",
        type=Path,
        metavar="RESULTS.csv",
        help="columns chamber,state,district,name,party[,bioguide_id][,caucus]; one row per seat",
    )
    rs.add_argument("--source", help="who certified the results (cited in the file header)")
    rs.add_argument(
        "--previous",
        action="append",
        default=[],
        type=Path,
        help="earlier composition to match returning members against (repeatable)",
    )
    rs.add_argument(
        "--senate-holdovers",
        action="store_true",
        help="carry over senators from --previous whose seats were not up",
    )
    rs.add_argument(
        "--allow-missing", action="store_true", help="count seats with no row as vacancies"
    )
    ap.add_argument("--caucus", action="append", default=[], help="PARTY=BLOC")
    ap.add_argument(
        "--member-caucus",
        action="append",
        default=[],
        help="ID=BLOC ('none' = own party); beats --caucus",
    )
    ap.add_argument(
        "--vacate",
        action="append",
        default=[],
        help="treat ID's seat as vacant (e.g. resigned); with --senate-holdovers, a previous "
        "senator who does not hold over",
    )
    ap.add_argument(
        "--accessed",
        type=dt.date.fromisoformat,
        default=None,
        help="date the source files were downloaded (for the citation; default today)",
    )
    ap.add_argument("--as-of", type=dt.date.fromisoformat, default=None)
    ap.add_argument("--name", default=None, help="composition name (default us-119 from Voteview)")
    ap.add_argument("--out", type=Path)
    a = ap.parse_args(argv)
    try:
        if a.from_results is not None:
            rep = _from_results(a)
        else:
            if not a.members or not a.votes:
                raise ValueError("give --members and --votes, or --from-results")
            stray = [
                f
                for f, v in (
                    ("--source", a.source),
                    ("--previous", a.previous),
                    ("--senate-holdovers", a.senate_holdovers),
                    ("--allow-missing", a.allow_missing),
                )
                if v
            ]
            if stray:
                raise ValueError(f"{', '.join(stray)} only apply with --from-results")
            rep = build_roster(
                a.members,
                a.votes,
                parse_caucus(a.caucus),
                parse_mapping(a.member_caucus),
                a.keep,
                50 if a.vacancy_gap is None else a.vacancy_gap,
                a.as_of,
                a.name or "us-119",
                a.vacate,
                a.accessed,
            )
    except (OSError, ValueError, KeyError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    text = dump_composition(rep)
    if a.out:
        a.out.write_text(text, encoding="utf-8")
    else:
        sys.stdout.write(text)
    for ln in rep.lines:
        print(ln, file=sys.stderr)
    return 0


def _from_results(a: argparse.Namespace) -> RosterReport:
    from .roster_results import build_from_results

    if a.members or a.votes or a.keep or a.vacancy_gap is not None:
        raise ValueError("--members, --votes, --keep and --vacancy-gap are for the Voteview mode")
    if not a.source:
        raise ValueError("--from-results needs --source (who certified the results)")
    if not a.name:
        raise ValueError("--from-results needs --name (for example us-120)")
    return build_from_results(
        a.from_results,
        a.source,
        a.name,
        a.previous,
        parse_caucus(a.caucus),
        parse_mapping(a.member_caucus),
        a.as_of,
        a.accessed,
        a.allow_missing,
        a.senate_holdovers,
        a.vacate,
    )


if __name__ == "__main__":
    raise SystemExit(main())
