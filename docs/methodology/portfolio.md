# Portfolio scheduling

`impsolver portfolio` orders and schedules several user-supplied cases to maximise expected
removals: E = Σ wᵢ · Pᵢ over the cases that finish by their deadlines.

## Time model

- The House works on up to `house_concurrency` cases at once. The Senate holds one trial at a
  time.
- Durations are working days on each chamber's calendar, which has weekdays and recess ranges.
  Trials may also sit on Saturdays (`trial_saturdays`).
- Each phase starts the working day after the previous one ends. Senate time is reserved even if
  the House vote might fail. This is conservative.
- `senate_committee: true` sends evidence to a Senate committee first, then holds a short floor
  phase (`committee_floor_days`).

## Which article counts

A case backed by a scenario is removed if any of its articles convicts. When the candidate leaves
`article` unset, P₀ is the chance that at least one of the scenario's articles completes its path,
from one joint simulation: every article sees the same party swings and member draws, so articles
are as correlated as the scenario's members make them. P₀ is therefore at least the best single
article's chance and at most the sum. The gate-path panel shows the gates of the likeliest
article. Set `article` to score one article alone. A scenario with one article gives the same P₀ as
before.

## Fatigue

Each later trial can be harder: P = σ(logit P₀ − δ · m), where m is the number of earlier trials.

## Search

Plans are built one case at a time. Partial plans covering the same set of cases are pruned when
another is at least as valuable and frees the House and Senate no later. A plan is also dropped
when even an optimistic bound cannot reach the current top plans. Up to 10 eligible cases the
search is exact; above that a beam keeps the 4,096 best partial plans.

## Succession

A case can depend on another: if official T is removed, official X's case changes or is
cancelled. For example, a deputy becomes acting head. The plan branches at T's verdict, and the
branches differ only in work that starts after that verdict. House work already begun on a
cancelled case is lost; a replacement case needs fresh House time.

## Outputs

The top plans, why any case was left out (`LOW_P`, `NO_FIT`, `EXCLUDED`, `DEPENDENCY_DROPPED`,
`NOT_SELECTED`), sensitivity to fatigue and durations, the succession decision tree, and the
distribution of the number of removals. The joint distribution shares party swings across cases
(at the first gate in each chamber when a scenario sets `gate_correlation` below 1) and follows the same decision tree as the expected value. `--html` writes all of it as a
planning page.

## Tornado chart

For each case built from a scenario, the planning page (and `tornado` in the JSON output) shows
how its probability moves when one input moves one notch and the rest stay as supplied:

- each bloc's party prior, 0.05 down and up on the probability scale at every stage key the bloc
  lists, clipped to [0, 1] (a clipped notch is labelled);
- `rho`, 0.2 down and up, clipped to [0, 1];
- the portfolio's `fatigue_delta`, 0.2 down and up, with the recommended order held fixed.

The measured value is the case's P in the recommended order: P(removal) alone, then fatigue for
the trials before it in that order's schedule (succession branches are not followed). A case
left out of the plan is measured alone, without a fatigue bar. Every run reuses the scenario's
seed and the portfolio's `draws`, so the member and swing draws are common random numbers: the
base matches the plan, a swing reflects the input rather than Monte Carlo noise, and raising a
bloc's prior can only raise P as long as the bloc's average stays on the same side of 0.5 at
every gate (always, without alignment; with alignment the factor sign follows that side). Bars
are sorted by swing, largest first. Members with an override or their own `p_pro` do not move
with their bloc; a `defection_prior` is re-applied to the moved prior. P(removal) can move either
way with `rho`, so read both ends of its bar.

## Comparing two plans

`impsolver compare-plans A.yaml B.yaml --html out.html` computes two portfolios (or two
scenarios) exactly as `portfolio` (or `simulate`) would, then lines them up: a summary table with
the differences, and each side's plan, per-case odds and tornado charts in two columns that stack
on a phone. Scenarios use `--draws` (default 20,000) and their own seeds; portfolios use their
own `draws`. Mixing a portfolio and a scenario is an error.
