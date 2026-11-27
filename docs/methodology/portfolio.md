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
and follows the same decision tree as the expected value. `--html` writes all of it as a
planning page.
