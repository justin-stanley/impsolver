# SPDX-FileCopyrightText: 2026 Justin Stanley
# SPDX-License-Identifier: MIT
import subprocess
import sys
from pathlib import Path

from impsolver.backtest import DEFAULT_RULES, default_fixtures, run_backtest


def test_all_fixtures_match() -> None:
    rep = run_backtest()
    assert len(default_fixtures()) == 13
    assert rep.ok, [c for c in rep.checks if not c.ok]
    shorts = {(c.case, c.article, c.tally): c.short for c in rep.checks if c.stage == "S2"}
    assert shorts[("johnson-1868", "XI", "35-19")] == 1
    assert shorts[("clinton-1998", "I", "45-55")] == 22
    assert shorts[("clinton-1998", "III", "50-50")] == 17
    assert shorts[("trump-2021", "I", "57-43")] == 10
    assert any("mayorkas-2024 article I: path B ended at S1" in n for n in rep.path_checks)


def test_judicial_and_earlier_trials() -> None:
    rep = run_backtest()
    got = {(c.case, c.stage, c.article): (c.got, c.short) for c in rep.checks}
    # Belknap: every article five votes short, as the managers reported (Hinds sec. 2468).
    assert {got[("belknap-1876", "S2", a)] for a in ["I", "II", "III", "IV", "V"]} == {("FAIL", 5)}
    assert got[("swayne-1905", "S2", "XII")] == ("FAIL", 20)
    # Exactly two-thirds convicts: Ritter VII 56 of 84; Archbald XIII 42 of 62 is just over.
    assert got[("ritter-1936", "S2", "VII")] == ("PASS", 0)
    assert got[("ritter-1936", "S2", "I")] == ("FAIL", 1)
    assert got[("archbald-1913", "S2", "XIII")] == ("PASS", 0)
    assert got[("archbald-1913", "S2", "II")] == ("FAIL", 2)
    # Claiborne III: 35 "present" count toward the two-thirds, so 46-17 falls 20 short of 66.
    assert got[("claiborne-1986", "S2", "III")] == ("FAIL", 20)
    assert got[("hastings-1989", "S2", "VI")] == ("FAIL", 16)
    assert got[("nixon-1989", "S2", "III")] == ("FAIL", 8)
    # Disqualification votes (S3): Archbald and Porteous carried, Ritter failed 0-76.
    assert got[("archbald-1913", "S3", "judgment")][0] == "PASS"
    assert got[("porteous-2010", "S3", "judgment")][0] == "PASS"
    assert got[("ritter-1936", "S3", "VII")][0] == "FAIL"
    for case in ["porteous-2010", "nixon-1989", "hastings-1989", "claiborne-1986", "ritter-1936"]:
        assert f"{case}: completed" in rep.path_checks
    assert "archbald-1913: completed" in rep.path_checks
    assert "swayne-1905: ended at S2" in rep.path_checks
    assert "nixon-1989 article III: path B ended at S2" in rep.path_checks
    assert not any("judgment" in n for n in rep.path_checks)


FIXTURE_HEAD = """schema_version: 1
case: mixed
target: {name: X, office: judge}
date: 2000-01-01
path: B
bodies: {senate: {seats: 100}}
"""


def _write(tmp_path: Path, body: str) -> Path:
    f = tmp_path / "fx.yaml"
    f.write_text(FIXTURE_HEAD + body)
    return f


def test_conviction_on_one_article_completes_the_case(tmp_path: Path) -> None:
    votes = """votes:
  - {stage: S2, article: I, yea: 70, nay: 30, expected: PASS}
  - {stage: S2, article: II, yea: 50, nay: 50, expected: FAIL}
  - {stage: S3, article: judgment, yea: 60, nay: 40, expected: PASS}
"""
    rep = run_backtest([_write(tmp_path, votes + "expected_complete: true\n")])
    assert rep.ok
    assert rep.path_checks == [
        "mixed article I: path B completed",
        "mixed article II: path B ended at S2",
        "mixed: completed",
    ]
    rep = run_backtest([_write(tmp_path, votes + "expected_ends_at: S2\n")])
    assert not rep.ok
    assert rep.path_checks[-1] == "mixed: completed (expected complete=False, ends_at=S2)"


def test_case_ends_at_the_furthest_stage_reached(tmp_path: Path) -> None:
    votes = """votes:
  - {stage: S1, article: I, yea: 60, nay: 40, expected: FAIL}
  - {stage: S2, article: II, yea: 50, nay: 50, expected: FAIL}
"""
    rep = run_backtest([_write(tmp_path, votes + "expected_ends_at: S2\n")])
    assert rep.ok
    assert rep.path_checks[-1] == "mixed: ended at S2"
    rep = run_backtest([_write(tmp_path, votes + "expected_ends_at: S1\n")])
    assert not rep.ok


def test_article_without_a_conviction_vote_does_not_complete(tmp_path: Path) -> None:
    votes = """votes:
  - {stage: S1, article: I, yea: 40, nay: 60, expected: PASS}
expected_ends_at: S2
"""
    rep = run_backtest([_write(tmp_path, votes)])
    assert rep.ok
    assert rep.path_checks == ["mixed article I: path B ended at S2", "mixed: ended at S2"]


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
