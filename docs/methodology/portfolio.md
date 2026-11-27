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

## Seat changes

A portfolio can list dated changes to who holds a seat, such as a resignation, a death, or a
successor sworn in:

```yaml
roster_changes:
  - {date: 2027-03-01, chamber: senate, vacate: SEN-B-07}       # seat falls vacant
  - date: 2027-04-15
    chamber: senate
    seat: {id: SEN-NEW-1, name: Placeholder successor, party: B}  # fills a vacancy
  - {date: 2027-05-01, chamber: house, vacate: REP-A-12,           # one member replaces another
     seat: {id: REP-NEW-1, name: Placeholder member, party: A}}
```

`vacate` names a member of the scenario's composition and adds one vacancy; `seat` is a full
member entry (the same fields as in a composition) and fills one vacancy. Give both to replace a
member. Changes are cumulative: each one applies to every scenario case whose Senate trial starts
on or after its date, and changes on the same date apply in the order listed. Cases with a fixed
`p` are not affected.

The distinct dates split the window into roster epochs. Epoch 0 is the scenario's own
composition; epoch *k* starts on the *k*-th date. P₀ is simulated once per case and epoch, with
the same seed, and a case scheduled with its trial starting on day *t* uses the P₀ of the epoch in
force on *t*. Fatigue then applies as usual. Some consequences:

- **The whole case uses one roster**, the one in force on the trial's first day, House votes
  included. A House change dated between a case's House vote and its trial is therefore counted
  for that case even though the House had already voted. This keeps one P₀ per slot; put House
  changes on or before the start of the House phase they should affect.
- **P depends on the schedule.** The same case can be worth more or less depending on where it
  sits in the order, and the search may delay a case behind another one so its trial starts after
  a helpful vacancy (the solver never adds idle days: a case still starts as early as its lanes
  allow).
- **A new member needs a probability.** The scenario's `party_priors` for their bloc apply, or
  give `p_pro` on the seat entry. An alignment file has no record of a new member, so they get
  their bloc's mean loadings and a `defection_prior` leaves their prior unadjusted. `impsolver validate --portfolio` resolves every epoch, so an unknown
  `vacate` id, a seat with no vacancy left, or a new member with no prior fails there.
- `LOW_P` uses the highest P₀ over all epochs: a case is dropped only if no roster gives it a
  chance of at least `p_floor`.
- The gate-path and pivot panels describe epoch 0. The plan tables show each slot's own P₀ and
  note the roster date it used; the joint removals distribution simulates each trial against its
  own epoch's roster.

Pruning has to allow for epochs. Without roster changes, a partial plan that frees the House and
Senate no later than another, with at least the same value, is at least as good for every
continuation. With roster changes that is no longer true: freeing the Senate earlier can put the
next trial before a vacancy that would have helped it. The search therefore prunes such a plan
only when it leads by a margin. Run from the plan with earlier lanes, the same continuation
starts every trial no later, so it can only lose where a case's P rises from one epoch to a later
one. The margin is, for each case not yet scheduled, its largest such rise in fatigued P over the
epochs a later trial can still reach, times its weight. It is zero once the Senate frees up on or
after the last change date, and zero for cases whose P only falls (for example a vacancy among
supporters), so pruning is then as before. The optimistic bound uses each case's best P₀ over all
epochs. With no `roster_changes` the search and its results are unchanged. When P rises after a
change the exact search prunes less: with 10 cases (the exact limit) one search took about 4 s
in testing against 0.5 s without changes, and `portfolio` runs seven (the plan plus six
sensitivity rows).

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
