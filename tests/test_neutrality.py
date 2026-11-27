# SPDX-FileCopyrightText: 2026 Justin Stanley
# SPDX-License-Identifier: MIT
"""The tool evaluates only targets it is given; it never nominates targets."""

import json
import subprocess
import sys
from pathlib import Path

import impsolver
from impsolver.model import RuleSet
from impsolver.viability import Case, assess
from tests.conftest import make_comp, make_prep

PKG = Path(impsolver.__file__).parent


def test_outputs_only_contain_supplied_targets(rules: RuleSet) -> None:
    comp = make_comp({"D": 220, "R": 215}, {"D": 50, "R": 50})
    cases = [
        Case(f"s{i}", make_prep(rules, comp, target={"name": f"Target {i}", "office": "judge"}))
        for i in range(3)
    ]
    rows = assess(cases, draws=1000)
    assert {r.target for r in rows} == {"Target 0", "Target 1", "Target 2"}


def test_no_embedded_target_lists() -> None:
    src = " ".join(p.read_text() for p in PKG.glob("*.py")).lower()
    for word in ("recommended_target", "suggest_target", "nominate("):
        assert word not in src


def test_cli_help_describes_the_tool() -> None:
    r = subprocess.run(
        [sys.executable, "-m", "impsolver.cli", "--help"], capture_output=True, text=True
    )
    assert "Counts the votes needed" in r.stdout


def test_portfolio_ids_come_from_input(tmp_path: Path) -> None:
    pf = tmp_path / "p.yaml"
    pf.write_text("""schema_version: 1
start: 2027-01-04
deadline: 2028-12-15
draws: 200
candidates:
  - {id: one, p: 0.5, house_days: 5, senate_days: 5}
  - {id: two, p: 0.4, house_days: 5, senate_days: 5}
""")
    r = subprocess.run(
        [sys.executable, "-m", "impsolver.cli", "--format", "json", "portfolio", str(pf)],
        capture_output=True,
        text=True,
        check=True,
    )
    data = json.loads(r.stdout)
    ids = {s["id"] for p in data["plans"] for s in p["slots"]} | {d["id"] for d in data["dropped"]}
    assert ids <= {"one", "two"}
