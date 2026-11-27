# impsolver

impsolver does the vote math for U.S. federal impeachment and removal. Give it a target **you**
choose, a chamber roster and per-member probabilities. It works out what the House and Senate
rules require at each step, how close the case is, which votes decide it, and, for several cases
at once, which order and timing give the most expected removals.

!!! note "Neutral by design"
    impsolver evaluates only the targets in its input files. It never suggests, ranks or adds
    targets, and its results are only as good as the probabilities you give it. Read the
    [responsible-use policy](responsible-use.md) and [validation and limits](methodology/validation.md)
    before quoting any number.

## What it answers

| Question | Command |
| --- | --- |
| Does this case pass each gate, fail, or depend on uncertain members? | `impsolver evaluate` |
| What is the fewest members whose stance would have to change? | `impsolver flips` |
| How likely is removal once bloc swings and co-defection are modelled? | `impsolver simulate` |
| Which of my scenarios are closest to viable? | `impsolver viability` |
| In what order and on what dates should several cases run? | `impsolver portfolio` |
| Do the rules reproduce past votes? | `impsolver backtest` |

The [demo planning page](demo/index.html) shows `impsolver portfolio --html` output for a
portfolio of placeholder officials.

## Install

```bash
pip install impsolver
```

Then follow [Getting started](getting-started.md).
