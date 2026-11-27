# impsolver

impsolver counts the votes needed to impeach and remove a U.S. official, and estimates the odds of
getting them. You describe a case: the official, the chamber rosters, and each member's
probability of voting for it. impsolver works out what the House and Senate rules require at each
step, how close the case is, which votes decide it, and, for several cases at once, which order
and timing give the most expected removals.

!!! note "Results depend on your inputs"
    Every probability is an input you supply. Read [validation and limits](methodology/validation.md)
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
pip install "git+https://github.com/justin-stanley/impsolver@v0.1.0"
```

impsolver is not on PyPI yet.

Then follow [Getting started](getting-started.md).
