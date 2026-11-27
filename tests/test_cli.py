# SPDX-FileCopyrightText: 2026 Justin Stanley
# SPDX-License-Identifier: MIT
import json
from pathlib import Path

import pytest

from impsolver.cli import main

REPO = Path(__file__).resolve().parents[1]
SCEN = str(REPO / "examples" / "scenario-example.yaml")
RULES = "us-federal"
COMP = str(REPO / "compositions" / "shorthand-119.yaml")


def run(capsys: pytest.CaptureFixture[str], *args: str) -> tuple[int, str, str]:
    rc = main(list(args))
    out = capsys.readouterr()
    return rc, out.out, out.err


def test_validate(capsys: pytest.CaptureFixture[str]) -> None:
    rc, out, _ = run(capsys, "validate", RULES, COMP, SCEN)
    assert rc == 0 and "scenario ok" in out


def test_evaluate_json(capsys: pytest.CaptureFixture[str]) -> None:
    rc, out, _ = run(capsys, "--format", "json", "evaluate", SCEN)
    assert rc == 0 and json.loads(out)["articles"][0]["binding_gate"] == "H2"


def test_flips(capsys: pytest.CaptureFixture[str]) -> None:
    rc, out, _ = run(capsys, "flips", SCEN, "--gate", "S2", "--constraint", "R<=25")
    assert rc == 0 and "(ilp)" in out and "20 flips" in out
    rc, out, _ = run(capsys, "flips", SCEN, "--greedy", "--gate", "S2")
    assert rc == 0 and "(greedy)" in out


def test_simulate(capsys: pytest.CaptureFixture[str]) -> None:
    rc, out, _ = run(capsys, "simulate", SCEN, "--draws", "2000", "--seed", "4")
    assert rc == 0 and "P(complete)" in out and "seed=4" in out


def test_compare(capsys: pytest.CaptureFixture[str]) -> None:
    rc, out, _ = run(capsys, "compare", SCEN, "--composition", COMP)
    assert rc == 0 and "shorthand-119" in out


def test_viability(capsys: pytest.CaptureFixture[str]) -> None:
    rc, out, _ = run(capsys, "viability", SCEN, "--draws", "1000")
    assert rc == 0 and "Example Official" in out


def test_backtest(capsys: pytest.CaptureFixture[str]) -> None:
    rc, out, _ = run(capsys, "backtest")
    assert rc == 0 and "all match" in out


def test_portfolio(capsys: pytest.CaptureFixture[str]) -> None:
    rc, out, _ = run(capsys, "portfolio", str(REPO / "examples" / "portfolio-example.yaml"))
    assert rc == 0 and "Plan 1" in out and "Sensitivity" in out


def test_calibrate(capsys: pytest.CaptureFixture[str]) -> None:
    al = REPO / "alignment" / "us-116.json"
    if not al.exists():
        pytest.skip("no alignment file")
    rc, out, _ = run(
        capsys,
        "calibrate",
        "--alignment",
        str(al),
        "--permutations",
        "200",
    )
    assert rc == 0 and "house:" in out and "senate:" in out


def test_schema(capsys: pytest.CaptureFixture[str], tmp_path: Path) -> None:
    rc, out, _ = run(capsys, "schema", "--out", str(tmp_path))
    assert rc == 0 and (tmp_path / "scenario.schema.json").exists()


def test_align(capsys: pytest.CaptureFixture[str], tmp_path: Path) -> None:
    m = tmp_path / "m.csv"
    v = tmp_path / "v.csv"
    m.write_text(
        "congress,chamber,icpsr,state_abbrev,district_code,party_code,bioname,bioguide_id\n"
        + "".join(
            f"119,Senate,{i},S{i},0,{200 if i < 6 else 100},N{i},X{i:05d}\n" for i in range(12)
        )
    )
    v.write_text(
        "congress,chamber,rollnumber,icpsr,cast_code,prob\n"
        + "".join(
            f"119,Senate,{r},{i},{1 if i < 6 else 6},99\n" for r in range(1, 21) for i in range(12)
        )
    )
    out = tmp_path / "a.json"
    rc, so, _ = run(capsys, "align", "--votes", str(v), "--members", str(m), "--out", str(out))
    assert rc == 0 and "senate: 12 members, 20 contested" in so and out.exists()


def test_errors_exit_2(capsys: pytest.CaptureFixture[str]) -> None:
    rc, _, err = run(capsys, "evaluate", "missing.yaml")
    assert rc == 2 and err.startswith("error:")


def test_validate_fails_on_warnings(capsys: pytest.CaptureFixture[str], tmp_path: Path) -> None:
    scen = tmp_path / "s.yaml"
    scen.write_text(
        Path(SCEN).read_text().replace("../compositions", str(REPO / "compositions"))
        + "overrides: {NOPE: {'*': 1.0}}\n"
    )
    rc, _, err = run(capsys, "validate", RULES, COMP, str(scen))
    assert rc == 2 and "warning: override for NOPE" in err


def test_portfolio_and_viability_print_scenario_warnings(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    scen = tmp_path / "s.yaml"
    scen.write_text(
        Path(SCEN).read_text().replace("../compositions", str(REPO / "compositions"))
        + "overrides: {NOPE: {'*': 1.0}}\n"
    )
    pf = tmp_path / "pf.yaml"
    pf.write_text(
        "schema_version: 1\nstart: 2027-01-04\ndeadline: 2028-12-15\ndraws: 200\n"
        "candidates:\n  - {id: a, scenario: s.yaml, house_days: 5, senate_days: 5}\n"
    )
    rc, _, err = run(capsys, "portfolio", str(pf))
    assert rc == 0 and "warning: candidate a: override for NOPE" in err
    rc, _, err = run(capsys, "viability", str(scen), "--draws", "500")
    assert rc == 0 and "warning: override for NOPE" in err
