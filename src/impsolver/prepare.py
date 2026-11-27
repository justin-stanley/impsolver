# SPDX-FileCopyrightText: 2026 Justin Stanley
# SPDX-License-Identifier: MIT
"""Load a scenario with its rules, composition and alignment, ready for evaluation."""

from __future__ import annotations

from collections.abc import Mapping
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
from .priors import apply_defection_prior, apply_score_prior
from .uncertainty import Bound, bound_scenario, has_uncertainty


class ScenarioError(ValueError):
    """A scenario refers to something that cannot exist under its rules."""


def check_references(rules: RuleSet, comp: Composition, scenario: Scenario) -> list[str]:
    """Raise on references that are wrong under any composition; return warnings for the rest.

    Stage keys and shift articles are checked strictly. Member ids and blocs are only warned
    about, because one scenario may be run against several compositions (``compare``).
    """
    stages = {s.id for s in rules.stages} | {STAR}
    errors: list[str] = []

    def stage_keys(where: str, table: Mapping[str, object]) -> None:
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
    scored_blocs = {m.bloc for b in comp.bodies.values() for m in b.roster if m.score is not None}
    warnings += [
        f"score_prior bloc {b} matches no scored member of composition {comp.name}"
        for b in sorted(set(scenario.score_prior) - scored_blocs)
    ]
    if scenario.uncertainty_draws > 0 and not has_uncertainty(scenario):
        warnings.append("uncertainty_draws has no effect: no prior is a range or a beta")
    return warnings


@dataclass
class Prepared:
    rules: RuleSet
    comp: Composition
    scenario: Scenario
    alignment: Alignment | None
    source: str = "<memory>"
    warnings: list[str] = field(default_factory=list)
    # The composition before any defection prior, kept so priors can be resampled.
    input_comp: Composition | None = None
    resolver: Resolver = field(init=False)

    def __post_init__(self) -> None:
        self.resolver = Resolver(self.scenario)

    def members(self, chamber: Chamber) -> list[Member]:
        return self.comp.bodies[chamber].roster

    def probs(
        self,
        chamber: Chamber,
        stage: str,
        article: str,
        extra: float = 0.0,
        bound: Bound = "point",
    ) -> npt.NDArray[np.float64]:
        """P(PRO) per member. ``bound`` picks the point value or the low / high bound of
        uncertain priors (see :mod:`impsolver.uncertainty`).

        With a defection prior, members whose party prior was adjusted carry one number in
        ``p_pro``; their bounds come from re-applying the prior to the low and high party values.
        The adjustment pushes away from the party's lean, so it is not monotone across 0.5: the
        lower of the two results is the low bound and the higher is the high bound.
        """
        if bound != "point" and self.scenario.defection_prior is not None:
            if self.input_comp is not None and self.alignment is not None:
                ends = [
                    self._bound_prep(b).probs(chamber, stage, article, extra)
                    for b in ("low", "high")
                ]
                return np.minimum(*ends) if bound == "low" else np.maximum(*ends)
        return np.array(
            [self.resolver.resolve(m, stage, article, extra, bound) for m in self.members(chamber)],
            dtype=float,
        )

    def _bound_prep(self, bound: Bound) -> Prepared:
        cache = self.__dict__.setdefault("_bound_cache", {})
        if bound not in cache:
            cache[bound] = self.with_scenario(bound_scenario(self.scenario, bound))
        prep: Prepared = cache[bound]
        return prep

    def with_scenario(self, scenario: Scenario) -> Prepared:
        """The same inputs under another scenario (for example one with sampled priors).

        The defection prior, if any, is applied again from the original composition.
        """
        base = self.input_comp if self.input_comp is not None else self.comp
        comp, _ = apply_member_priors(scenario, base, self.rules, self.alignment)
        return Prepared(
            self.rules, comp, scenario, self.alignment, self.source, list(self.warnings), base
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


def apply_member_priors(
    scenario: Scenario, comp: Composition, rules: RuleSet, alignment: Alignment | None
) -> tuple[Composition, int]:
    """Apply the defection prior, then the score prior; return the composition and the number
    of members the score prior moved."""
    if alignment is None:
        return comp, 0
    if scenario.defection_prior is not None:
        comp = apply_defection_prior(scenario.defection_prior, scenario, comp, rules, alignment)
    if scenario.score_prior:
        return apply_score_prior(scenario, comp, rules, alignment)
    return comp, 0


def prepare_objects(
    rules: RuleSet,
    comp: Composition,
    scenario: Scenario,
    alignment: Alignment | None = None,
    source: str = "<memory>",
) -> Prepared:
    warnings = check_references(rules, comp, scenario)
    input_comp = comp
    if scenario.defection_prior is not None and alignment is None:
        raise ValueError("defection_prior needs an alignment")
    if scenario.score_prior and alignment is None:
        raise ValueError("score_prior needs an alignment")
    comp, scored = apply_member_priors(scenario, comp, rules, alignment)
    if scenario.score_prior and scored == 0:
        warnings.append(
            "score_prior moved no member: none has a score, a score_prior bloc and no "
            "congressional history in the alignment file"
        )
    prep = Prepared(rules, comp, scenario, alignment, source, warnings, input_comp)
    if scenario.attendance == "random":
        if not any(prep.absence_rates(ch).any() for ch in comp.bodies):
            prep.warnings.append(
                "attendance is random but every absence rate is 0: set absence_rate, give members "
                "p_absent, or use an alignment file with missed-vote counts"
            )
    return prep


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
