# impsolver: functional spec

impsolver is a neutral vote-math tool for U.S. federal impeachment (House) and removal (Senate).
The user supplies the targets, the chamber composition and per-member probabilities. The tool
works out what the rules require and how close each user-supplied case is. It never nominates
targets.

## What it answers
- **evaluate**: bounds per gate from cutoff classification (PASS, FAIL or CONTESTED), the binding
  gate, the coalition that controls it, and the members nearest the threshold there (by the
  supplied probabilities): the present non-PRO members at the binding gate, highest p first (ties
  by id), enough to cover the shortfall at the minimum plus 5, capped at 25. Each entry gives id,
  name, bloc, p (after shifts) and the source of the base probability (`override`, `member` or the
  member's `p_source`, or `party_prior`). It restates the inputs and suggests no one.
- **flips**: the fewest members whose stance would have to change for the gates to pass
  (exact ILP by default, `--greedy` for a fast heuristic). Bloc caps and exclusions are supported;
  unknown ids or blocs are rejected. Absences can optionally be
  modelled, and are reported as procedural sensitivity, not as a recommendation.
- **simulate**: Gaussian-copula Monte Carlo with bloc swings, with optional co-defection
  loadings learned from Voteview.
- **viability**: ranks the scenarios the user supplies by P(complete), flips needed and the
  uniform support gap.
- **portfolio**: orders and schedules a user-supplied set of candidates under House concurrency,
  one Senate trial at a time, calendars, deadlines, fatigue and succession effects. Includes
  sensitivity analysis and the joint distribution of removals. `--html OUT` writes a self-contained
  planning page: a timeline of House and Senate work for the top plans, each case's gate-by-gate
  odds, the members nearest each scenario case's binding-gate threshold, succession branches, the
  removals distribution, left-out candidates and sensitivity.
- **backtest**: replays the Johnson, Clinton, Trump (2019 and 2021) and Mayorkas roll calls, the
  Belknap trial (1876) and the Senate trials of Judges Swayne, Archbald, Ritter, Claiborne,
  Hastings, Nixon and Porteous.
- **calibrate**: checks the learned alignment against the 2021 Republican crossover votes.
- **roster** and **align**: build the composition and the alignment files from Voteview CSVs.

## Data
- Voteview member and vote CSVs go in `data/voteview/`. They are not committed; download them from
  `https://voteview.com/static/data/out/{votes,members}/{H,S}{116,119}_{votes,members}.csv`.
- `compositions/us-119.yaml` and `alignment/us-{116,119}.json` are generated from those files.
