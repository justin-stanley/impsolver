# SPDX-FileCopyrightText: 2026 Justin Stanley
# SPDX-License-Identifier: MIT
"""Build a composition for a new Congress from a CSV of certified election results.

The CSV has the columns ``chamber,state,district,name,party`` and, optionally, ``bioguide_id``
and ``caucus``. Each row is one seat. A row with a blank name is a vacant seat. Returning members
keep their Bioguide ID; when the results omit it, a member of ``--previous`` with the same
chamber, state, surname and a compatible given name is matched and flagged. A match is accepted
only when it is one to one: a row with several candidates, or a previous member who is the
candidate of several rows, is never matched. Members without an ID get a placeholder such as
``new:CA-06`` (House) or ``new:CA-S1`` (Senate) until the Clerk assigns one.
"""

from __future__ import annotations

import csv
import datetime as dt
import re
import unicodedata
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

from .model import Body, Composition, Member
from .roster import SEATS, TERRITORIES, RosterReport, chamber_summary, resolve_caucus

REQUIRED = ("chamber", "state", "district", "name", "party")
OPTIONAL = ("bioguide_id", "caucus")
BIOGUIDE = re.compile(r"[A-Z]\d{6}")
STATE = re.compile(r"[A-Z]{2}")
AT_LARGE = {"AL", "0", "00"}
PARTY_CODE = re.compile(r"[A-Z]{1,4}")
SUFFIXES = {"jr", "sr", "ii", "iii", "iv", "v"}
PARTY_WORDS = {
    "republican": "R",
    "democrat": "D",
    "democratic": "D",
    "independent": "I",
}


@dataclass
class Row:
    line: int
    chamber: str
    state: str
    district: int | None
    name: str
    party: str
    bioguide: str
    caucus: str
    at_large: bool = False


def _norm(text: str) -> list[str]:
    """Lower-case ASCII tokens without punctuation or generational suffixes."""
    s = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()
    toks = re.sub(r"[^a-z0-9\- ]+", " ", s).replace("-", " - ").split()
    # Generational suffixes only at the end ("Smith Jr"), so a given name or initial "V" stays.
    while len(toks) > 1 and toks[-1] in SUFFIXES:
        toks.pop()
    return " ".join(toks).replace(" - ", "-").split()


def _drop_suffix(name: str) -> str:
    """Strip a trailing ", Jr." or ", III" so it is not read as "Last, First"."""
    head, sep, tail = name.rpartition(",")
    # "LAST, First, Jr." or "First Last, Jr." -- but not "SMITH, V.", where V is the given name.
    full_head = "," in head or len(_norm_raw(head)) > 1
    if sep and full_head and tail.strip() and all(t in SUFFIXES for t in _norm_raw(tail)):
        return _drop_suffix(head)
    return name


def _norm_raw(text: str) -> list[str]:
    s = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9 ]+", " ", s).split()


def surname(name: str) -> list[str]:
    """Surname tokens: the text before the first comma ("LAST, First"), else the last word."""
    name = _drop_suffix(name)
    if "," in name:
        return _norm(name.split(",", 1)[0])
    toks = _norm(name)
    return toks[-1:]


def same_surname(results_name: str, prev_name: str) -> bool:
    """True when the results name ends with (or, in "Last, First" form, is) the previous surname.

    ``"Derrick Van Orden"`` matches ``"VAN ORDEN, Derrick"``, and ``"Nick Begich III"`` matches
    ``"BEGICH, Nicholas J., III"``.
    """
    prev = surname(prev_name)
    if not prev:
        return False
    results_name = _drop_suffix(results_name)
    if "," in results_name:
        return surname(results_name) == prev
    toks = _norm(results_name)
    return len(toks) > len(prev) and toks[-len(prev) :] == prev


def given_names(name: str, n_surname: int = 1) -> list[str]:
    """Given-name tokens: after the first comma ("LAST, First"), else before the surname."""
    name = _drop_suffix(name)
    if "," in name:
        return _norm(name.split(",", 1)[1])
    toks = _norm(name)
    return toks[:-n_surname]


def _given_ok(a: str, b: str, initials: bool) -> bool:
    """Equal, a prefix of 3+ letters (Nick / Nickolas) or, if allowed, a lone initial."""
    if a == b:
        return True
    short, long_ = sorted((a, b), key=len)
    return long_.startswith(short) and (len(short) >= 3 or (initials and len(short) == 1))


