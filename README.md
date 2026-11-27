# impsolver

Vote math for U.S. federal impeachment and removal. Given a target that **you** supply, a chamber
roster and per-member probabilities, impsolver works out what the House and Senate rules require
at each step, how close the case is, which votes decide it, and, for several cases at once, which
order and timing give the most expected removals.

impsolver is **neutral**. It evaluates only the targets in its input files. It never suggests,
ranks or adds targets on its own, and its output is only as good as the probabilities you give it.

```text
$ impsolver backtest
OK       clinton-1998   S2 art I    45-55      expected FAIL  got FAIL  short 22
OK       trump-2021     S2 art I    57-43      expected FAIL  got FAIL  short 10
...
backtest: all match
```

## Intended use

impsolver is meant for analysis, teaching and research: what a two-thirds vote requires, how
attendance moves a threshold, how party cohesion turns into uncertainty, and how a long docket
competes for floor time. It is not a prediction of any real outcome, and it is not advice to
pursue or oppose any case. The example files use placeholder officials and placeholder
probabilities. Please keep any use of this tool honest about its assumptions (see
[Limitations](#limitations)).

## Install

Requires Python 3.12 or newer.

```bash
git clone <this repository>
cd impsolver
python -m venv .venv && . .venv/bin/activate
pip install -e '.[dev]'      # or: uv pip install -e '.[dev]'
impsolver --help
```

The ILP solver uses CBC, which ships with PuLP; nothing else needs to be installed. impsolver runs
fully offline once installed.

## Quickstart

```bash
impsolver backtest                                   # replay historical roll calls
impsolver evaluate examples/scenario-example.yaml    # bounds per gate
impsolver flips examples/scenario-example.yaml       # fewest stance changes needed (exact ILP)
impsolver simulate examples/scenario-example.yaml --draws 20000
impsolver portfolio examples/portfolio-example.yaml --html plan.html
```

`plan.html` is a self-contained planning page: a timeline of House and Senate work for the best
plans, each case's gate-by-gate odds, succession branches, the distribution of removals,
candidates left out and why, and sensitivity to fatigue and durations. A rendered copy is in
[`examples/portfolio-example.html`](examples/portfolio-example.html).

Add `--format json` to any command for machine-readable output.

## How it works

The rules ship with the package as `us-federal`
([`src/impsolver/data/rules/us-federal.yaml`](src/impsolver/data/rules/us-federal.yaml)); a scenario
can name a built-in rule set or point to its own YAML file:

| Gate | Chamber | Vote | Rule |
| --- | --- | --- | --- |
| H1 | House | motion to table or refer fails | majority of votes cast |
| H2 | House | article adopted | majority of votes cast |
| S1 | Senate | motion to dismiss or point of order fails | majority of votes cast |
| S2 | Senate | conviction | two-thirds of senators present |
| S3 | Senate | disqualification (optional, after conviction) | majority of votes cast |

Path A starts at H1. Path B starts at H2 and applies when a committee has reported. A quorum (a
majority of sworn members) is required at every gate.

| Command | What it does |
| --- | --- |
| `evaluate` | Classifies members as PRO, CON or uncertain by cutoffs and bounds each gate: PASS, FAIL or CONTESTED, with the binding gate. |
| `flips` | The fewest members whose stance would have to change, by exact ILP (`--greedy` for a heuristic). Supports bloc caps, exclusions and modelled absences. |
| `simulate` | Gaussian-copula Monte Carlo with bloc swings and, optionally, co-defection loadings learned from roll calls. |
| `viability` | Ranks the scenarios you supply by P(removal), flips needed and the uniform shift in support that would make each viable. |
| `portfolio` | Orders and schedules several cases with House concurrency, one Senate trial at a time, calendars, deadlines, fatigue and succession, then reports sensitivity and the joint distribution of removals. |
| `backtest` | Replays the Johnson, Clinton, Trump (2019 and 2021) and Mayorkas votes against the rules. |
| `calibrate` | Tests whether learned alignment picks out members who actually crossed party lines. |
| `roster`, `align` | Build a composition and alignment loadings from Voteview data. |
| `validate`, `compare`, `schema` | Check files, compare compositions, write JSON schemas. |

File formats are documented by the JSON schemas in [`schemas/`](schemas/) and the examples in
[`examples/`](examples/). Design details are in [`docs/technical-design.md`](docs/technical-design.md)
and [`docs/design-reference.md`](docs/design-reference.md).

## Data

Rosters and alignment are built from **Voteview**. Please cite it when you use these files or
regenerate them:

> Lewis, Jeffrey B., Keith Poole, Howard Rosenthal, Adam Boche, Aaron Rudkin, and Luke Sonnet
> (2026). *Voteview: Congressional Roll-Call Votes Database.* https://voteview.com/

This repository includes files derived from Voteview (`compositions/us-119.yaml`,
`alignment/us-116.json`, `alignment/us-119.json`). It does not include the raw CSVs. Download them
with `scripts/fetch-voteview.sh`, then rebuild:

```bash
scripts/fetch-voteview.sh 116 119
V=data/voteview
impsolver roster --members $V/H119_members.csv --members $V/S119_members.csv \
  --votes $V/H119_votes.csv --votes $V/S119_votes.csv --caucus 328=D \
  --member-caucus K000401=R --vacate H001082 --as-of 2026-11-27 --out compositions/us-119.yaml
impsolver align --votes $V/H116_votes.csv --votes $V/S116_votes.csv \
  --members $V/H116_members.csv --members $V/S116_members.csv --caucus 328=D \
  --out alignment/us-116.json
impsolver align --votes $V/H119_votes.csv --votes $V/S119_votes.csv \
  --members $V/H119_members.csv --members $V/S119_members.csv --caucus 328=D \
  --member-caucus K000401=R --out alignment/us-119.json
```

The `us-119` roster reflects the 119th Congress as of 2026-11-27, checked against the
[House Press Gallery party breakdown](https://pressgallery.house.gov/member-data/party-breakdown)
and [senate.gov](https://www.senate.gov/history/partydiv.htm). Two flags capture facts that
Voteview cannot show yet: Rep. Kiley (independent) caucuses with Republicans, and Rep. Hern's
resignation took effect on 2026-11-27. Rosters go stale; check current sources before relying on
one.

The historical fixtures in [`src/impsolver/data/fixtures/`](src/impsolver/data/fixtures/) cite the House Clerk and Senate roll-call
pages they were checked against.

## Limitations

- **Probabilities are inputs.** Party priors, overrides and shifts are your assumptions. The tool
  does not estimate how anyone will vote on a specific case.
- **Validation is thin.** The defection prior and alignment are checked against one event, the
  2021 crossover votes: 8 House members and 7 senators. House β = 1.31 ± 0.43. The Senate shows no
  signal (p = 0.75), so Senate alignment is off by default.
- **Correlation choices move results.** The same draw is reused across gates in a chamber, House
  and Senate swings are independent unless `national_swing` is set, and every scenario in a
  portfolio shares one party swing.
- **Procedure is simplified.** Attendance is fixed by the roster, nobody votes "present" in
  simulations, and how a tied Senate majority vote resolves is an input (`senate_tie_break`)
  because the rule for impeachment trials is not settled here.
- **Scheduling is approximate.** Working days come from simple calendars, Senate time is reserved
  even if the House vote fails, and plans with more than 10 eligible candidates use a beam search.

## Development

```bash
pip install -e '.[dev]'
pytest -q
ruff check src tests && ruff format --check src tests
mypy src
```

See [CONTRIBUTING.md](CONTRIBUTING.md) and [CHANGELOG.md](CHANGELOG.md).

## License

MIT. See [LICENSE](LICENSE).
