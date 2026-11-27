# SPDX-FileCopyrightText: 2026 Justin Stanley
# SPDX-License-Identifier: MIT
"""Load a scenario with its rules, composition and alignment, ready for evaluation."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import numpy.typing as npt

from .loader import (
    load_alignment,
    load_composition,
    load_rules,
    load_scenario,
    resolve,
    resolve_rules,
)
from .members import Resolver
from .model import STAR, Alignment, Chamber, Composition, Member, RuleSet, Scenario
from .priors import apply_defection_prior


class ScenarioError(ValueError):
    """A scenario refers to something that cannot exist under its rules."""


def check_references(rules: RuleSet, comp: Composition, scenario: Scenario) -> list[str]:
    """Raise on references that are wrong under any composition; return warnings for the rest.

    Stage keys and shift articles are checked strictly. Member ids and blocs are only warned
    about, because one scenario may be run against several compositions (``compare``).
    """
    stages = {s.id for s in rules.stages} | {STAR}
    errors: list[str] = []

    def stage_keys(where: str, table: dict[str, float]) -> None:
        bad = sorted(set(table) - stages)
        if bad:
            errors.append(f"{where}: unknown stage key(s) {', '.join(bad)}")

    for bloc, table in scenario.party_priors.items():
        stage_keys(f"party_priors.{bloc}", table)
    for mid, table in scenario.overrides.items():
        stage_keys(f"overrides.{mid}", table)
    for body in comp.bodies.values():
        for m in body.roster:
            stage_keys(f"member {m.id} p_pro", m.p_pro)
    for sh in scenario.shifts:
        if sh.stage is not None and sh.stage not in stages:
            errors.append(f"shift {sh.label!r}: unknown stage {sh.stage}")
        if sh.article is not None and sh.article not in scenario.articles:
            errors.append(f"shift {sh.label!r}: article {sh.article} is not in articles")
    if errors:
        raise ScenarioError("; ".join(errors))
    ids = {m.id for b in comp.bodies.values() for m in b.roster}
    blocs = {m.bloc for b in comp.bodies.values() for m in b.roster}
    warnings = [
        f"override for {mid} matches no member of composition {comp.name}"
        for mid in sorted(set(scenario.overrides) - ids)
    ]
    warnings += [
        f"party_priors bloc {b} matches no member of composition {comp.name}"
        for b in sorted(set(scenario.party_priors) - blocs)
    ]
    warnings += [
        f"shift {sh.label!r} bloc {sh.bloc} matches no member of composition {comp.name}"
        for sh in scenario.shifts
        if sh.bloc != STAR and sh.bloc not in blocs
    ]
    if scenario.attendance == "fixed" and scenario.absence_rate > 0:
        warnings.append("absence_rate has no effect unless attendance is random")
    return warnings


@dataclass
class Prepared:
    rules: RuleSet
    comp: Composition
    scenario: Scenario
    alignment: Alignment | None
    source: str = "<memory>"
    warnings: list[str] = field(default_factory=list)
    resolver: Resolver = field(init=False)

    def __post_init__(self) -> None:
        self.resolver = Resolver(self.scenario)

    def members(self, chamber: Chamber) -> list[Member]:
        return self.comp.bodies[chamber].roster

    def probs(
        self, chamber: Chamber, stage: str, article: str, extra: float = 0.0
    ) -> npt.NDArray[np.float64]:
        return np.array(
            [self.resolver.resolve(m, stage, article, extra) for m in self.members(chamber)],
            dtype=float,
        )

    def present_mask(self, chamber: Chamber) -> npt.NDArray[np.bool_]:
        return np.array([m.attendance == "present" for m in self.members(chamber)], dtype=bool)

    def absence_rates(self, chamber: Chamber) -> npt.NDArray[np.float64]:
        """Per-member chance of missing a vote, used when ``attendance`` is ``random``.

        Resolved in order: the member's ``p_absent``, the alignment file's missed-vote rate
        (``n_missed / n_possible``), then the scenario's ``absence_rate``.
        """
        missed: dict[str, float] = {}
        if self.alignment is not None and chamber in self.alignment.bodies:
            for am in self.alignment.bodies[chamber].members:
                rate = am.missed_rate
                if rate is not None:
                    missed[am.id] = rate
        default = self.scenario.absence_rate
        return np.array(
            [
                m.p_absent if m.p_absent is not None else missed.get(m.id, default)
                for m in self.members(chamber)
            ],
            dtype=float,
        )


def prepare_objects(
    rules: RuleSet,
    comp: Composition,
    scenario: Scenario,
    alignment: Alignment | None = None,
    source: str = "<memory>",
) -> Prepared:
    warnings = check_references(rules, comp, scenario)
    if scenario.defection_prior is not None:
        if alignment is None:
            raise ValueError("defection_prior needs an alignment")
        comp = apply_defection_prior(scenario.defection_prior, scenario, comp, rules, alignment)
    return Prepared(rules, comp, scenario, alignment, source, warnings)


def prepare(path: str | Path, composition: str | Path | None = None) -> Prepared:
    """Load a scenario file with its rules, composition and alignment.

    Args:
        path: Scenario YAML. Relative paths inside it resolve against its folder.
        composition: Optional composition that replaces the one the scenario names.

    Returns:
        A ``Prepared`` scenario whose ``warnings`` list unknown member ids or blocs.
    """
    return prepare_objects(*load_parts(path, composition), str(path))


def load_parts(
    path: str | Path, composition: str | Path | None = None
) -> tuple[RuleSet, Composition, Scenario, Alignment | None]:
    """The rules, raw composition, scenario and alignment that ``prepare`` combines."""
    scen = load_scenario(path)
    rules = load_rules(resolve_rules(scen.rules, path))
    comp = load_composition(composition if composition else resolve(scen.composition, path))
    align = load_alignment(resolve(scen.alignment, path)) if scen.alignment else None
    return rules, comp, scen, align