def same_given(results_name: str, prev_name: str) -> bool:
    """True when the given names are compatible.

    The first given names may match as equal, as a 3-letter prefix or as a lone initial
    (``"J. Smith"`` and ``"SMITH, John"``). A first name may also equal another given name of
    the other side (``"Robert Smith"`` and ``"SMITH, J. Robert"``), but not by initial alone.
    """
    pa = given_names(prev_name)
    ra = given_names(results_name, max(len(surname(prev_name)), 1))
    if not ra or not pa:
        return False
    if _given_ok(ra[0], pa[0], initials=True):
        return True
    return any(_given_ok(ra[0], t, False) for t in pa) or any(
        _given_ok(pa[0], t, False) for t in ra
    )


def _party(text: str, where: str) -> str:
    t = text.strip()
    if t.lower() in PARTY_WORDS:
        return PARTY_WORDS[t.lower()]
    if t and not PARTY_CODE.fullmatch(t.upper()):
        raise ValueError(
            f"{where}: party {t!r} is not a code such as R, D or I (or Republican, Democrat, "
            "Democratic, Independent); write the code and set the caucus column if needed"
        )
    return t.upper()


def read_results(path: Path) -> tuple[list[Row], list[str]]:
    """Parse and check the results CSV. Returns the rows and the skipped-row notes."""
    rows: list[Row] = []
    skipped: list[str] = []
    with open(path, newline="", encoding="utf-8-sig") as fh:
        rd = csv.DictReader(fh)
        cols = [c.strip() for c in rd.fieldnames or []]
        missing = [c for c in REQUIRED if c not in cols]
        if missing:
            raise ValueError(f"{path.name}: missing column(s) {', '.join(missing)}")
        unknown = [c for c in cols if c not in REQUIRED + OPTIONAL]
        if unknown:
            raise ValueError(f"{path.name}: unknown column(s) {', '.join(unknown)}")
        for raw in rd:
            i = rd.line_num  # the physical line, even after a quoted field with a line break
            where = f"{path.name} line {i}"
            if None in raw:
                raise ValueError(
                    f"{where}: more fields than the header has columns; put a name that contains "
                    'a comma in double quotes, e.g. "SMITH, John"'
                )
            r = {k.strip(): (v or "").strip() for k, v in raw.items()}
            chamber = r["chamber"].lower()
            if chamber not in SEATS:
                raise ValueError(f"{where}: chamber must be house or senate, got {r['chamber']!r}")
            state = r["state"].upper()
            if state in TERRITORIES:
                skipped.append(f"{state} {r['name'] or '(blank)'}: non-voting delegate")
                continue
            if not STATE.fullmatch(state):
                raise ValueError(f"{where}: state must be a 2-letter code, got {r['state']!r}")
            district: int | None = None
            d = r["district"].upper()
            if chamber == "house":
                if d in AT_LARGE:
                    district = 1
                elif d.isdigit() and int(d) == 0:
                    raise ValueError(
                        f"{where}: write an at-large district as AL, 0 or 00, got {d!r}"
                    )
                elif d.isdigit():
                    district = int(d)
                else:
                    raise ValueError(f"{where}: House district must be a number or AL, got {d!r}")
            elif d:
                raise ValueError(f"{where}: leave district blank for the Senate, got {d!r}")
            bio = r.get("bioguide_id", "")
            if bio and not BIOGUIDE.fullmatch(bio):
                raise ValueError(f"{where}: bad bioguide_id {bio!r} (expected e.g. A000360)")
            if r["name"] and not r["party"]:
                raise ValueError(f"{where}: {r['name']} has no party")
            rows.append(
                Row(
                    i,
                    chamber,
                    state,
                    district,
                    r["name"],
                    _party(r["party"], where),
                    bio,
                    r.get("caucus", ""),
                    chamber == "house" and d in AT_LARGE,
                )
            )
    by_state: dict[str, list[Row]] = defaultdict(list)
    for row in rows:
        if row.chamber == "house":
            by_state[row.state].append(row)
    for st, group in by_state.items():
        al = [x for x in group if x.at_large]
        if al and any(x.district != 1 for x in group):
            raise ValueError(
                f"{path.name} line {al[0].line}: {st} is marked at-large but also has "
                "numbered districts; write the district number"
            )
    return rows, skipped


def _seat(chamber: str, state: str, district: int | None) -> str:
    return f"{state}-{district:02d}" if chamber == "house" and district is not None else state


