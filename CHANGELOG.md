# Changelog

All notable changes are listed here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added
- Backtest fixtures for Belknap (1876) and the Senate trials of Judges Swayne, Archbald, Ritter,
  Claiborne, Hastings, Nixon and Porteous, with their disqualification votes.
- Optional random attendance in the Monte Carlo (`attendance: random`, `absence_rate`, member
  `p_absent`, and `n_missed`/`n_possible` in alignment files); the default `fixed` leaves results unchanged.
- Scenario option `gate_correlation` (0 to 1, default 1) sets how much each member's Monte Carlo
  draw carries from one gate to the next in a chamber; marginals are preserved and default
  results do not change.
- `evaluate` lists, per article, the members nearest the threshold at the binding gate (by the
  supplied probabilities), in its text and JSON output and on the `portfolio --html` page.
- `impsolver validate --portfolio FILE` checks a portfolio and every scenario it references, and
  `impsolver init scenario|portfolio|composition` writes commented templates that validate (#4).
- `impsolver score` scores per-member crossing predictions on the crossover fixtures (Brier and log
  loss) over a grid of β, ρ, alignment weight and κ, with leave-one-event-out scores when there is
  more than one event; it reports only, and no default changes.
- Crossover fixtures take an optional `not_voting` list, and `impsolver score` leaves those members
  out instead of scoring them as non-crossers (2021: 41 House and 8 Senate Republicans of the 116th).
- `impsolver align` pools several congresses, optionally with a recency weight (`--half-life`, in
  congresses; recorded as `half_life`), and `alignment/us-116-118.json` pools the 116th to 118th
  Congresses (Voteview checksums added); `us-116.json`, `us-119.json` and default results are unchanged.
- `party_priors` and `overrides` values may be a range `{low, high}` or `{beta: [a, b]}`;
  `uncertainty_draws` (or `simulate --uncertainty-draws`) reports P(removal) with a 5-95% interval
  over them, and `evaluate` widens its bounds to the range; number-valued results are unchanged.
- Portfolio `roster_changes` (dated vacancies and new seats): P0 is computed per roster epoch and
  each trial uses the roster in force on its first day; without changes results do not change.
- The `portfolio --html` page has a tornado chart per scenario case (P with each bloc prior ±0.05,
  rho ±0.2 and fatigue ±0.2, common random numbers; also `tornado` in the JSON), and
  `impsolver compare-plans A.yaml B.yaml [--html OUT]` shows two portfolios or two scenarios side
  by side; default results do not change.

### Changed
- `portfolio` with succession rules: after each trigger's verdict, every branch re-orders the cases
  not yet started (all orders when at most 6 remain); a case already started stays in the plan
  with its House start. The decision tree shows each branch's order. Expected removals with succession can rise and the recommended
  order can change; portfolios without succession rules are unchanged.
- `backtest` scores completion per case (a conviction on any article completes it) instead of per
  article, adds a case-level line to `path_checks`, and fails a fixture with no required-stage vote.
- The ILP runs on PuLP 4 (`pulp[cbc]>=2.9,<5`; CBC now comes from the `cbcbox` wheel). Flip and
  absence counts are unchanged; among near-tied solutions, the members or gates listed can differ
  by CBC build (#9).
- `portfolio`: a candidate without `article` now counts removal on any article, P0 = P(at least one
  article completes) from one simulation with shared draws across articles, also in the joint
  removals distribution; default numbers change only for scenarios with more than one article.

### Fixed

- Review fixes for PR #13: the planning page's pivot list uses the same article as its gate-path
  row; `gate_correlation` keeps the bloc swing fixed across gates so national and portfolio-shared
  swings stay shared; a multi-article candidate is simulated once per article; `attendance: random`
  with no absence rates warns; `evaluate` and `flips` note that they use fixed attendance; CBC runs
  with a zero gap on every PuLP version.
- Review fixes for PR #14: `compare-plans` and the tornado charts use the P0 of the roster in
  force at each trial; `evaluate` widens its bounds for range and Beta priors when a defection
  prior is set; warnings from later rosters are reported; `compare-plans` scenario rows use point
  priors throughout; `score` lists alignment weights per chamber. `roster_changes` now accepts
  Senate changes only, because a case's roster is chosen by its trial start, after its House vote
  (#15).

## [0.1.0] - 2026-11-27

First public release.

### Added
- Gate math for U.S. federal impeachment and removal (H1, H2, S1, S2, S3), paths A and B, quorum.
- `evaluate`, `flips` (exact ILP by default, greedy optional), `simulate` (Gaussian copula with
  optional co-defection loadings), `viability`, `compare`, `backtest`, `calibrate`, `validate`,
  `schema`.
- `portfolio` scheduling with House concurrency, one Senate trial at a time, calendars,
  deadlines, fatigue, causal succession branches, sensitivity and the joint removals
  distribution; `--html` writes a self-contained planning page.
- `roster` and `align` importers for Voteview data, with per-member caucus mappings and
  `--vacate` for resignations Voteview does not show yet.
- Historical fixtures for Johnson (1868), Clinton (1998), Trump (2019 and 2021) and Mayorkas
  (2024), each checked against House Clerk and Senate records.
- `DATA.md` and `CITATION.cff`; generated rosters and alignment files carry the Voteview
  citation and access date (`--accessed`).
- Docs site with methodology, worked examples (generated and checked in CI), CLI and API
  reference, and a demo planning page.
- Community and project files: RESPONSIBLE_USE, CODE_OF_CONDUCT, SECURITY, GOVERNANCE,
  issue forms, PR template, CODEOWNERS; REUSE-compliant licensing.
- CI on Linux, macOS and Windows; CodeQL; OpenSSF Scorecard; Dependabot; release workflow with
  PyPI trusted publishing and build attestations; `uv.lock`; checksummed data and
  `make reproduce`.
- Scenario options `senate_tie_break`, `national_swing` and `alignment_chamber_weight` (the
  Senate defaults to 0).
