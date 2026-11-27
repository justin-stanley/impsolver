# impsolver

Neutral vote-math solver for impeachment (House) and conviction (Senate). You supply the
candidates; the tool never nominates targets. See `docs/functional-spec.md` and
`docs/technical-design.md`.

```bash
uv venv -p python3.12 .venv && uv pip install -p .venv/bin/python -e '.[dev]'
.venv/bin/impsolver backtest
.venv/bin/impsolver evaluate examples/scenario-us119.yaml
.venv/bin/impsolver portfolio examples/portfolio-example.yaml
```

Regenerate the data-derived files (after downloading the Voteview CSVs into `data/voteview/`):

```bash
V=data/voteview
.venv/bin/impsolver roster --members $V/H119_members.csv --members $V/S119_members.csv \
  --votes $V/H119_votes.csv --votes $V/S119_votes.csv --caucus 328=D --out compositions/us-119.yaml
.venv/bin/impsolver align --votes $V/H116_votes.csv --votes $V/S116_votes.csv \
  --members $V/H116_members.csv --members $V/S116_members.csv --caucus 328=D --out alignment/us-116.json
.venv/bin/impsolver align --votes $V/H119_votes.csv --votes $V/S119_votes.csv \
  --members $V/H119_members.csv --members $V/S119_members.csv --caucus 328=D --out alignment/us-119.json
```

Checks: `PYTHONPATH=src .venv/bin/pytest -q`, `.venv/bin/ruff check src tests`, `.venv/bin/mypy src`.
