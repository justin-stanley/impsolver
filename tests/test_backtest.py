import subprocess
import sys
from pathlib import Path

from impsolver.backtest import DEFAULT_RULES, default_fixtures, run_backtest


def test_all_fixtures_match() -> None:
    rep = run_backtest()
    assert len(default_fixtures()) == 5
    assert rep.ok, [c for c in rep.checks if not c.ok]
    shorts = {(c.case, c.article, c.tally): c.short for c in rep.checks if c.stage == "S2"}
    assert shorts[("johnson-1868", "XI", "35-19")] == 1
    assert shorts[("clinton-1998", "I", "45-55")] == 22
    assert shorts[("clinton-1998", "III", "50-50")] == 17
    assert shorts[("trump-2021", "I", "57-43")] == 10
    assert any("mayorkas-2024 article I: path B ended at S1" in n for n in rep.path_checks)


def test_mismatch_exits_nonzero(tmp_path: Path) -> None:
    bad = tmp_path / "bad.yaml"
    bad.write_text("""schema_version: 1
case: bad
target: {name: X, office: judge}
date: 2000-01-01
bodies: {house: {seats: 435}, senate: {seats: 100}}
votes:
  - {stage: S2, yea: 60, nay: 40, expected: PASS}
""")
    rep = run_backtest([bad])
    assert not rep.ok
    r = subprocess.run(
        [sys.executable, "-m", "impsolver.cli", "backtest", str(bad)],
        capture_output=True,
        text=True,
    )
    assert r.returncode != 0


def test_fixture_tallies_account_for_every_sworn_member() -> None:
    from impsolver.loader import load_fixture, load_rules

    rules = load_rules(DEFAULT_RULES)
    for f in default_fixtures():
        fx = load_fixture(f)
        assert fx.sources, f"{f.name} has no sources"
        for v in fx.votes:
            body = fx.bodies[rules.stage(v.stage).chamber]
            assert v.yea + v.nay + v.present + v.not_voting == body.seats - body.vacancies, (
                f"{f.name} {v.stage} {v.yea}-{v.nay}"
            )
