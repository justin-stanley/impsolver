# SPDX-FileCopyrightText: 2026 Justin Stanley
# SPDX-License-Identifier: MIT
import pytest

from impsolver.model import RuleSet
from impsolver.paths import PathError, build_path, path_for
from tests.conftest import make_scenario


def test_path_a(rules: RuleSet) -> None:
    p = build_path(rules, "A")
    assert [s.id for s in p.stages] == ["H1", "H2", "S1", "S2"]
    assert [s.id for s in p.optional] == ["S3"]


def test_path_b_needs_committee_reports(rules: RuleSet) -> None:
    with pytest.raises(PathError):
        path_for(rules, make_scenario(), "B")
    p = path_for(rules, make_scenario(committee_reports=True), "B")
    assert [s.id for s in p.stages] == ["H2", "S1", "S2"]


def test_unknown_path(rules: RuleSet) -> None:
    with pytest.raises(KeyError):
        build_path(rules, "Z")
