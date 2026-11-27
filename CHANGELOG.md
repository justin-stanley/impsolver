# Changelog

All notable changes are listed here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added
- `evaluate` lists, per article, the members nearest the threshold at the binding gate (by the
  supplied probabilities), in its text and JSON output and on the `portfolio --html` page.

### Changed

### Fixed

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
