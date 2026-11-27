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

### Pooled history (116th to 118th Congress)

The same fixture, still matched on 116th Congress ids, was run against the pooled
`alignment/us-116-118.json` (equal weight) and against a pool with `--half-life 1`
(`impsolver calibrate --alignment FILE`, 5000 permutations, seed 0):

| History | Body | Party members | Crossers' break rate | Party break rate | Alignment, crossers vs random (p) | β |
| --- | --- | --- | --- | --- | --- | --- |
| 116 | House | 201 | 0.165 | 0.069 | 0.33 vs 0.19 (0.012) | 1.31 ± 0.43 |
| 116 to 118, equal | House | 303 | 0.177 | 0.064 | 0.30 vs 0.19 (0.024) | 1.62 ± 0.49 |
| 116 to 118, half-life 1 | House | 299 | 0.178 | 0.065 | 0.30 vs 0.19 (0.027) | 1.66 ± 0.49 |
| 116 | Senate | 54 | 0.058 | 0.027 | 0.20 vs 0.25 (0.753) | 0.89 ± 0.47 |
| 116 to 118, equal | Senate | 64 | 0.246 | 0.090 | 0.34 vs 0.21 (0.013) | 1.44 ± 0.49 |
| 116 to 118, half-life 1 | Senate | 58 | 0.297 | 0.099 | 0.32 vs 0.20 (0.011) | 1.38 ± 0.48 |

In the House, pooling changes little: the crossers break about 2.8 times as often as the party
rather than 2.4 times, and their co-defection signal is about as strong. In the Senate the pooled
crossers break about 2.7 times as often as their party (2.1 times in the 116th alone) and now look
aligned. **Do not read the pooled Senate result as validation.** The 117th Congress began on
January 3, 2021, so the pool contains the votes being predicted (in the Voteview files, House
roll call 16 of the 117th Congress, 232 to 197 with 10 Republicans in favour, and Senate roll call
59, 57 to 43 with 7 Republicans for conviction) and four years of votes cast after them. The 116th-only
calibration is the only one without that leakage, and the defaults (`alignment_chamber_weight`
Senate 0, the β values above) still rest on it. The pooled file is offered as a longer history for
scenarios about later congresses, not as a better-validated one.

## What has not been checked

- The probabilities themselves. They are inputs, and the tool cannot tell you whether they are
  right.
- Out-of-sample performance. The calibration uses one event, 8 House members and 7 senators, and
  the fit is in-sample.
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
