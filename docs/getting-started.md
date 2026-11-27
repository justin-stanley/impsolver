# Getting started

## Install

impsolver needs Python 3.12 or newer. The ILP solver (CBC) ships with PuLP, so nothing else is
required, and everything runs offline.

```bash
pip install "git+https://github.com/justin-stanley/impsolver@v0.1.0"
impsolver --help
```

impsolver is not on PyPI yet.

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

## Start from templates

`impsolver init` writes a commented starter file that validates as it is. Every template uses
placeholder officials and placeholder numbers; replace them with your own. The three templates
refer to each other by name, so write them into one folder:

```bash
mkdir my-case && cd my-case
impsolver init composition --out composition.yaml
impsolver init scenario --out scenario.yaml        # names composition.yaml
impsolver init portfolio --out portfolio.yaml      # names scenario.yaml
```

Without `--out`, `init` prints the template to standard output. It never overwrites an existing
file unless you pass `--force`. The composition template uses placeholder party counts, not a
real Congress: take current figures from the House Clerk and senate.gov, or build a roster with
`impsolver roster`.

## Validate a portfolio

```bash
impsolver validate us-federal composition.yaml scenario.yaml
impsolver validate --portfolio portfolio.yaml
```

`validate --portfolio` loads the portfolio and every scenario its candidates reference, without
simulating them. It fails (exit status 2) on schema errors, on an `after`, `excludes`,
`variant_of` or `succession` id that names no candidate, on a missing scenario file, on an
`article` the scenario does not list, and on any warning. Warnings print as
`warning: candidate ID: ...`, the same way `impsolver portfolio` prints them.

## Next steps

- [Rules and gates](methodology/gates.md) explains what each gate needs.
- [One hypothetical case](examples/single-case.md) walks through `evaluate`, `flips` and
  `simulate`.
- [Several cases at once](examples/portfolio.md) covers the scheduler and the planning page.
