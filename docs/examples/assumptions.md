# Changing assumptions

The same placeholder case, Official A, with one assumption changed: the House and Senate share
one party swing (`national_swing: true` in `examples/scenario-cabinet-a-national.yaml`).

**Independent swings (default):**

--8<-- "examples/generated/simulate-cabinet-a.md"

**One shared swing:**

--8<-- "examples/generated/simulate-national.md"

Sharing the swing raises P(removal) here. When the bloc is favourable in the House it is also
favourable in the Senate, so the draws that get past the House are the ones more likely to
convict. This is one reason the [validation page](../methodology/validation.md) lists correlation
choices among the assumptions that move results.

Other inputs to try: `rho`, `gate_correlation`, `senate_tie_break`, `alignment` with
`alignment_chamber_weight`, `defection_prior`, and `attendance: random` with `absence_rate` (see
[attendance](../methodology/model.md#attendance)).

## A range instead of a number

`examples/scenario-cabinet-a-uncertain.yaml` gives each R prior as a range whose midpoint is the
number used above (for example `R: {"*": {low: 0.20, high: 0.40}}` in place of 0.30), and sets
`uncertainty_draws: 200`:

--8<-- "examples/generated/simulate-uncertain.md"

P(complete) is the average over the 200 sets of R priors. The bracket after it is the 5th to
95th percentile of P(complete) across those sets: the spread that the stated ranges alone allow,
far wider than the Monte Carlo error. With `--uncertainty-draws 0 --draws 20000` the same file
runs at the midpoints and prints exactly the first result on this page. `evaluate` on this file
prints the same bounds as the original, because every R range lies between the 0.1 and 0.9
cutoffs. See [uncertain priors](../methodology/model.md#uncertain-priors).
