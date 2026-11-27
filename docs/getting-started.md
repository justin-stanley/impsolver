# Getting started

## Install

impsolver needs Python 3.12 or newer. The ILP solver (CBC) ships with PuLP, so nothing else is
required, and everything runs offline.

```bash
pip install impsolver
impsolver --help
```

To work on the code instead:

```bash
git clone https://github.com/justin-stanley/impsolver
cd impsolver
uv sync --extra dev        # or: pip install -e '.[dev]'
```

## Your first run

The repository's `examples/` folder holds placeholder scenarios. Start with the backtest, which
replays real roll calls against the built-in rules:

--8<-- "examples/generated/backtest.md"

## The three input files

1. **Rules** describe the gates. Use the built-in set with `rules: us-federal`, or point to your
   own YAML file.
2. **A composition** lists who holds each seat. Write one by hand, use party shorthand
   (`party_shorthand: {R: 219, D: 214}`), or build one from Voteview with `impsolver roster`.
3. **A scenario** names the target and gives probabilities: party priors per bloc and stage,
   per-member overrides, and optional shifts.

```yaml
schema_version: 1
target: {name: Example Official, office: cabinet_secretary}
rules: us-federal
composition: ../compositions/shorthand-119.yaml
party_priors:
  D: {"*": 0.95}
  I: {"*": 0.9}
  R: {"*": 0.08, H1: 0.15}
```

Check files with `impsolver validate us-federal COMPOSITION SCENARIO`. It fails on unknown stage
keys and warns about member ids or blocs that the composition does not contain.

## Next steps

- [Rules and gates](methodology/gates.md) explains what each gate needs.
- [One hypothetical case](examples/single-case.md) walks through `evaluate`, `flips` and
  `simulate`.
- [Several cases at once](examples/portfolio.md) covers the scheduler and the planning page.
