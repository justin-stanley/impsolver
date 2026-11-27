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
ρ (default 0.6) controls how much a bloc moves together. The same draw is reused at every gate in
a chamber, so a member who is unusually favourable at H1 is also favourable at H2. With
`national_swing: true` the House and Senate share one swing per bloc.

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
party's lean. β = 1 by default.
