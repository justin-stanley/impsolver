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

Other inputs to try: `rho`, `senate_tie_break`, `alignment` with `alignment_chamber_weight`,
`defection_prior`, and `attendance: random` with `absence_rate` (see
[attendance](../methodology/model.md#attendance)).
