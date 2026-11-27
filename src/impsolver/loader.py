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


def resolve(ref: str, relative_to: str | Path) -> Path:
    p = Path(ref)
    return p if p.is_absolute() else (Path(relative_to).parent / p)


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
