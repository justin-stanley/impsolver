# SPDX-FileCopyrightText: 2026 Justin Stanley
# SPDX-License-Identifier: MIT
"""The methodology paper draft is well formed and quotes only numbers the code produces."""

import contextlib
import io
import re
import shlex
from pathlib import Path

import pytest
from ruamel.yaml import YAML

from impsolver.cli import build_parser, main
from impsolver.thresholds import required_pro
from tests.test_thresholds import TWO_THIRDS

ROOT = Path(__file__).resolve().parents[1]
PAPER = ROOT / "paper" / "paper.md"
BIB = ROOT / "paper" / "paper.bib"
GENERATED = ROOT / "docs" / "examples" / "generated"

SECTIONS = [
    "Summary",
    "Statement of need",
    "Methods",
    "Validation",
    "Neutrality statement",
    "Acknowledgements",
    "References",
    "Appendix: commands behind the numbers",
]

# (text quoted in the paper, generated output that must contain it)
QUOTED = [
    ("E = 1.377", "portfolio", "E[removals]=1.377"),
    ("mean 1.364 and standard deviation 0.982", "portfolio", "mean 1.364, sd 0.982"),
    ("against 0.877", "portfolio", "independent sd 0.877"),
    ("probability, 0.020", "portfolio", "LOW_P (P=0.020 < p_floor 0.05)"),
    ("8 / 201", "calibrate", "8/201 crossers matched"),
    ("7 / 54", "calibrate", "7/54 crossers matched"),
    ("0.165 vs 0.069", "calibrate", "break rate 0.165 vs party 0.069"),
    ("0.058 vs 0.027", "calibrate", "break rate 0.058 vs party 0.027"),
    ("0.33 vs 0.20 (0.012)", "calibrate", "alignment 0.33 vs random 0.20 (p=0.012)"),
    ("0.20 vs 0.25 (0.744)", "calibrate", "alignment 0.20 vs random 0.25 (p=0.744)"),
    ("1.31 ± 0.43", "calibrate", "beta 1.31 ± 0.43"),
    ("0.89 ± 0.47", "calibrate", "beta 0.89 ± 0.47"),
    ("41 in\nthe House and 8 in the Senate", "score", "41 members left out as not voting"),
    ("160 House members (8 crossed)", "score", "160 members, 8 crossed"),
    ("46 senators (7 crossed)", "score", "46 members, 7 crossed"),
    ("0.1985 at $\\beta = 0$", "score", "beta  0.00  Brier 0.0475  log 0.1985"),
    ("0.1654 at the\ndefault", "score", "beta  1.00  Brier 0.0432  log 0.1654  <- default"),
    ("0.1642 at $\\beta = 1.25$", "score", "beta  1.25  Brier 0.0430  log 0.1642"),
    ("0.4265 at $\\beta = 0$", "score", "beta  0.00  Brier 0.1290  log 0.4265"),
    ("0.3846 at the default", "score", "beta  1.00  Brier 0.1157  log 0.3846  <- default"),
    ("scores\n0.1828", "score", "rho 0.6, weight 1, kappa 50: Brier 0.0465  log 0.1828"),
    ("(0.1691)", "score", "beta 1.25, rho 0, weight 0.5, kappa 50   Brier 0.0442  log 0.1691"),
    ("7 of the 4,000 draws are effective", "score", "smallest effective draws: 7 of 4000"),
    ("1 of 4,000 in the Senate", "score", "smallest effective draws: 1 of 4000"),
    ("fewer than 100 effective draws", "score", "best settings skip points below 100"),
]  # fmt: skip


def paper_text() -> str:
    return PAPER.read_text(encoding="utf-8")


def front_matter() -> dict[str, object]:
    text = paper_text()
    assert text.startswith("---\n"), "JOSS needs the YAML front matter first"
    block = text.split("---\n", 2)[1]
    data = YAML(typ="safe").load(block)
    assert isinstance(data, dict)
    return data


def body() -> str:
    return paper_text().split("---\n", 2)[2]


def run_cli(args: list[str]) -> str:
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        assert main(args) == 0
    return buf.getvalue()


def test_front_matter_has_joss_keys() -> None:
    fm = front_matter()
    for key in ("title", "tags", "authors", "affiliations", "date", "bibliography"):
        assert key in fm, key
    assert fm["bibliography"] == "paper.bib"
    authors = fm["authors"]
    assert isinstance(authors, list) and authors and all("name" in a for a in authors)


def test_has_every_required_section() -> None:
    headings = re.findall(r"^# (.+)$", body(), flags=re.M)
    assert headings == SECTIONS
    for sub in ("Gates", "Copula model", "Alignment and the defection prior", "Scheduler"):
        assert re.search(rf"^## {sub}", body(), flags=re.M), sub
    for sub in ("Backtest", "Calibration", "Limits"):
        assert re.search(rf"^## {sub}$", body(), flags=re.M), sub


def test_every_citation_is_in_the_bib() -> None:
    bib_keys = set(re.findall(r"^@\w+\{([^,]+),", BIB.read_text(encoding="utf-8"), flags=re.M))
    cited = set(re.findall(r"@([A-Za-z][\w-]*)", " ".join(re.findall(r"\[(@[^\]]+)\]", body()))))
    assert cited, "the paper cites nothing"
    assert cited <= bib_keys, cited - bib_keys
    assert "voteview" in cited


def test_bib_entries_have_a_title_and_a_source() -> None:
    entries = re.split(r"^@", BIB.read_text(encoding="utf-8"), flags=re.M)[1:]
    for entry in entries:
        key = entry.split("{", 1)[1].split(",", 1)[0]
        assert re.search(r"^\s*title\s*=", entry, flags=re.M), key
        assert re.search(r"^\s*(doi|howpublished|publisher)\s*=", entry, flags=re.M), key


