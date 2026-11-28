# SPDX-FileCopyrightText: 2026 Justin Stanley
# SPDX-License-Identifier: MIT
"""Read user-supplied member scores (``id,score,source``) and standardize them per source.

impsolver ships no scores. The user supplies a file from a source whose license they have
checked, and names that source (with its citation) in the ``source`` column.
"""

from __future__ import annotations

import csv
import math
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

from .model import Composition

COLUMNS = ("id", "score", "source")


class ScoreError(ValueError):
    pass


@dataclass(frozen=True)
class MemberScore:
    raw: float
    z: float
    source: str


@dataclass(frozen=True)
class SourceStats:
    source: str
    n: int
    mean: float
    sd: float


def read_member_scores(path: Path) -> tuple[dict[str, MemberScore], list[SourceStats]]:
    """Scores by id, each standardized (z-score, population sd) within its ``source``.

    The file should hold the source's whole reference set, not only the members to be scored,
    so that the mean and spread describe the source's scale.
    """
    rows: dict[str, tuple[float, str]] = {}
    with path.open(newline="", encoding="utf-8-sig") as f:  # tolerate a spreadsheet BOM
        reader = csv.DictReader(f)
        if tuple(reader.fieldnames or ()) != COLUMNS:
            raise ScoreError(f"{path}: header must be exactly {','.join(COLUMNS)}")
        for r in reader:
            n = reader.line_num  # the physical line, even after a quoted field with a line break
            if None in r or None in r.values():
                # An unquoted comma in the citation would otherwise cut it silently and could
                # merge two sources into one standardization group.
                raise ScoreError(
                    f"{path}:{n}: expected 3 fields (id,score,source); put the source in double "
                    'quotes if it contains commas, e.g. A000001,0.5,"Author, Title, v2, URL"'
                )
            mid, src = (r["id"] or "").strip(), (r["source"] or "").strip()
            if not mid:
                raise ScoreError(f"{path}:{n}: empty id")
            if not src:
                raise ScoreError(f"{path}:{n}: empty source for {mid}")
            try:
                val = float(r["score"])
            except (TypeError, ValueError):
                raise ScoreError(f"{path}:{n}: score {r['score']!r} is not a number") from None
            if not math.isfinite(val):
                raise ScoreError(f"{path}:{n}: score for {mid} is not finite")
            if mid in rows:
                raise ScoreError(f"{path}:{n}: duplicate id {mid}")
            rows[mid] = (val, src)
    groups: dict[str, list[float]] = defaultdict(list)
    for val, src in rows.values():
        groups[src].append(val)
    stats: dict[str, SourceStats] = {}
    for src, vals in sorted(groups.items()):
        if len(vals) < 2:
            raise ScoreError(f"{path}: source {src!r} has {len(vals)} row; need at least 2")
        mean = sum(vals) / len(vals)
        sd = math.sqrt(sum((v - mean) ** 2 for v in vals) / len(vals))
        if sd == 0.0:
            raise ScoreError(f"{path}: source {src!r} scores do not vary")
        stats[src] = SourceStats(src, len(vals), mean, sd)
    out = {
        mid: MemberScore(val, (val - stats[src].mean) / stats[src].sd, src)
        for mid, (val, src) in rows.items()
    }
    return out, list(stats.values())


def attach_scores(
    comp: Composition, scores: dict[str, MemberScore], stats: list[SourceStats]
) -> list[str]:
    """Set ``score`` / ``score_source`` on matching members in place; return report lines."""
    matched: dict[str, int] = defaultdict(int)
    for body in comp.bodies.values():
        members = body.roster
        for i, m in enumerate(members):
            s = scores.get(m.id)
            if s is None:
                continue
            members[i] = m.model_copy(update={"score": round(s.z, 6), "score_source": s.source})
            matched[s.source] += 1
        body.members = members
    if not matched:
        raise ScoreError("member scores matched no current seat holder; check that ids match")
    lines = [
        f"Scores: {st.source} ({st.n} rows, mean {st.mean:.4g}, sd {st.sd:.4g}; "
        f"{matched[st.source]} seat holders scored, standardized within source)"
        for st in stats
    ]
    return lines
