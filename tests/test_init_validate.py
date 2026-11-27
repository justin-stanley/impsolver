# SPDX-FileCopyrightText: 2026 Justin Stanley
# SPDX-License-Identifier: MIT
"""`impsolver init` templates and `impsolver validate --portfolio` (issue #4)."""

from pathlib import Path

import pytest
from ruamel.yaml import YAML

from impsolver.cli import main
from impsolver.model import Composition, Portfolio, Scenario
from impsolver.templates import TEMPLATES

REPO = Path(__file__).resolve().parents[1]
PF_EXAMPLE = str(REPO / "examples" / "portfolio-example.yaml")


def run(capsys: pytest.CaptureFixture[str], *args: str) -> tuple[int, str, str]:
    rc = main(list(args))
    out = capsys.readouterr()
    return rc, out.out, out.err


def write_all(capsys: pytest.CaptureFixture[str], folder: Path) -> None:
    for kind in ("composition", "scenario", "portfolio"):
        rc, _, err = run(capsys, "init", kind, "--out", str(folder / f"{kind}.yaml"))
        assert rc == 0 and f"wrote {kind} template" in err


def test_templates_parse_and_use_placeholders() -> None:
    models = {"composition": Composition, "scenario": Scenario, "portfolio": Portfolio}
    for kind, text in TEMPLATES.items():
        assert text.startswith("#") and "PLACEHOLDER" in text
        models[kind].model_validate(YAML(typ="safe", pure=True).load(text))
    assert "Example Official" in TEMPLATES["scenario"]


def test_init_templates_validate(capsys: pytest.CaptureFixture[str], tmp_path: Path) -> None:
    write_all(capsys, tmp_path)
    comp, scen = str(tmp_path / "composition.yaml"), str(tmp_path / "scenario.yaml")
    rc, out, err = run(capsys, "validate", "us-federal", comp, scen)
    assert rc == 0 and "scenario ok" in out and "warning" not in err
    rc, out, err = run(capsys, "validate", "--portfolio", str(tmp_path / "portfolio.yaml"))
    assert rc == 0 and "portfolio ok: 2 candidates, 1 scenarios" in out and err == ""


def test_init_stdout(capsys: pytest.CaptureFixture[str]) -> None:
    rc, out, _ = run(capsys, "init", "portfolio")
    assert rc == 0 and out == TEMPLATES["portfolio"]


def test_init_refuses_to_overwrite(capsys: pytest.CaptureFixture[str], tmp_path: Path) -> None:
    out = tmp_path / "scenario.yaml"
    out.write_text("mine\n")
    rc, _, err = run(capsys, "init", "scenario", "--out", str(out))
    assert rc == 2 and "already exists" in err and out.read_text() == "mine\n"
    rc, _, _ = run(capsys, "init", "scenario", "--out", str(out), "--force")
    assert rc == 0 and out.read_text() == TEMPLATES["scenario"]


def test_init_unknown_kind(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit):
        main(["init", "rules"])
    capsys.readouterr()


def test_validate_portfolio_example(capsys: pytest.CaptureFixture[str]) -> None:
    rc, out, _ = run(capsys, "validate", "--portfolio", PF_EXAMPLE)
    assert rc == 0 and "portfolio ok: 7 candidates, 2 scenarios" in out
    rc, out, _ = run(capsys, "validate", "us-federal", "--portfolio", PF_EXAMPLE)
    assert rc == 0 and "rules ok" in out and "portfolio ok" in out


def test_validate_portfolio_after_typo(capsys: pytest.CaptureFixture[str], tmp_path: Path) -> None:
    write_all(capsys, tmp_path)
    pf = tmp_path / "portfolio.yaml"
    pf.write_text(pf.read_text().replace("after: [official-a]", "after: [oficial-a]"))
    rc, _, err = run(capsys, "validate", "--portfolio", str(pf))
    assert rc == 2 and "unknown candidate oficial-a" in err


def test_validate_portfolio_scenario_warning(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    write_all(capsys, tmp_path)
    scen = tmp_path / "scenario.yaml"
    scen.write_text(scen.read_text() + "overrides: {NOPE: {'*': 1.0}}\n")
    rc, _, err = run(capsys, "validate", "--portfolio", str(tmp_path / "portfolio.yaml"))
    assert rc == 2
    assert "warning: candidate official-a: override for NOPE" in err
    assert "1 warning(s)" in err


def test_validate_portfolio_scenario_errors(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    write_all(capsys, tmp_path)
    pf = tmp_path / "portfolio.yaml"
    base = pf.read_text()
    pf.write_text(base.replace("scenario: scenario.yaml", "scenario: missing.yaml"))
    rc, _, err = run(capsys, "validate", "--portfolio", str(pf))
    assert rc == 2 and "candidate official-a" in err and "missing.yaml" in err
    pf.write_text(base.replace("scenario: scenario.yaml", "scenario: scenario.yaml, article: II"))
    rc, _, err = run(capsys, "validate", "--portfolio", str(pf))
    assert rc == 2 and "article II is not in the scenario's articles (I)" in err
    scen = tmp_path / "scenario.yaml"
    scen.write_text(scen.read_text().replace("H1: 0.40", "H9: 0.40"))
    pf.write_text(base)
    rc, _, err = run(capsys, "validate", "--portfolio", str(pf))
    assert rc == 2 and "unknown stage key(s) H9" in err


def test_validate_portfolio_bad_rules(capsys: pytest.CaptureFixture[str], tmp_path: Path) -> None:
    write_all(capsys, tmp_path)
    scen = tmp_path / "scenario.yaml"
    scen.write_text(scen.read_text().replace("rules: us-federal", "rules: no-such-rules"))
    rc, _, err = run(capsys, "validate", "--portfolio", str(tmp_path / "portfolio.yaml"))
    assert rc == 2 and "unknown built-in rule set" in err


def test_validate_needs_something(capsys: pytest.CaptureFixture[str]) -> None:
    rc, _, err = run(capsys, "validate")
    assert rc == 2 and "--portfolio" in err