def build_from_results(
    results: Path,
    source: str,
    name: str,
    previous: list[Path] | None = None,
    caucus: dict[str, str] | None = None,
    member_caucus: dict[str, str] | None = None,
    as_of: dt.date | None = None,
    accessed: dt.date | None = None,
    allow_missing: bool = False,
    senate_holdovers: bool = False,
    vacate: list[str] | None = None,
) -> RosterReport:
    """Build a composition from certified results, matching returning members to ``previous``.

    Args:
        results: The results CSV (see the module docstring).
        source: Who certified the results, cited in the header (e.g. the Clerk's statistics).
        name: Composition name, e.g. ``us-120``.
        previous: Earlier compositions; their members are the candidates for "returning".
        caucus: Party to bloc, as for the Voteview roster (``--caucus I=D``).
        member_caucus: Member id to bloc; beats ``caucus`` and is beaten by the CSV column.
        allow_missing: Count seats with no row as vacancies instead of failing.
        senate_holdovers: Carry over senators from ``previous`` whose seats were not up.
        vacate: Previous senators who are not holdovers (resigned, retired, defeated).
    """
    from .loader import load_composition

    caucus = caucus or {}
    member_caucus = member_caucus or {}
    vacate_set = set(vacate or [])
    if senate_holdovers and not previous:
        raise ValueError("--senate-holdovers needs --previous")
    if vacate_set and not senate_holdovers:
        raise ValueError("with --from-results, --vacate applies only with --senate-holdovers")
    rows, skipped = read_results(results)
    prev: dict[str, Member] = {}
    prev_chamber: dict[str, str] = {}
    prev_names: list[str] = []
    # With several --previous rosters, the newest (by as_of) wins for a member listed in more than
    # one, whatever the order they are given in.
    loaded = sorted(((load_composition(p), p) for p in previous or []), key=lambda cp: cp[0].as_of)
    for comp, p in loaded:
        prev_names.append(f"{p.name} ({comp.name}, as of {comp.as_of.isoformat()})")
        for ch, body in comp.bodies.items():
            for m in body.roster:
                if not STATE.fullmatch(m.state):
                    raise ValueError(
                        f"--previous {p.name}: member {m.id} has no state; --previous needs a "
                        "roster of named members with states (not party_shorthand)"
                    )
                prev[m.id] = m
                prev_chamber[m.id] = ch
    unknown = sorted(vacate_set - set(prev))
    if unknown:
        raise ValueError(f"--vacate ids not found in --previous: {', '.join(unknown)}")

    lines = [f"Data: {source.rstrip('.')}. Accessed {(accessed or dt.date.today()).isoformat()}."]
    lines[0] += f" Files: {results.name}."
    if prev_names:
        lines.append("Returning members matched against " + "; ".join(prev_names) + ".")
    lines += [f"skipped: {s}" for s in skipped]

    prev_districts: dict[str, int] = {}
    for i, m in prev.items():
        if prev_chamber[i] == "house" and m.district is not None:
            prev_districts[m.state] = max(prev_districts.get(m.state, 0), m.district)
    for r in rows:
        top = prev_districts.get(r.state)
        if r.at_large and top is not None and top > 1:
            raise ValueError(
                f"{results.name} line {r.line}: {r.state} is marked at-large but --previous lists "
                f"districts up to {top}; write the district number"
            )

    used_ids: set[str] = set()
    reserved = {r.bioguide for r in rows if r.bioguide}
    bodies: dict[str, Body] = {}
    for chamber in ("house", "senate"):
        crow = [r for r in rows if r.chamber == chamber]
        seats_listed: dict[str, list[Row]] = defaultdict(list)
        for r in crow:
            seats_listed[_seat(chamber, r.state, r.district)].append(r)
        for seat, group in seats_listed.items():
            cap = 1 if chamber == "house" else 2
            if len(group) > cap:
                at = ", ".join(str(r.line) for r in group)
                raise ValueError(
                    f"{chamber} {seat}: {len(group)} rows for {cap} seat(s) (lines {at})"
                )
        out: list[Member] = []
        notes_out: list[str] = []
        new_ct: dict[str, int] = defaultdict(int)
        vacant_rows = [r for r in crow if not r.name]
        cands, near, claims = _candidates(crow, prev, prev_chamber, chamber, reserved)
        for r in crow:
            top = prev_districts.get(r.state)
            if chamber == "house" and top is not None and (r.district or 0) > top:
                notes_out.append(
                    f"check district: {_seat(chamber, r.state, r.district)} (line {r.line}) is "
                    f"above the highest {r.state} district in --previous ({top})"
                )
        for r in crow:
            if not r.name:
                continue
            seat = _seat(chamber, r.state, r.district)
            notes: list[str] = []
            if r.bioguide:
                mid = r.bioguide
                if previous and mid not in prev:
                    notes.append("bioguide id not in the previous composition")
                    notes_out.append(f"new member: {r.name} ({mid}, {seat}) not in --previous")
            else:
                c = cands[r.line]
                if len(c) == 1 and len(claims[c[0].id]) == 1:
                    mid = c[0].id
                    diff = []
                    if c[0].party != r.party:
                        diff.append(f"party {c[0].party} -> {r.party}")
                    if chamber == "house" and c[0].district != r.district:
                        diff.append(f"district {c[0].district} -> {r.district}")
                    changed = f"; {', '.join(diff)}" if diff else ""
                    notes.append(
                        f"matched to {c[0].name} by name and state; results gave no bioguide id"
                        + changed
                    )
                    notes_out.append(
                        f"name match: {r.name} ({seat}) -> {c[0].name} ({mid}){changed}"
                    )
                else:
                    if chamber == "house":
                        mid = f"new:{seat}"
                    else:
                        new_ct[r.state] += 1
                        mid = f"new:{r.state}-S{new_ct[r.state]}"
                    notes.append("new member; placeholder id until a bioguide id is assigned")
                    if len(c) > 1:
                        both = ", ".join(f"{m.name} ({m.id})" for m in c)
                        notes.append(f"ambiguous name match ({both}); add bioguide_id")
                        notes_out.append(f"ambiguous name match: {r.name} ({seat}) -> {both}")
                    elif c:
                        rivals = ", ".join(
                            f"{x.name} (line {x.line})" for x in claims[c[0].id] if x is not r
                        )
                        what = f"{c[0].name} ({c[0].id})"
                        notes.append(
                            f"ambiguous name match ({what} also matches {rivals}); add bioguide_id"
                        )
                        notes_out.append(
                            f"ambiguous name match: {r.name} ({seat}) -> {what}, "
                            f"also matched by {rivals}"
                        )
                    elif near[r.line]:
                        who = ", ".join(f"{m.name} ({m.id})" for m in near[r.line])
                        notes.append(
                            f"same surname and state as {who} but a different given name; "
                            "not matched (add bioguide_id if it is the same person)"
                        )
                        notes_out.append(
                            f"new member: {r.name} ({mid}); surname matches {who}, given name "
                            "does not"
                        )
                    else:
                        notes_out.append(f"new member: {r.name} ({mid})")
            if mid in used_ids:
                raise ValueError(f"{results.name} line {r.line}: id {mid} appears twice")
            used_ids.add(mid)
            pm = prev.get(mid)
            if r.caucus:
                cau: str | None = None if r.caucus.lower() == "none" else r.caucus
            elif mid not in member_caucus and pm and pm.caucus and pm.party == r.party:
                cau = pm.caucus
                notes.append(f"caucus {cau} kept from the previous composition")
                notes_out.append(f"caucus kept from --previous: {r.name} ({mid}) -> {cau}")
            else:
                cau, note = resolve_caucus(mid, r.party, member_caucus, caucus)
                if note:
                    notes.append(note)
                    notes_out.append(f"caucus from party mapping: {r.name} ({mid})")
                if mid not in member_caucus and pm and pm.caucus:
                    notes.append(
                        f"previous caucus {pm.caucus} not kept: party changed from {pm.party} "
                        f"to {r.party}"
                    )
                    notes_out.append(f"party changed: {r.name} ({mid}) {pm.party} -> {r.party}")
            out.append(
                Member(
                    id=mid,
                    name=r.name,
                    party=r.party,
                    caucus=cau,
                    state=r.state,
                    district=r.district,
                    notes="; ".join(notes) or None,
                )
            )
        other = sorted(
            {m.party for m in out if m.party not in ("R", "D", "I") and m.caucus is None}
        )
        for party in other:
            n = sum(m.party == party and m.caucus is None for m in out)
            notes_out.append(
                f"party {party} is not R, D or I: {n} member(s) form their own bloc "
                f"(map it with --caucus {party}=BLOC or the caucus column if that is not meant)"
            )
        held: list[Member] = []
        if chamber == "senate" and senate_holdovers:
            held = _holdovers(seats_listed, prev, prev_chamber, vacate_set, used_ids)
            for m in held:
                if m.id in member_caucus or not m.caucus:
                    cau, note = resolve_caucus(m.id, m.party, member_caucus, caucus)
                    if note:
                        notes_out.append(f"caucus from party mapping: {m.name} ({m.id})")
                else:
                    cau = m.caucus
                out.append(
                    Member(
                        id=m.id,
                        name=m.name,
                        party=m.party,
                        caucus=cau,
                        state=m.state,
                        notes="holdover from the previous composition",
                    )
                )
                used_ids.add(m.id)
            notes_out.append(f"holdovers from --previous: {len(held)}")
        total = SEATS[chamber]
        listed = sum(len(g) for g in seats_listed.values()) + len(held)
        if listed > total or len(out) > total:
            raise ValueError(f"{chamber}: {max(listed, len(out))} seats listed for {total}")
        missing = total - listed
        if missing and not allow_missing:
            raise ValueError(
                f"{chamber}: the results list {listed} of {total} seats. Add a row for every seat "
                "(blank name for a vacancy)"
                + (", pass --senate-holdovers" if chamber == "senate" else "")
                + " or pass --allow-missing"
            )
        bodies[chamber] = Body(seats=total, vacancies=total - len(out), members=out)
        flagged = [n for n in notes_out if not n.startswith("holdovers")]
        lines.append(chamber_summary(chamber, out, total, f"{len(flagged)} flagged"))
        lines += [
            f"  vacant seat: {_seat(chamber, r.state, r.district)} (blank row, line {r.line})"
            for r in vacant_rows
        ]
        if missing:
            lines.append(f"  not in results: {missing} seats counted as vacant (--allow-missing)")
        lines += [f"  {n}" for n in notes_out]
    unknown = sorted(set(member_caucus) - used_ids)
    if unknown:
        raise ValueError(f"--member-caucus ids not found among seat holders: {', '.join(unknown)}")
    comp = Composition(schema_version=1, name=name, as_of=as_of or dt.date.today(), bodies=bodies)  # type: ignore[arg-type]
    return RosterReport(comp, lines)


