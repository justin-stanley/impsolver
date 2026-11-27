from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from impsolver.loader import load_rules
from impsolver.model import Alignment, Composition, RuleSet, Scenario
from impsolver.prepare import Prepared, prepare_objects

REPO = Path(__file__).resolve().parents[1]
RULES_PATH = REPO / "src" / "impsolver" / "data" / "rules" / "us-federal.yaml"


@pytest.fixture(scope="session")
def rules() -> RuleSet:
    return load_rules(RULES_PATH)


def make_comp(
    house: dict[str, int] | list[dict[str, Any]],
    senate: dict[str, int] | list[dict[str, Any]],
    house_seats: int | None = None,
    senate_seats: int | None = None,
    house_vac: int = 0,
    senate_vac: int = 0,
) -> Composition:
    def body(spec: Any, seats: int | None, vac: int) -> dict[str, Any]:
        if isinstance(spec, dict):
            n = sum(spec.values())
            return {"seats": seats or n + vac, "vacancies": vac, "party_shorthand": spec}
        return {"seats": seats or len(spec) + vac, "vacancies": vac, "members": spec}

    return Composition.model_validate(
        {
            "schema_version": 1,
            "name": "test",
            "as_of": "2027-01-01",
            "bodies": {
                "house": body(house, house_seats, house_vac),
                "senate": body(senate, senate_seats, senate_vac),
            },
        }
    )


def make_scenario(**kw: Any) -> Scenario:
    data: dict[str, Any] = {
        "schema_version": 1,
        "target": {"name": "Test Target", "office": "judge"},
        "rules": str(RULES_PATH),
        "composition": "unused.yaml",
        "party_priors": {"D": {"*": 0.95}, "R": {"*": 0.05}},
    }
    data.update(kw)
    return Scenario.model_validate(data)


def make_prep(
    rules: RuleSet, comp: Composition, align: Alignment | None = None, **kw: Any
) -> Prepared:
    return prepare_objects(rules, comp, make_scenario(**kw), align)
