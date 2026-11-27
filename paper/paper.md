---
title: "impsolver: vote math for U.S. impeachment and removal"
tags:
  - Python
  - political science
  - legislatures
  - roll-call votes
  - Monte Carlo
  - integer programming
  - scheduling
authors:
  - name: Justin Stanley
    # TODO before submission: add the author's ORCID (orcid: 0000-...) and confirm the affiliation.
    affiliation: 1
affiliations:
  - name: "Affiliation to be confirmed by the author"
    index: 1
date: 27 November 2026
bibliography: paper.bib
---

# Summary

Removing a U.S. federal official takes a chain of recorded votes. The House impeaches by a
majority of votes cast; the Senate convicts only with "the Concurrence of two thirds of the
Members present" [@usconst]; and along the way each chamber can end a case on a procedural motion.
Each vote has its own threshold, its own denominator and its own quorum, so whether a case
succeeds depends on attendance, on which side a motion's "yea" serves, and on how votes in one
chamber relate to votes in the other.

impsolver is a Python package and command-line tool that does this arithmetic. The user describes
a case: the official, the House and Senate rosters, and a probability that each member votes for
the case at each step. impsolver reports the votes each step requires given who is present, which
step decides the case and how far short it falls, the fewest members whose votes would have to
change (an exact integer program), the probability of removal under correlated party swings (a
Gaussian-copula Monte Carlo), and, for several cases at once, the order and dates that maximise
expected removals under limited floor time. It replays 85 recorded roll calls from 13 historical
cases and reproduces every outcome and shortfall.

Every probability is an input. impsolver is not a forecaster and does not estimate how anyone will
vote; it computes what the rules require and what follows from the user's stated assumptions.

# Statement of need

Questions about impeachment arithmetic come up in teaching, in research on legislative procedure
and in public discussion: how many votes conviction needs if some senators are absent, whether a
motion to table in the House is a harder or easier hurdle than adoption, how much a party's
cohesion widens the range of outcomes, or how competing cases interact when the Senate can hold
only one trial at a time. The answers are usually worked out by hand, one threshold at a time,
and the assumptions behind them are rarely written down.

We are not aware of an open-source tool that encodes the full sequence of House and Senate votes
as data, checks it against the historical record, and exposes every modelling assumption as an
explicit input. impsolver aims to fill that gap for analysts, instructors and researchers. Its
design goals are:

- **Rules as data.** The gates, thresholds, quorum rules and paths live in a YAML rule set that is
  validated against a strict schema, so a different rule set can be studied without code changes.
- **Reproducibility.** Every random number comes from a seeded generator, the derived data files
  carry pinned checksums of their Voteview sources [@voteview], and the worked examples in the
  documentation are regenerated from the code and checked in CI.
- **Neutrality by construction.** The tool evaluates only the targets in its input files; no code
  path suggests, ranks or adds targets (see the neutrality statement below).

# Methods

## Gates

The built-in rule set, `us-federal`, has five gates. PRO denotes the side that moves the case
forward, so on a motion to table or dismiss PRO is a nay.

| Gate | Chamber | Vote | PRO needs |
| --- | --- | --- | --- |
| H1 | House | Motion to table or refer a privileged resolution | the motion fails: PRO $\ge$ CON |
| H2 | House | Adopt an article of impeachment | PRO $>$ CON among votes cast |
| S1 | Senate | Motion to dismiss or point of order | the motion fails: PRO $\ge$ CON |
| S2 | Senate | Conviction | $3\,\mathrm{PRO} \ge 2\,(\mathrm{PRO} + \mathrm{CON} + \mathrm{present})$ |
| S3 | Senate | Disqualification, only after conviction | PRO $>$ CON |

Path A starts at H1 (a resolution offered on the floor); path B starts at H2 after a committee
report. A path ends at the first failed gate, and removal occurs when S2 passes. Every gate also
requires a quorum, a majority of sworn members; a vote without one is reported as `NO_QUORUM`
rather than as a failure on the merits. Thresholds use exact integer arithmetic: two-thirds of
100 present is 67, of 99 is 66 and of 54 is 36.

