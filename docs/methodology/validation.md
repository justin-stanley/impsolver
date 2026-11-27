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

## What has not been checked

- The probabilities themselves. They are inputs, and the tool cannot tell you whether they are
  right.
- Out-of-sample performance. The calibration uses one event, 8 House members and 7 senators, and
  the fit is in-sample.
- Whether breaking ranks on ordinary votes predicts crossing on impeachment. The defection prior
  assumes it does.
- Turnout in trials before 1986. The sources give guilty and not-guilty counts only, so those
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
| Same draw at every gate in a chamber | always | H1 adds little risk once H2 is modelled |
| Senate tie-break | none | Changes S1 and S3 when the Senate splits evenly |
| Senate alignment weight | 0 | On applies loadings that showed no validation signal |
| Attendance | fixed by roster | Nobody is randomly absent |