# Tallies quoted in the Validation section: (fixture, stage, article, tally as printed)
TALLIES = [
    ("ritter-1936", "S2", "VII", "56-28"),
    ("claiborne-1986", "S2", "III", "46-17-35"),
    ("johnson-1868", "S2", "XI", "35-19"),
    ("archbald-1913", "S3", "judgment", "39-35"),
    ("porteous-2010", "S3", "judgment", "94-2"),
    ("ritter-1936", "S3", "judgment", "0-76"),
    ("mayorkas-2024", "H2", "I", "214-216"),
    ("mayorkas-2024", "H2", "I", "214-213"),
    ("mayorkas-2024", "S1", "I", "51-48-1"),
    ("mayorkas-2024", "S1", "II", "51-49"),
]


@pytest.mark.parametrize(("case", "stage", "article", "tally"), TALLIES)
def test_quoted_tallies_match_the_backtest(case: str, stage: str, article: str, tally: str) -> None:
    rows = (GENERATED / "backtest.md").read_text(encoding="utf-8").splitlines()
    assert any(
        ln.split()[:6] == ["OK", case, stage, "art", article, tally] for ln in rows if ln.strip()
    ), (case, stage, article, tally)
    paper = paper_text().replace("–", "-")
    assert re.search(rf"\b{re.escape(tally)}\b", paper), tally


def test_appendix_commands_parse() -> None:
    appendix = body().split("# Appendix", 1)[1]
    block = appendix.split("```bash", 1)[1].split("```", 1)[0]
    commands = [ln.split("#", 1)[0].strip() for ln in block.splitlines()]
    commands = [c for c in commands if c.startswith("uv run impsolver ")]
    assert len(commands) >= 4
    parser = build_parser()
    for cmd in commands:
        parser.parse_args(shlex.split(cmd)[3:])


def test_backtest_counts_match_the_code() -> None:
    out = run_cli(["backtest"])
    rows = [ln for ln in out.splitlines() if ln.startswith("OK ")]
    cases = {ln.split()[1] for ln in rows}
    assert out.rstrip().endswith("backtest: all match")
    text = paper_text()
    assert f"{len(rows)} recorded roll calls from {len(cases)}" in text
    assert f"replays {len(rows)} recorded roll calls from {len(cases)} cases" in text


def test_thresholds_quoted_in_methods() -> None:
    a, b, c = (required_pro(TWO_THIRDS, "pass", n) for n in (100, 99, 54))
    assert f"two-thirds of\n100 present is {a}, of 99 is {b} and of 54 is {c}" in paper_text()
    assert f"({a} of 100, {b} of 99, {c} of 54)" in paper_text()


@pytest.mark.parametrize(("in_paper", "example", "in_output"), QUOTED)
def test_quoted_numbers_come_from_the_generated_examples(
    in_paper: str, example: str, in_output: str
) -> None:
    assert in_paper in paper_text(), in_paper
    generated = (GENERATED / f"{example}.md").read_text(encoding="utf-8")
    assert in_output in generated, in_output


def test_appendix_names_the_generating_commands() -> None:
    appendix = body().split("# Appendix", 1)[1]
    for example in {e for _, e, _ in QUOTED}:
        first = (GENERATED / f"{example}.md").read_text(encoding="utf-8").splitlines()[1]
        assert first.startswith("$ impsolver ")
        assert "uv run " + first[2:] in appendix, first


FIXTURES = ROOT / "src" / "impsolver" / "data" / "fixtures"
# A probability written as P(...), P=..., a percentage, a decimal in [0, 1] or "probability of".
PROBABILITY = re.compile(
    r"\bP\s*[(=]"  # P(...) or P=...
    r"|\d+(?:\.\d+)?\s*(?:%|\\%|percent)"  # a percentage
    r"|(?<![\w.])[01]?\.\d+"  # a decimal such as 0.4 or .35
    r"|probabilit\w* of"
)


def real_surnames() -> set[str]:
    """Surnames of every real official in the backtest fixtures."""
    names = set()
    for path in FIXTURES.glob("*.yaml"):
        data = YAML(typ="safe").load(path.read_text(encoding="utf-8"))
        words = [w for w in str(data["target"]["name"]).split() if w not in {"Jr.", "Sr."}]
        names.add(words[-1])
    return names


def paragraphs_with_probabilities_for(text: str, names: set[str]) -> list[str]:
    return [
        para
        for para in text.split("\n\n")
        if any(re.search(rf"\b{re.escape(n)}\b", para) for n in names) and PROBABILITY.search(para)
    ]


def test_probability_check_catches_violations() -> None:
    names = {"Doe"}
    assert paragraphs_with_probabilities_for("Doe has P(removal) = 0.4.", names)
    assert paragraphs_with_probabilities_for("Doe is 40% likely to be removed.", names)
    assert paragraphs_with_probabilities_for("Doe: a probability of conviction.", names)
    assert paragraphs_with_probabilities_for("Doe at .35 to convict.", names)
    assert not paragraphs_with_probabilities_for("Doe was acquitted 35-19.", names)
    assert not paragraphs_with_probabilities_for("Roe at 0.4.\n\nDoe was acquitted.", names)


def test_no_invented_probabilities_for_real_people() -> None:
    text = paper_text()
    # The only probabilities in the paper belong to placeholder cases or calibration scores.
    assert "Official A" in text and "placeholder" in text
    names = real_surnames()
    assert {"Trump", "Mayorkas", "Clinton", "Johnson", "Belknap", "Porteous"} <= names
    assert paragraphs_with_probabilities_for(text, names) == []