Given per-member probabilities and cutoffs (by default 0.1 and 0.9), `evaluate` classifies members
as PRO, CON or uncertain and reports, per gate, the minimum and maximum PRO count, the number
required and a verdict: PASS if the gate passes with every uncertain member against, FAIL if it
fails with every uncertain member for, CONTESTED otherwise. `flips` finds the fewest stance changes
that pass a chosen set of gates. It solves a binary integer program with PuLP [@pulp] and CBC
[@cbc]: one variable per member marks a PRO vote, optional absence variables model attendance, and
each gate contributes a linear constraint (for S2, $3\sum_i x_i \ge 2\sum_i (1 - a_i)$). The
objective counts changes first and breaks ties in favour of members with higher supplied
probabilities, and a flip always beats an absence at equal counts. A greedy
heuristic is also available.

## Copula model of correlated votes

Members of a party do not vote independently, so `simulate` uses a Gaussian copula
[@nelsen2006copulas]. For member $i$ in bloc $b$ with probability $p_i$ of voting PRO,

$$u_i = \sqrt{\rho}\, z_b + \sqrt{1-\rho}\, e_i, \qquad \text{PRO} \iff u_i < \Phi^{-1}(p_i),$$

where $z_b$ is a bloc-wide swing, $e_i$ is individual noise and both are standard normal. Each
member's marginal probability is preserved exactly; $\rho$ (default 0.6) sets how strongly a bloc
moves together. By default one draw covers every gate in a chamber, so a member who is unusually
favourable at H1 is also favourable at H2. A scenario option `gate_correlation` $c$ mixes in a
fresh standard normal at each later gate, component by component
($x_g = \sqrt{c}\,x_{g-1} + \sqrt{1-c}\,x'$), which keeps the marginals. House and Senate swings
are independent unless `national_swing` is set, and attendance is fixed by the roster unless a
scenario sets `attendance: random`, which drops each member independently at a missed-vote rate
taken from the roster, from the alignment file's Voteview counts or from a scenario default.
The default is 100,000 draws from a seeded PCG64 generator [@harris2020numpy].

## Alignment and the defection prior

Optionally, part of the individual noise is replaced by $k$ latent co-defection factors learned
from roll calls [@voteview]. `impsolver align` marks, for every contested roll call (one on which
the two largest blocs took opposite majorities), whether each member broke from their bloc's
majority, computes pairwise correlations of these breaks, shrinks each correlation toward the mean
of its bloc-pair cell with weight $n/(n+\kappa)$ ($\kappa = 50$ by default), projects the result
to a valid correlation matrix by clipping negative eigenvalues, and keeps the top $k = 5$
eigenvectors as loadings $F_i$ with $\lVert F_i\rVert^2 < 1$. In the simulation,

$$u_{ig} = \sqrt{\rho}\, z_b + \sqrt{1-\rho}\,\big(s_{ig}\, F_i \cdot w + \sqrt{1 - \lVert F_i\rVert^2}\, e_i\big),$$

where $w$ is a standard normal factor draw and $s_{ig} = \pm 1$ follows the sign of the bloc's lean
at gate $g$, so that "breaking" always means voting against the bloc's likely position. Senate
loadings are off by default because the Senate showed no signal in calibration (see Validation).

A separate `defection_prior` shifts each member's party-prior probability by their historical
break rate $r_i$, shrunk toward the bloc rate $r_b$ with 20 pseudo-votes:
$p_i = \sigma\big(\operatorname{logit} p_{\text{party}} \pm \beta\,[\operatorname{logit} r_i - \operatorname{logit} r_b]\big)$,
with the sign chosen so that members who break more often move away from their party's lean and
$\beta = 1$ by default.

## Scheduler with causal succession

`impsolver portfolio` orders and schedules several user-supplied cases to maximise expected
removals, $E = \sum_i w_i P_i$ over the cases that finish by their deadlines. The House works on up
to `house_concurrency` cases at once; the Senate holds one trial at a time; durations are working
days on chamber calendars with recesses. Each later trial may be harder,
$P = \sigma(\operatorname{logit} P_0 - \delta m)$, where $m$ counts earlier trials. Plans are built
one case at a time by a search over ordered subsets that prunes a partial plan when another with
the same cases is at least as valuable and frees both chambers no later. The search is exact up to
10 eligible cases and uses a beam of 4,096 partial plans above that. Each plan is re-run with the
fatigue parameter and the durations varied to report regret, and the distribution of the number
of removals is simulated jointly, with scenario cases sharing one party-swing stream.

A case can depend on another: if official T is removed, official X's case may change (for example,
a deputy becomes acting head) or be cancelled. The plan then branches at T's verdict, and the
branches are *causal*: they differ only in work that starts after that verdict. House work already
begun on a cancelled case is lost, and a replacement case needs fresh House time from the day after
the verdict. Within each branch the cases whose House work has not started are re-ordered, over
every permutation when at most six remain, with ties going to the original order; work begun
before the verdict keeps its House start. Because the original order is always among the options,
adapting a branch never lowers expected removals. At most three triggers branch in one plan.

