"""YAML/JSON loading with ruamel's safe loader, resolving paths relative to the referring file."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError
from ruamel.yaml import YAML

from .model import Alignment, Composition, CrossoverFixture, Fixture, Portfolio, RuleSet, Scenario

M = TypeVar("M", bound=BaseModel)


class LoadError(Exception):
    pass


def read_data(path: str | Path) -> Any:
    p = Path(path)
    try:
        text = p.read_text(encoding="utf-8")
    except OSError as e:
        raise LoadError(f"{p}: {e.strerror or e}") from e
    if p.suffix == ".json":
        try:
            return json.loads(text)
        except json.JSONDecodeError as e:
            raise LoadError(f"{p}: invalid JSON: {e}") from e
    try:
        return YAML(typ="safe", pure=True).load(text)
    except Exception as e:  # ruamel raises many types
        raise LoadError(f"{p}: invalid YAML: {e}") from e


def load_model[M: BaseModel](cls: type[M], path: str | Path) -> M:
    data = read_data(path)
    try:
        return cls.model_validate(data)
    except ValidationError as e:
        raise LoadError(f"{path}: {e}") from e


DATA = Path(__file__).resolve().parent / "data"
BUILTIN_RULES = DATA / "rules"
BUILTIN_FIXTURES = DATA / "fixtures"


def resolve(ref: str, relative_to: str | Path) -> Path:
    p = Path(ref)
    return p if p.is_absolute() else (Path(relative_to).parent / p)


def builtin_rules(name: str) -> Path:
    path = BUILTIN_RULES / f"{name}.yaml"
    if not path.exists():
        known = sorted(q.stem for q in BUILTIN_RULES.glob("*.yaml"))
        raise LoadError(f"unknown built-in rule set {name!r}; known: {', '.join(known)}")
    return path


def resolve_rules(ref: str, relative_to: str | Path) -> Path:
    """A rule-set reference is a built-in name (``us-federal``) or a path to a YAML file."""
    if "/" not in ref and "\\" not in ref and Path(ref).suffix == "":
        return builtin_rules(ref)
    return resolve(ref, relative_to)


def load_rules(path: str | Path) -> RuleSet:
    return load_model(RuleSet, path)


def load_composition(path: str | Path) -> Composition:
    return load_model(Composition, path)


def load_scenario(path: str | Path) -> Scenario:
    return load_model(Scenario, path)


def load_alignment(path: str | Path) -> Alignment:
    data = read_data(path)
    if isinstance(data, dict) and "encoding" not in data:
        raise LoadError(
            f"{path}: alignment file has no 'encoding' field; it predates the unsigned-break "
            "fix and must be regenerated"
        )
    try:
        return Alignment.model_validate(data)
    except ValidationError as e:
        raise LoadError(f"{path}: {e}") from e


def load_fixture(path: str | Path) -> Fixture:
    return load_model(Fixture, path)


def load_crossovers(path: str | Path) -> CrossoverFixture:
    return load_model(CrossoverFixture, path)


def load_portfolio(path: str | Path) -> Portfolio:
    return load_model(Portfolio, path)
