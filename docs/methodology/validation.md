# Validation and limits

## What has been checked

- **Arithmetic.** All 85 historical votes in the 13 fixtures reproduce their recorded outcome and
  shortfall. These are Belknap 1876, Johnson 1868, Clinton 1998, Trump 2019 and 2021, Mayorkas
  2024, and the Senate trials of Judges Swayne (1905), Archbald (1913), Ritter (1936), Claiborne
  (1986), Hastings and Nixon (1989) and Porteous (2010). Each fixture cites the House Clerk or
  Senate roll-call pages it was checked against. Trials before 1989 have no Senate roll-call pages,
  so those fixtures cite the senate.gov case pages or the House precedents (Hinds', Cannon's and
  Deschler's) on govinfo.gov, which reprint the Senate Journal tallies.
- **Mixed verdicts and edge cases.** The judicial trials convict on some articles and acquit on
  others, so the backtest scores completion per case. They also test the boundary of the
  two-thirds rule (Ritter's article VII passed at exactly 56 of 84), "present" votes in the
  denominator (Claiborne's article III), and disqualification votes (S3) that passed (Archbald,
  Porteous) or failed (Ritter).
- **Co-defection signal.** `impsolver calibrate` asks whether the learned alignment picks out the
  Republicans who voted to impeach or convict in 2021, using only 116th Congress roll calls.

--8<-- "examples/generated/calibrate.md"

In the House, the eight crossers were more aligned with each other than random same-party sets.
In the Senate they were not, so Senate alignment is off by default.

## Calibration sweep

`impsolver score` turns the 2021 check into scores. For every member of the crossing party with
at least 100 votes in the history congress, it predicts whether that member crossed and scores
the predictions with the Brier score (mean squared error) and the log loss (mean −log
probability of what happened, in nats). Lower is better for both. It scores two kinds of
prediction:

- **Marginal**, P(cross), from the defection prior alone:
  p = sigmoid(logit b + β · excess), where b is the event's observed crossing share. Only β
  matters here, because correlation settings never change a member's own probability.
- **Conditional**, P(cross | how every other member voted), from the simulation's copula with
  bloc correlation ρ and alignment loadings scaled by the alignment weight. This is where ρ, the
  alignment weight and κ (the shrinkage used to fit the loadings) can show up. It is computed by
  importance sampling over the bloc swing and factor weights, and the output gives the smallest
  effective number of draws so that noisy grid points can be spotted.

The grid is β from 0 to 3, ρ in {0, 0.3, 0.6, 0.9} and weight in {0, 0.5, 1}, plus the defaults.
Each alignment file is one κ; to sweep κ, refit with `impsolver align --kappa K` and pass each
file with `--alignment`. With more than one crossover fixture, each event is held out in turn:
the best settings on the others are scored on it, next to the defaults' score.

The "smallest effective draws" line is the minimum over the whole grid. Below, it comes from
corner settings (β ≥ 2, ρ = 0.9, weight 1); the best and default settings have about 1,000 or
more of the 4,000 draws.

--8<-- "examples/generated/score.md"

Refitting the 116th Congress alignment at κ = 10 and κ = 200 (same Voteview files as
`alignment/us-116.json`, `impsolver align ... --kappa 10`, then `impsolver score --alignment
alignment/us-116.json --alignment us-116-k10.json --alignment us-116-k200.json`, 10,000 draws)
changes little in the House: the best weighted setting at each κ is β = 1.25, ρ = 0, weight 0.5,
with log loss 0.1443 (κ 10), 0.1442 (κ 50) and 0.1439 (κ 200), against 0.1401 with no alignment,
and for ρ ≤ 0.6 and β ≤ 1.5 no setting moves by more than 0.004 across κ. In the Senate the best
weighted setting at each κ is β = 0.75, ρ = 0, weight 0.5: 0.3672 (κ 10), 0.3678 (κ 50) and
0.3632 (κ 200), still worse than no alignment (0.3508). With Senate weight 1 the effective draws
fall to single digits, because the Senate loadings are close to unit norm, so those scores are
noisy. The refitted files are not committed.

What the sweep suggests, read with care:

- **β.** In the House, β = 1.25 scores slightly better than the default β = 1 (log loss 0.1401
  vs 0.1410; Brier 0.0353 vs 0.0354), consistent with the logistic fit of 1.31 ± 0.43. In the
  Senate the default β = 1 is best on the grid. Both beat β = 0 (House 0.1673, Senate 0.3857), so
  break rates carry signal in both chambers.
- **ρ, alignment weight and κ.** Within this single event, every setting with ρ > 0 or an
  alignment weight above 0 scores worse than the marginal prediction, in both chambers. The
  default House setting (β = 1, ρ = 0.6, weight 1) has log loss 0.156 against 0.140. Two cautions: with
  one event, the bloc swing is a single draw that the other members' votes pin down, so ρ mostly
  acts as a second spread parameter that trades off against β; and how much a party's crossing
  share varies from one event to the next, which is what ρ is for, cannot be measured from one
  event at all. The House permutation test above still finds the crossers more aligned than
  random sets; the sweep says that this does not make the other crossers' votes help predict a
  given member's.
- **Defaults are unchanged.** The evidence is one event, 8 House and 7 Senate crossers, scored
  in-sample with the observed crossing share as the base rate, and there are no
  leave-one-event-out scores. That is too thin to move β from 1 to 1.25 or to lower ρ or the House
  alignment weight. More crossover fixtures, from other events, are needed before any default
  should change.

## What has not been checked

- The probabilities themselves. They are inputs, and the tool cannot tell you whether they are
  right.
- Out-of-sample performance. The calibration uses one event, 8 House members and 7 senators, and
  the fit is in-sample. `impsolver score` reports leave-one-event-out scores once there is more
  than one crossover fixture.
- Whether breaking ranks on ordinary votes predicts crossing on impeachment. The defection prior
  assumes it does.
- Turnout in trials before 1989. The sources give guilty and not-guilty counts only, so those
  fixtures derive `not_voting` from the seated membership the senate.gov party-division table shows
  for that session. It affects only the quorum check. The pre-1990 House votes are left out
  (except Ritter's and Johnson's resolutions), because their full tallies or vacancies could not be
  checked against a primary source.
- Member-level crossover sets for the judicial trials. Their votes did not split on party lines,
  and the calibration uses only the 116th Congress.

## Modelling choices that move results

| Choice | Default | Effect |
| --- | --- | --- |
| Bloc correlation ρ | 0.6 | Higher ρ widens the spread of outcomes |
| Shared swing across chambers | off | On makes House and Senate outcomes move together |
| Gate correlation (`gate_correlation`) | 1 (same draw at every gate in a chamber) | At 1, H1 adds little risk once H2 is modelled; lower values treat each gate as a fresh chance to fall short |
| Senate tie-break | none | Changes S1 and S3 when the Senate splits evenly |
| Senate alignment weight | 0 | On applies loadings that showed no validation signal |
| Attendance | fixed by roster | `random` drops members at their missed-vote rates; absences lower the S2 threshold and can deny a quorum |
