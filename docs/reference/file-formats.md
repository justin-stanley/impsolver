# File formats

All inputs are YAML (or JSON) validated against strict schemas: unknown keys are errors. The
schemas are generated from the models with `impsolver schema --out schemas`. A test fails when
the committed copies fall out of date.

`impsolver init composition|scenario|portfolio` writes a commented starter for each of the files
you edit by hand, and `impsolver validate` checks them (`--portfolio FILE` for a portfolio and
the scenarios it references). See [Getting started](../getting-started.md#start-from-templates).

| File | Schema | Example |
| --- | --- | --- |
| Rule set | `schemas/rules.schema.json` | `src/impsolver/data/rules/us-federal.yaml` |
| Composition | `schemas/composition.schema.json` | `compositions/shorthand-119.yaml`, `compositions/us-119.yaml` |
| Scenario | `schemas/scenario.schema.json` | `examples/scenario-example.yaml` |
| Portfolio | `schemas/portfolio.schema.json` | `examples/portfolio-example.yaml` |
| Alignment | `schemas/alignment.schema.json` | `alignment/us-116.json` |
| Historical fixture | `schemas/fixture.schema.json` | `src/impsolver/data/fixtures/trump-2021.yaml` |
| Crossover fixture | `schemas/crossovers.schema.json` | `src/impsolver/data/fixtures/members/trump-2021-crossovers.yaml` |

Paths inside a scenario or portfolio are relative to that file. A scenario's `rules` may instead
name a built-in rule set (`us-federal`).