For the placeholder portfolio shipped as `examples/portfolio-example.yaml` (seven cases, two with
simulated probabilities and five with fixed ones), the best plan has $E = 1.377$ expected
removals. One case is dropped because its probability, 0.020, is below the 0.05 floor, and one is
excluded by another. The dependent case is scheduled first, so its trial ends before the trigger's
and the succession rule leaves the value unchanged ("With succession: ... E=1.377"). The joint
removals distribution has mean 1.364 and standard deviation 0.982, against 0.877 if the cases
were independent: the shared party swing widens the spread.

# Validation

## Backtest

`impsolver backtest` replays 85 recorded roll calls from 13 cases and checks the outcome and
shortfall of each against the recorded tally; all match. The cases are the House and Senate votes
on Andrew Johnson (1868), Bill Clinton (1998–1999), Donald Trump (2019–2020 and 2021) and
Alejandro Mayorkas (2024), the trial of William Belknap (1876), and the Senate trials of Judges
Charles Swayne (1905), Robert Archbald (1913), Halsted Ritter (1936), Harry Claiborne (1986),
Alcee Hastings and Walter Nixon (1989) and Thomas Porteous (2010). Each fixture in the repository
cites the House Clerk or senate.gov roll-call pages it was checked against, or, for trials with no
Senate roll-call page, the senate.gov case pages and the House precedents published on
govinfo.gov [@senateimpeachmentlist; @clerk2021; @senate2021; @hinds; @cannon; @deschler]. The
fixtures exercise the edge cases of the rules: Ritter's article VII passed at exactly 56 of 84
present, the minimum two-thirds; Claiborne's article III (46–17 with 35 senators voting
"present") failed by 20 because "present" counts in the denominator; Johnson's article XI
(35–19) failed by one vote; and disqualification votes passed for Archbald (39–35) and Porteous
(94–2) and failed for Ritter (0–76). The 2024 House votes on Mayorkas (214–216, then 214–213) and
the Senate's sustained points of order (51–48–1 and 51–49) test the majority and fail-direction
rules. The backtest checks the rules engine only; it does not test any probability.

## Calibration

The co-defection model is checked on one event: the members of the 116th Congress's Republican
conference who voted to impeach in the House (roll call 17 of 2021, 232–197 [@clerk2021]) or to
convict in the Senate (vote 59 of the 117th Congress, 57–43 [@senate2021]). Only 116th Congress
roll calls are used to fit the alignment, so the votes being predicted are not in the history.
`impsolver calibrate` reports, per chamber, the crossers' break rate against their party's, their
mean pairwise alignment against 2,000 random same-party sets (a permutation p-value), and a
logistic fit of $\beta$:

| Chamber | Crossers matched / party members | Break rate, crossers vs party | Alignment, crossers vs random (p) | $\beta$ |
| --- | --- | --- | --- | --- |
| House | 8 / 201 | 0.165 vs 0.069 | 0.33 vs 0.20 (0.012) | 1.31 ± 0.43 |
| Senate | 7 / 54 | 0.058 vs 0.027 | 0.20 vs 0.25 (0.744) | 0.89 ± 0.47 |

