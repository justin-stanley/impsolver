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
python -m venv .venv && . .venv/bin/activate
pip install -e '.[dev]'
```

Before opening a pull request:

```bash
pytest -q
ruff check src tests
ruff format --check src tests
mypy src
impsolver backtest
```

If you change a model in `src/impsolver/model.py`, regenerate the schemas with
`impsolver schema --out schemas`; a test fails when they drift. If you change behaviour, add a
line to `CHANGELOG.md` and, where the design changes, to `docs/technical-design.md`.

## Pull requests

Keep each pull request to one change, with a test that fails before it and passes after. Describe
what changed and why, and call out any change to numerical results.
