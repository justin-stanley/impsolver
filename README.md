# impsolver

[![CI](https://github.com/justin-stanley/impsolver/actions/workflows/ci.yml/badge.svg)](https://github.com/justin-stanley/impsolver/actions/workflows/ci.yml)
[![Docs](https://github.com/justin-stanley/impsolver/actions/workflows/docs.yml/badge.svg)](https://justin-stanley.github.io/impsolver/)
[![Python](https://img.shields.io/badge/python-3.12%20%7C%203.13-blue)](pyproject.toml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue)](LICENSE)
[![OpenSSF Scorecard](https://api.scorecard.dev/projects/github.com/justin-stanley/impsolver/badge)](https://scorecard.dev/viewer/?uri=github.com/justin-stanley/impsolver)
[![REUSE](https://img.shields.io/badge/REUSE-compliant-green)](https://reuse.software/)
<!-- DOI badge: added after the Zenodo integration mints the first DOI -->

**Counts the votes needed to impeach and remove a U.S. official, and estimates the odds of getting
them.**

You describe a case: the official, the chamber rosters, and each member's probability of voting
for it. impsolver reports:

- the votes each of the 5 House and Senate gates requires, given who is present;
- which gate decides the case, and how many members short it is;
- the fewest members whose votes would have to change;
- the probability of removal, from a Monte Carlo model of party swings;
- for several cases, the order and dates that maximize expected removals.

```text
$ impsolver backtest
OK       clinton-1998   S2 art I    45-55      expected FAIL  got FAIL  short 22
OK       trump-2021     S2 art I    57-43      expected FAIL  got FAIL  short 10
...
backtest: all match
```

The backtest replays 16 recorded roll calls from 5 cases, 1868 to 2024, and matches every
outcome and shortfall.

## Intended use

Use impsolver to analyze, teach and research the rules: what a two-thirds vote requires, how
attendance moves a threshold, how party cohesion becomes uncertainty, how cases compete for
floor time. It does not predict real outcomes and does not advise anyone to pursue or oppose a
case. Every probability is an input you supply. The examples use placeholder officials.
[RESPONSIBLE_USE.md](RESPONSIBLE_USE.md) states what the project will and will not host.

## Install

Requires Python 3.12 or later (CI tests 3.12 and 3.13). Runs offline; the CBC solver ships with
PuLP.

```bash
pip install "git+https://github.com/justin-stanley/impsolver@v0.1.0"
```

impsolver is not on PyPI yet.

## Quickstart

```bash
impsolver backtest                                    # replay 16 historical roll calls
impsolver evaluate examples/scenario-example.yaml     # what each gate needs
impsolver flips examples/scenario-example.yaml        # fewest votes that must change
impsolver simulate examples/scenario-example.yaml     # probability of removal
impsolver portfolio examples/portfolio-example.yaml --html plan.html
```

`plan.html` is one self-contained file: a timeline of House and Senate work, each case's odds at
each gate, succession branches, the removals distribution, and why any case was left out. See the
[example](examples/portfolio-example.html). Add `--format json` to any command for
machine-readable output.

## How it works

The built-in rule set, `us-federal`, has 5 gates:

| Gate | Chamber | Vote | PRO side needs |
| --- | --- | --- | --- |
| H1 | House | motion to table or refer | the motion to fail |
| H2 | House | adopt an article | a majority of votes cast |
| S1 | Senate | motion to dismiss or point of order | the motion to fail |
| S2 | Senate | convict | two-thirds of senators present |
| S3 | Senate | disqualify (only after conviction) | a majority of votes cast |

Every gate needs a quorum: a majority of sworn members. Path A starts at H1; path B starts at H2
after a committee report.

| Command | Output |
| --- | --- |
| `evaluate` | PASS, FAIL or CONTESTED per gate, from probability cutoffs, and the deciding gate |
| `flips` | The fewest stance changes that pass every gate (exact ILP; `--greedy` for speed) |
| `simulate` | P(removal) and pass rates per gate, from correlated party swings |
| `viability` | Your scenarios ranked by P(removal), flips needed and support gap |
| `portfolio` | Order and dates for several cases: House capacity, 1 Senate trial at a time, deadlines, fatigue, succession |
| `backtest`, `calibrate` | Checks against historical roll calls and the 2021 crossover votes |
| `roster`, `align` | Builds rosters and co-defection loadings from Voteview |
| `validate`, `compare`, `schema` | Checks files, compares rosters, writes JSON schemas |

The [docs](https://justin-stanley.github.io/impsolver/) cover the methodology, worked examples,
file formats and the API.

## Data

Rosters and alignment come from Voteview. Cite it when you use or rebuild these files:

> Lewis, Jeffrey B., Keith Poole, Howard Rosenthal, Adam Boche, Aaron Rudkin, and Luke Sonnet
> (2026). *Voteview: Congressional Roll-Call Votes Database.* https://voteview.com/
> Accessed 2026-11-27.

The `us-119` roster matches the House Press Gallery and senate.gov counts on 2026-11-27: House
217 R, 214 D, 1 I, 3 vacant; Senate 53 R, 45 D, 2 I. Rosters go stale; check current sources
first. [DATA.md](DATA.md) lists each derived file, its sources, the 2 corrections applied, and
the commands to rebuild it. Each historical fixture cites the House Clerk or Senate page it was
checked against.

## Limitations

- **Probabilities are inputs.** impsolver does not estimate how anyone will vote.
- **Validation is thin.** One event calibrates the model: 8 House members and 7 senators who
  crossed party lines in 2021. House β = 1.31 ± 0.43. The Senate shows no signal (p = 0.75), so
  Senate alignment is off by default.
- **Correlation choices move results.** One draw covers every gate in a chamber. House and
  Senate swings are independent unless `national_swing` is set. A portfolio's cases share one
  party swing.
- **Procedure is simplified.** The roster fixes attendance, nobody votes "present" in
  simulations, and you choose how a tied Senate majority vote resolves (`senate_tie_break`).
- **Scheduling is approximate.** Calendars are simple, Senate time is reserved even if the House
  vote fails, and portfolios above 10 eligible cases use a beam search.

## Contributing

```bash
git clone https://github.com/justin-stanley/impsolver && cd impsolver
uv sync --extra dev --extra docs && uv run pre-commit install
make test lint docs
```

Read [CONTRIBUTING.md](CONTRIBUTING.md) first. Report security or misuse issues privately
([SECURITY.md](SECURITY.md)). Cite the software with [CITATION.cff](CITATION.cff).

## License

Code: MIT ([LICENSE](LICENSE)). Data derived from Voteview carries Voteview's citation request
([DATA.md](DATA.md)).
