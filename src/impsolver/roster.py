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
            if h.id in member_caucus:
                c = member_caucus[h.id]
                cau: str | None = None if c.lower() == "none" else c
            elif h.party in caucus:
                cau = caucus[h.party]
                notes.append(f"caucus {cau} set from party mapping {h.party}={cau}")
                flagged.append(f"{h.name} ({h.id})")
            else:
                cau = None
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
        parties = Counter(m.party for m in out)
        lines.append(
            f"{chamber}: {len(out)} members ("
            + "/".join(f"{n}{p}" for p, n in sorted(parties.items(), key=lambda kv: -kv[1]))
            + f"), {total - len(out)} vacancies, {len(suspected)} suspected"
        )
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
    ap = argparse.ArgumentParser(prog="impsolver roster", description=__doc__)
    ap.add_argument("--members", action="append", required=True, type=Path)
    ap.add_argument("--votes", action="append", required=True, type=Path)
    ap.add_argument("--caucus", action="append", default=[], help="PARTY=BLOC")
    ap.add_argument(
        "--member-caucus",
        action="append",
        default=[],
        help="ID=BLOC ('none' = own party); beats --caucus",
    )
    ap.add_argument("--keep", action="append", default=[], help="never mark ID as a vacancy")
    ap.add_argument(
        "--vacate", action="append", default=[], help="treat ID's seat as vacant (e.g. resigned)"
    )
    ap.add_argument("--vacancy-gap", type=int, default=50)
    ap.add_argument(
        "--accessed",
        type=dt.date.fromisoformat,
        default=None,
        help="date the Voteview files were downloaded (for the citation; default today)",
    )
    ap.add_argument("--as-of", type=dt.date.fromisoformat, default=None)
    ap.add_argument("--name", default="us-119")
    ap.add_argument("--out", type=Path)
    a = ap.parse_args(argv)
    try:
        rep = build_roster(
            a.members,
            a.votes,
            parse_caucus(a.caucus),
            parse_mapping(a.member_caucus),
            a.keep,
            a.vacancy_gap,
            a.as_of,
            a.name,
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


if __name__ == "__main__":
    raise SystemExit(main())
