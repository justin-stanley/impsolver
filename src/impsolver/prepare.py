"""Load a scenario with its rules, composition and alignment, ready for evaluation."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import numpy.typing as npt

from .loader import load_alignment, load_composition, load_rules, load_scenario, resolve
from .members import Resolver
from .model import Alignment, Chamber, Composition, Member, RuleSet, Scenario
from .priors import apply_defection_prior


@dataclass
class Prepared:
    rules: RuleSet
    comp: Composition
    scenario: Scenario
    alignment: Alignment | None
    source: str = "<memory>"
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

    def with_composition(self, comp: Composition) -> Prepared:
        return Prepared(self.rules, comp, self.scenario, self.alignment, self.source)


def prepare_objects(
    rules: RuleSet,
    comp: Composition,
    scenario: Scenario,
    alignment: Alignment | None = None,
    source: str = "<memory>",
) -> Prepared:
    if scenario.defection_prior is not None:
        if alignment is None:
            raise ValueError("defection_prior needs an alignment")
        comp = apply_defection_prior(scenario.defection_prior, scenario, comp, rules, alignment)
    return Prepared(rules, comp, scenario, alignment, source)


def prepare(path: str | Path, composition: str | Path | None = None) -> Prepared:
    scen = load_scenario(path)
    rules = load_rules(resolve(scen.rules, path))
    comp = load_composition(composition if composition else resolve(scen.composition, path))
    align = load_alignment(resolve(scen.alignment, path)) if scen.alignment else None
    return prepare_objects(rules, comp, scen, align, str(path))