Two House crossers had no 116th Congress record and could not be matched. In the House the
crossers were more aligned with each other than random same-party sets; in the Senate they were
not, which is why Senate loadings are off by default.

`impsolver score` turns the same event into per-member predictions of who crossed and scores them
with the Brier score [@brier1950] and the log loss [@gneiting2007], both lower-is-better, over a
grid of $\beta$, $\rho$ and alignment weight. Members recorded as not voting are left out (41 in
the House and 8 in the Senate), leaving 160 House members (8 crossed) and 46 senators (7 crossed).
From the defection prior alone, the House log loss is 0.1985 at $\beta = 0$, 0.1654 at the
default $\beta = 1$ and 0.1642 at $\beta = 1.25$, the best value on the grid; in the Senate it is
0.4265 at $\beta = 0$ and 0.3846 at the default, which is the best. Break rates therefore carry
signal in both chambers. Conditioning on how every other member voted, through the copula, did not
improve on this: the default House setting ($\beta = 1$, $\rho = 0.6$, alignment weight 1) scores
0.1828 against the marginal 0.1654. The five best grid points in each chamber all have
$\rho = 0$, and the best House point with a positive alignment weight (0.1691) still scores worse
than the best marginal prediction. With a single event, the bloc swing is pinned down by the other members'
votes, so $\rho$ cannot be measured from it, and the defaults were not changed.

## Limits

The validation is thin. The probability model is calibrated on one event, 8 House members and
7 senators, scored in-sample with the observed crossing share as the base rate. The backtest
validates the rules, not the probabilities, which remain the user's inputs. Results depend on
modelling choices that the tool exposes but cannot settle: the bloc correlation $\rho$, whether
swings are shared across chambers and across gates, the Senate alignment weight, attendance, and
how a tied Senate majority vote is resolved (`senate_tie_break`, a stated assumption rather than a
rule). Procedure is simplified: nobody votes "present" in simulations, Senate time is reserved
even if the House vote might fail, and calendars are simple. Rosters go stale and must be checked
against current sources before use.

# Neutrality statement

impsolver evaluates only the targets in its input files. No code path suggests, ranks or adds
targets, and the test suite checks this. Every feature works the same way for any party and for
either side of a vote. The project's responsible-use policy (`RESPONSIBLE_USE.md`) excludes target
lists, rankings of real people as targets, and scenarios about real, current officials with
invented probabilities; the shipped examples use placeholder officials ("Official A", "Example
Official") and placeholder numbers. The historical cases above appear only as recorded tallies
from primary sources, used to test the rules engine, and this paper makes no claim about how any
real official would or should be treated. Outputs are conditional on the user's inputs and are not
forecasts of any real vote.

# Acknowledgements

Rosters, co-defection loadings and break rates are derived from the Voteview congressional
roll-call database [@voteview]; we thank its maintainers for making the data public. impsolver
builds on NumPy [@harris2020numpy], PuLP [@pulp] and the COIN-OR CBC solver [@cbc].

# References

<div id="refs"></div>

# Appendix: commands behind the numbers

Every number in this paper was produced by impsolver at the commit this paper was written against
(the `roadmap/v0.2` integration branch), run from the repository root with the committed data
files. The same commands generate the worked examples in `docs/examples/generated/`, which
`python docs/examples/run_examples.py --check` keeps up to date, and `tests/test_paper.py` checks
that the numbers quoted here still appear in their output.

```bash
uv sync --extra dev --extra docs
uv run impsolver backtest                       # 85 roll calls, 13 cases, "backtest: all match"
uv run impsolver evaluate examples/scenario-example.yaml
uv run impsolver portfolio examples/portfolio-example.yaml          # E = 1.377; removals mean 1.364, sd 0.982
uv run impsolver calibrate --alignment alignment/us-116.json --permutations 2000
uv run impsolver score --alignment alignment/us-116.json --draws 4000
```

Thresholds quoted in the Methods section (67 of 100, 66 of 99, 36 of 54) are the outputs of
`impsolver.thresholds`, which the test suite checks directly.
