# Probability model

## Where each probability comes from

For each member and gate, impsolver resolves P(PRO) in this order and stops at the first hit:

1. a scenario `override` for that member, stage-specific before `"*"`;
2. the member's own `p_pro` in the composition;
3. the scenario's `party_priors` for the member's bloc (caucus if set, otherwise party);
4. otherwise an error.

Shifts then move it on the log-odds scale: p′ = σ(logit p + Σ δ). Probabilities of exactly 0 or 1
never move.

## Uncertain priors

A `party_priors` or `overrides` value can be a number, a range or a Beta distribution:

```yaml
party_priors:
  D: {"*": 0.97}                                  # a number, as before
  R: {"*": {low: 0.20, high: 0.40}, S2: {beta: [3, 7]}}
overrides:
  R-001: {"*": {low: 0.4, high: 0.8}}
uncertainty_draws: 200                            # outer Monte Carlo draws; 0 (default) is off
```

A range says only that the probability lies between `low` and `high`; a Beta(a, b) gives it a
distribution with mean a / (a + b). Member `p_pro` values in a composition stay numbers. Files
written before this option existed load and give the same results.

Each command uses one number per prior, except `simulate` with the outer loop on:

| Where | Range `{low, high}` | Beta `{beta: [a, b]}` |
| --- | --- | --- |
| `evaluate`: pro_min (is the member certainly PRO?) | `low` | 5th percentile |
| `evaluate`: pro_max (is the member certainly not CON?) | `high` | 95th percentile |
| `evaluate` pivots, `flips`, `compare`, `viability`, `portfolio`, and `simulate` with `uncertainty_draws: 0` | midpoint (low + high) / 2 | mean a / (a + b) |
| `simulate` with `uncertainty_draws` N > 0 | uniform on [low, high] | Beta(a, b) |

In `evaluate` a member counts as PRO only if the low value is at or above the high cutoff, and
as CON only if the high value is at or below the low cutoff; everyone else is uncertain. A range
therefore can only widen the [pro_min, pro_max] bounds compared with its midpoint.

### The outer loop

With `uncertainty_draws` N > 0 (or `simulate --uncertainty-draws N`), `simulate` runs two loops:

1. **Outer draws.** For each of N draws, every uncertain prior is sampled once. A prior is one
   entry in the file, such as `R: {"*": …}` or `overrides: R-001: {S2: …}`. Every member and stage
   that resolves to that entry gets the same sampled value in that draw: all members of the bloc
   share it, and a `"*"` entry gives the same value at every stage that falls back to it. Shifts
   are then applied as usual. The samples come from their own stream, PCG64([seed, 0x0DD5]).
2. **Inner draws.** Each outer draw runs the usual copula simulation with `--draws` draws (2,000
   by default when the outer loop is on, instead of 100,000). Every outer draw uses the same
   inner seed (common random numbers), so the differences between outer draws come only from the
   sampled priors.

`P(complete)` is the mean over outer draws, which is the probability with the prior uncertainty
averaged in. The output adds the 5th and 95th percentiles of P(complete) across outer draws
(`p_complete_interval` in JSON): the range of removal probabilities that the stated prior
uncertainty allows. Gate rows pool every inner draw of every outer draw. The MC standard error is
√(var_t / N + p(1 − p) / draws), where var_t is the variance of P(complete) across outer draws;
the second term remains because the inner draws are shared.

With more than one article, every article in an outer draw uses the same sampled priors and the
same inner draws, and the output adds a line "Any article: P(removal)" (`p_any_complete` and
`p_any_complete_interval` in JSON): the chance that at least one article convicts, with its 5th
and 95th percentiles across outer draws.

Because P(complete) is not linear in the priors, the pooled mean usually differs from the result
at the midpoints. The other commands use the midpoints, so a portfolio candidate or a viability
row backed by this scenario does not include the prior uncertainty.

With a `defection_prior` or a `score_prior`, `evaluate` and the other single-number commands
adjust the midpoint; the outer loop adjusts each sampled value instead. Members whose probability
either prior sets therefore have no separate low and high bounds in `evaluate`.

See the [worked example](../examples/assumptions.md#a-range-instead-of-a-number).

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
chamber. For each gate after the first, the member-level parts of the draw (the co-defection
factor weights if an alignment file is used, and the individual noise e_i) become

x_g = √c · x_(g−1) + √(1 − c) · x′, with x′ a fresh standard normal.

The bloc swing z_b stays the same at every gate: it is one party mood for the whole chamber, and
swings shared across chambers (`national_swing`) or across portfolio cases stay fully shared.

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

`impsolver align` can pool several congresses: pass the vote and member files of each (the
committed `alignment/us-116-118.json` pools the 116th to 118th). Every roll call counts equally
unless you pass `--half-life H`, which gives a roll call from a congress d congresses before the
latest a weight of 0.5^(d/H); the weights apply to the correlations and to the break and attendance
counts written to the file, and the file records `half_life`.

### Defection prior

`defection_prior` shifts party-prior probabilities by each member's historical break rate, shrunk
toward the bloc rate with `pseudo_votes`. Members who break more often move away from their
party's lean. β = 1 by default. `impsolver score` shows how β and the correlation settings score
against the known crossover votes; see [validation](validation.md#calibration-sweep).

### Score prior

Members who have just arrived have no break rate, so the defection prior leaves them at their
party prior. `score_prior` is an optional hook for them: if you supply an external score for each
such member (`impsolver roster --member-scores`, see [data sources](../data.md#member-scores-user-supplied)),
a scenario can map it to a shift on the logit scale, per bloc:

```yaml
alignment: ../alignment/us-119.json
score_prior:
  R: {slope: 0.5, intercept: 0.0}
```

For a member of bloc R with standardized score z, every stage's party prior p becomes
sigmoid(logit(p) + intercept + slope · z). It applies only to members who have a `score`, whose
bloc is listed, who have no recorded vote in the scenario's alignment file for their chamber, and
whose probability is not already set by the composition (`p_pro`, including a defection prior's
result) or an override. That is why `score_prior` requires `alignment`. A party prior of exactly
0 or 1 is left as it is.

impsolver does not choose a direction or size for the shift and ships no scores: the sign of
`slope` decides which end of the score's scale moves toward PRO, and both numbers are your
assumptions to state. Nothing in the backtests calibrates them, and default results are unchanged
when `score_prior` is absent.
