# Probability model

## Where each probability comes from

For each member and gate, impsolver resolves P(PRO) in this order and stops at the first hit:

1. a scenario `override` for that member, stage-specific before `"*"`;
2. the member's own `p_pro` in the composition;
3. the scenario's `party_priors` for the member's bloc (caucus if set, otherwise party);
4. otherwise an error.

Shifts then move it on the log-odds scale: p′ = σ(logit p + Σ δ). Probabilities of exactly 0 or 1
never move.

## Deterministic bounds

`evaluate` classifies members with the scenario `cutoffs` (default 0.1 and 0.9): PRO at or above
the high cutoff, CON at or below the low one, uncertain in between. A gate **passes** if it passes
with every uncertain member against, **fails** if it fails with every uncertain member for, and is
otherwise **contested**.

## Monte Carlo

`simulate` uses a Gaussian copula. For member *i* in bloc *b*:

u = √ρ · z_b + √(1 − ρ) · e_i, and the member is PRO when u < Φ⁻¹(p).

z_b is a bloc-wide swing and e_i is individual noise. Every marginal probability is preserved;
ρ (default 0.6) controls how much a bloc moves together. By default the same draw is reused at
every gate in a chamber, so a member who is unusually favourable at H1 is also favourable at H2.
With `national_swing: true` the House and Senate share one swing per bloc.

### Gate correlation

`gate_correlation` (c, between 0 and 1, default 1) loosens the link between gates in the same
chamber. For each gate after the first, every part of the draw (the bloc swing z_b, the
co-defection factor weights if an alignment file is used, and the individual noise e_i) becomes

x_g = √c · x_(g−1) + √(1 − c) · x′, with x′ a fresh standard normal.

Each part stays standard normal, so every member's probability at every gate is unchanged; only
the joint behaviour across gates moves. At c = 1 the draw is reused exactly as before. At c = 0 the
gates are independent given the probabilities: an unusually favourable H1 says nothing about H2.
Lower values usually make a full path harder to complete, because each gate is a separate chance
to fall short. With `national_swing`, the first gate in each chamber uses the shared swing and
later gates mix in their own fresh swing, so c < 1 also weakens the House–Senate link.

### Attendance

By default attendance is **fixed**: every member the roster marks `present` votes at every gate.
With `attendance: random` in the scenario, each present member is instead absent in a draw with
their own missed-vote rate, independently of their vote and of everyone else. The rate comes from,
in order:

1. the member's `p_absent` in the composition;
2. the alignment file's `n_missed / n_possible` for that member, when the scenario names one
   (`impsolver align` counts roll calls recorded as "not voting" out of every roll call the member
   could have cast, contested or not);
3. the scenario's `absence_rate` (default 0).

One attendance draw covers every gate in a chamber. An absent member drops out of the votes cast,
out of the two-thirds-of-present denominator at S2 and out of the quorum count, so absences on the
CON side lower the conviction threshold and enough absences can deny a quorum. Absences use their
own random stream, so the vote draws are the same as with fixed attendance.

A missed-vote rate measures routine roll calls. Members may attend a trial or an impeachment
vote more reliably than that, and a member's rate can reflect a role or a spell of absence that
does not apply to the vote in question. Treat the rates as an assumption to vary, not a forecast. `evaluate` and `flips` keep fixed attendance; use
`flips --allow-absence` to see which absences would decide a gate.

### Co-defection loadings

With an alignment file, part of the individual noise is replaced by k latent factors learned from
roll calls (`impsolver align`). For every contested vote, the loadings encode whether a member
broke from their bloc's majority, so members who break together get similar loadings. At each
gate, the sign of the factor term follows the bloc's lean, so "breaking" always means voting
against the bloc's likely position. Senate loadings are off by default
(`alignment_chamber_weight`); see [validation](validation.md).

### Defection prior

`defection_prior` shifts party-prior probabilities by each member's historical break rate, shrunk
toward the bloc rate with `pseudo_votes`. Members who break more often move away from their
party's lean. β = 1 by default. `impsolver score` shows how β and the correlation settings score
against the known crossover votes; see [validation](validation.md#calibration-sweep).
