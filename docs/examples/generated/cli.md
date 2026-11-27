```text
usage: impsolver [-h] [--format {text,json}]
                 {validate,init,evaluate,flips,simulate,compare,viability,backtest,portfolio,calibrate,schema,roster,align}
                 ...

Counts the votes needed to impeach and remove a U.S. official, and estimates the odds of getting
them.

positional arguments:
  {validate,init,evaluate,flips,simulate,compare,viability,backtest,portfolio,calibrate,schema,roster,align}
    validate            validate rules, composition, scenario and portfolio files
    init                write a commented starter file (placeholder officials only)
    evaluate            deterministic bounds per gate
    flips               minimal changes for the gates to pass
    simulate            copula Monte Carlo
    compare             evaluate one scenario against several compositions
    viability           rank the scenarios you supply
    backtest            replay historical roll calls
    portfolio           schedule a portfolio of candidates
    calibrate           check alignment against known crossovers
    schema              write JSON schemas
    roster              build a composition from Voteview (see roster --help)
    align               fit alignment loadings from Voteview (see align --help)

options:
  -h, --help            show this help message and exit
  --format {text,json}
```

### `impsolver validate`

```text
usage: impsolver validate [-h] [--format {text,json}] [--portfolio FILE]
                          [rules] [composition] [scenario]

Check input files without running them. Exits 2 on any error or warning.

positional arguments:
  rules                 built-in rule set name (us-federal) or a YAML path
  composition
  scenario

options:
  -h, --help            show this help message and exit
  --format {text,json}
  --portfolio FILE      also check a portfolio and every scenario its candidates reference
```

### `impsolver init`

```text
usage: impsolver init [-h] [--format {text,json}] [--out FILE] [--force]
                      {composition,portfolio,scenario}

Write a commented template that validates. composition.yaml, scenario.yaml and portfolio.yaml in
one folder refer to each other.

positional arguments:
  {composition,portfolio,scenario}

options:
  -h, --help            show this help message and exit
  --format {text,json}
  --out FILE            write here instead of standard output
  --force               overwrite an existing --out file
```

### `impsolver evaluate`

```text
usage: impsolver evaluate [-h] [--format {text,json}] [--path PATH] scenario

positional arguments:
  scenario

options:
  -h, --help            show this help message and exit
  --format {text,json}
  --path PATH
```

### `impsolver flips`

```text
usage: impsolver flips [-h] [--format {text,json}] [--gate GATE] [--path PATH] [--article ARTICLE]
                       [--ilp] [--greedy] [--constraint BLOC<=N] [--exclude ID] [--allow-absence]
                       [--absence-cost ABSENCE_COST] [--per-gate-stance]
                       scenario

positional arguments:
  scenario

options:
  -h, --help            show this help message and exit
  --format {text,json}
  --gate GATE
  --path PATH
  --article ARTICLE
  --ilp                 exact ILP (the default; kept for scripts)
  --greedy              fast greedy heuristic instead of the ILP
  --constraint BLOC<=N
  --exclude ID
  --allow-absence
  --absence-cost ABSENCE_COST
  --per-gate-stance
```

### `impsolver simulate`

```text
usage: impsolver simulate [-h] [--format {text,json}] [--draws DRAWS] [--rho RHO] [--seed SEED]
                          [--path PATH]
                          scenario

positional arguments:
  scenario

options:
  -h, --help            show this help message and exit
  --format {text,json}
  --draws DRAWS
  --rho RHO
  --seed SEED
  --path PATH
```

### `impsolver compare`

```text
usage: impsolver compare [-h] [--format {text,json}] --composition COMPOSITION scenario

positional arguments:
  scenario

options:
  -h, --help            show this help message and exit
  --format {text,json}
  --composition COMPOSITION
```

### `impsolver viability`

```text
usage: impsolver viability [-h] [--format {text,json}] [--target-p TARGET_P] [--max-gap MAX_GAP]
                           [--draws DRAWS]
                           scenarios [scenarios ...]

positional arguments:
  scenarios

options:
  -h, --help            show this help message and exit
  --format {text,json}
  --target-p TARGET_P
  --max-gap MAX_GAP
  --draws DRAWS
```

### `impsolver backtest`

```text
usage: impsolver backtest [-h] [--format {text,json}] [fixtures ...]

positional arguments:
  fixtures

options:
  -h, --help            show this help message and exit
  --format {text,json}
```

### `impsolver portfolio`

```text
usage: impsolver portfolio [-h] [--format {text,json}] [--exhaustive] [--html OUT] file

positional arguments:
  file

options:
  -h, --help            show this help message and exit
  --format {text,json}
  --exhaustive
  --html OUT            also write a self-contained HTML planning page
```

### `impsolver calibrate`

```text
usage: impsolver calibrate [-h] [--format {text,json}] --alignment ALIGNMENT
                           [--min-votes MIN_VOTES] [--permutations PERMUTATIONS] [--seed SEED]
                           [fixture]

positional arguments:
  fixture               crossover fixture (default: the built-in 2021 crossovers)

options:
  -h, --help            show this help message and exit
  --format {text,json}
  --alignment ALIGNMENT
  --min-votes MIN_VOTES
  --permutations PERMUTATIONS
  --seed SEED
```

### `impsolver schema`

```text
usage: impsolver schema [-h] [--format {text,json}] [--out OUT]

options:
  -h, --help            show this help message and exit
  --format {text,json}
  --out OUT
```
