# Contributing

Thanks for helping. Bug reports, fixes, documentation and new tests are all welcome.

## Ground rules

- **Stay neutral.** impsolver evaluates only the targets a user supplies. Contributions must not
  add target lists, rank real people as targets, or ship real-person scenarios with made-up
  probabilities. Examples use placeholder officials. Historical fixtures record public roll calls
  and must cite their sources.
- **Cite facts.** Any roster change, vacancy or caucus fact needs a current primary source (House
  Clerk, House Press Gallery, senate.gov, Voteview) in the pull request.
- **Keep it offline.** The CLI must run without network access; data downloads live in
  `scripts/`.

## Development setup

```bash
uv sync --extra dev --extra docs     # or: pip install -e '.[dev,docs]'
uv run pre-commit install
```

Before opening a pull request:

```bash
make test    # pytest with coverage; the floor is 90%
make lint    # ruff, ruff-format, mypy --strict, REUSE and file checks
make docs    # only if you touched docs/ or anything shown in the worked examples
uv run impsolver backtest
```

If you change a model in `src/impsolver/model.py`, regenerate the schemas with
`uv run impsolver schema --out schemas`; a test fails when they drift. If you change anything that
the worked examples print, regenerate them with `uv run python docs/examples/run_examples.py`; the
docs build fails when they are stale. New files need an SPDX header, or an entry in `REUSE.toml`
for data files.

Record behaviour changes in `CHANGELOG.md`. Where the design changes, also update
`docs/technical-design.md`, and label the pull request `numerical-change` if default results move.

## Releasing (maintainers)

1. Update `version` in `pyproject.toml` and move the CHANGELOG entries under a new version
   heading.
2. Commit, then push a signed tag: `git tag -s vX.Y.Z -m vX.Y.Z && git push origin vX.Y.Z`.
3. The release workflow tests, builds, attests and publishes to PyPI with trusted publishing, then
   creates the GitHub release from the CHANGELOG. Zenodo archives the release and mints a DOI.

## Pull requests

Keep each pull request to one change, with a test that fails before it and passes after. Describe
what changed and why, and call out any change to numerical results.