def _candidates(
    crow: list[Row],
    prev: dict[str, Member],
    prev_chamber: dict[str, str],
    chamber: str,
    reserved: set[str],
) -> tuple[dict[int, list[Member]], dict[int, list[Member]], dict[str, list[Row]]]:
    """All name-match candidate pairs for the rows without a bioguide id, before any is assigned.

    Returns, by results line, the previous members with the same chamber, state, surname and a
    compatible given name (``cands``) and those with only the surname (``near``), and, by
    previous id, the rows that name that member as a candidate (``claims``). A pair is accepted
    only when both sides have exactly one candidate, so the outcome does not depend on row order.
    """
    pool = [m for i, m in prev.items() if prev_chamber[i] == chamber and i not in reserved]
    cands: dict[int, list[Member]] = {}
    near: dict[int, list[Member]] = {}
    claims: dict[str, list[Row]] = defaultdict(list)
    for r in crow:
        if not r.name or r.bioguide:
            continue
        same = [m for m in pool if m.state == r.state and same_surname(r.name, m.name)]
        cands[r.line] = [m for m in same if same_given(r.name, m.name)]
        near[r.line] = [m for m in same if m not in cands[r.line]]
        for m in cands[r.line]:
            claims[m.id].append(r)
    return cands, near, claims


def _holdovers(
    seats_listed: dict[str, list[Row]],
    prev: dict[str, Member],
    prev_chamber: dict[str, str],
    vacate: set[str],
    used: set[str],
) -> list[Member]:
    """Previous senators whose seats were not up, state by state.

    A state keeps 2 - (rows listed) holdovers. The candidates are the state's previous senators
    who are not in the results and not vacated. When there are more candidates than open seats the
    tool cannot tell whose term continues, so it stops and asks for ``--vacate`` or a CSV row.
    """
    held: list[Member] = []
    states = sorted(
        {m.state for i, m in prev.items() if prev_chamber[i] == "senate"} | set(seats_listed)
    )
    for st in states:
        open_seats = 2 - len(seats_listed.get(st, []))
        cands = [
            m
            for i, m in prev.items()
            if prev_chamber[i] == "senate" and m.state == st and i not in vacate and i not in used
        ]
        if len(cands) > open_seats:
            names = ", ".join(f"{m.name} ({m.id})" for m in cands)
            raise ValueError(
                f"senate {st}: {len(cands)} previous senators ({names}) for {open_seats} "
                "holdover seat(s); --vacate the ones leaving or list the seat in the results"
            )
        held += cands
    return held
