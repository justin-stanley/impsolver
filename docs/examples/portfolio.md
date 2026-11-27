# Several cases at once

`examples/portfolio-example.yaml` holds placeholder officials:

- two scenario cases, A and B, whose probabilities come from simulation;
- four cases with probabilities supplied directly;
- one succession rule: if official A is removed, official F's case becomes a different case,
  `official-f-acting`.

--8<-- "examples/generated/portfolio.md"

How to read it:

- **Plans** list the order of trials and the dates for each phase. "p" is the probability after
  fatigue from earlier trials.
- **Dropped** explains every case left out. Official E's probability is below the floor. Official
  D is excluded by official C, a choice the input makes; for example, two articles about the same
  conduct.
- **Sensitivity** re-solves with other fatigue values and durations and shows how much the
  recommended order would lose.

The same result as a planning page, with a timeline, gate-by-gate odds, the members nearest each
case's binding-gate threshold (by the supplied probabilities) and the removals distribution, is
the [demo](../demo/index.html). Build your own with `impsolver portfolio FILE --html plan.html`. The page's tornado charts show
how each scenario case's odds in the plan move when one bloc prior, `rho` or the fatigue delta
moves one notch (see [the method](../methodology/portfolio.md#tornado-chart)).

## Comparing scenarios

`viability` ranks the scenarios you supply. The support gap is the uniform log-odds shift toward
PRO that would bring P(removal) to the target:

--8<-- "examples/generated/viability.md"

`compare-plans` puts two scenarios (or two portfolios) side by side, with one-notch sensitivity
for each. Add `--html compare.html` for a page with the same content and tornado charts:

--8<-- "examples/generated/compare-plans.md"
