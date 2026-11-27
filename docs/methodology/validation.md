# Validation and limits

## What has been checked

- **Arithmetic.** All 16 historical roll calls in the fixtures reproduce their recorded outcome
  and shortfall. These are Johnson 1868, Clinton 1998, Trump 2019 and 2021, and Mayorkas 2024.
  The fixtures cite the House Clerk and Senate pages they were checked against.
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

## Modelling choices that move results

| Choice | Default | Effect |
| --- | --- | --- |
| Bloc correlation ρ | 0.6 | Higher ρ widens the spread of outcomes |
| Shared swing across chambers | off | On makes House and Senate outcomes move together |
| Same draw at every gate in a chamber | always | H1 adds little risk once H2 is modelled |
| Senate tie-break | none | Changes S1 and S3 when the Senate splits evenly |
| Senate alignment weight | 0 | On applies loadings that showed no validation signal |
| Attendance | fixed by roster | Nobody is randomly absent |
