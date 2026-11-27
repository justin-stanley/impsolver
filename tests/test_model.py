# SPDX-FileCopyrightText: 2026 Justin Stanley
# SPDX-License-Identifier: MIT
import pytest
from pydantic import ValidationError

from impsolver.model import Body, Scenario
from tests.conftest import make_comp


def test_seat_count_must_balance() -> None:
    with pytest.raises(ValidationError):
        Body.model_validate({"seats": 10, "vacancies": 1, "party_shorthand": {"R": 5, "D": 5}})


def test_duplicate_ids_rejected() -> None:
    m = {"id": "X1", "name": "a", "party": "R"}
    with pytest.raises(ValidationError):
        Body.model_validate({"seats": 2, "members": [m, m]})


def test_shorthand_expands() -> None:
    c = make_comp({"R": 3, "D": 2}, {"R": 1})
    assert [m.id for m in c.bodies["house"].roster] == ["R-001", "R-002", "R-003", "D-001", "D-002"]


def test_extra_keys_forbidden() -> None:
    with pytest.raises(ValidationError):
        Scenario.model_validate(
            {
                "schema_version": 1,
                "target": {"name": "x", "office": "y"},
                "rules": "r",
                "composition": "c",
                "bogus": 1,
            }
        )
