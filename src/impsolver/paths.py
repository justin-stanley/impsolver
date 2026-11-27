# SPDX-FileCopyrightText: 2026 Justin Stanley
# SPDX-License-Identifier: MIT
"""Walk a rule set's stage graph into ordered paths."""

from __future__ import annotations

from dataclasses import dataclass

from .model import RuleSet, Scenario, Stage


@dataclass(frozen=True)
class Path:
    name: str
    stages: tuple[Stage, ...]  # required stages, ending at the terminal stage
    optional: tuple[Stage, ...]  # stages evaluated only if the terminal stage passes

    @property
    def all_stages(self) -> tuple[Stage, ...]:
        return self.stages + self.optional


class PathError(Exception):
    pass


def build_path(rules: RuleSet, name: str) -> Path:
    spec = rules.path(name)
    required: list[Stage] = []
    optional: list[Stage] = []
    seen: set[str] = set()
    sid: str | None = spec.start
    terminal_seen = False
    while sid is not None:
        if sid in seen:
            raise PathError(f"cycle at stage {sid}")
        seen.add(sid)
        st = rules.stage(sid)
        if terminal_seen:
            optional.append(st)
        else:
            if st.optional:
                raise PathError(f"optional stage {sid} comes before the terminal stage")
            required.append(st)
            terminal_seen = st.terminal_on_pass
        sid = st.next[0] if st.next else None
    if not terminal_seen:
        raise PathError(f"path {name} has no terminal_on_pass stage")
    return Path(name=name, stages=tuple(required), optional=tuple(optional))


def path_for(rules: RuleSet, scenario: Scenario, name: str) -> Path:
    spec = rules.path(name)
    if spec.requires == "committee_reports" and not scenario.committee_reports:
        raise PathError(f"path {name} requires committee_reports: true in the scenario")
    if spec.requires not in (None, "committee_reports"):
        raise PathError(f"path {name} has an unknown requirement {spec.requires!r}")
    return build_path(rules, name)
