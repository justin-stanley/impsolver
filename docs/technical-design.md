# impsolver: technical design

The user supplies every case and every probability; the tool computes what the rules require.

## Stack
Python 3.12, pydantic v2 (strict, extra=forbid), ruamel.yaml (safe), numpy, PuLP 4 (CBC from
`pulp[cbc]`; PuLP 2.9 also works), pytest + hypothesis, ruff, mypy strict, uv. The CLI uses
argparse (`impsolver = impsolver.cli:main`) and runs fully offline.

## Gate math
- Stances: PRO / CON / PRESENT / ABSENT. With `pass_direction: pass`, yea = PRO; with `fail`, nay = PRO.
- `majority_of_votes_cast`: in the pass direction PRO needs pro > con. In the fail direction PRO
  needs pro >= con, because a tie defeats the motion.
- `fraction_of_present p/q`: q*pro >= p*(pro + con + present_counted). `present_in_denominator`
  defaults to true.
- `fraction_of_membership p/q`: q*pro >= p*base, where base = seats - vacancies when
  `vacancies_reduce_base` (default true).
- Quorum (`majority_of_sworn`) is a precondition; failing it gives NO_QUORUM.
- Integer ceil is `-(-p*n//q)`. `required_pro` is the minimal pro that passes: required passes and
  required - 1 fails. Examples: 2/3 of 100 is 67, of 54 is 36, of 99 is 66.

## Rules (built-in `us-federal`, src/impsolver/data/rules/us-federal.yaml)
| id | chamber | motion | rule | direction | next |
|----|---------|--------|------|-----------|------|
| H1 | house | table/refer privileged resolution | majority | fail | H2 |
| H2 | house | adopt article | majority | pass | S1 |
| S1 | senate | dismiss/point of order/table | majority | fail | S2 |
| S2 | senate | conviction | 2/3 of present | pass (terminal_on_pass) | S3 |
| S3 | senate | disqualification | majority | pass (optional) | — |

S2 is presided over by the chief justice when target.office is president, and otherwise by the
president pro tempore or the VP.

Paths: A = H1>H2>S1>S2(>S3). B (needs `committee_reports`) = H2>S1>S2(>S3). A path completes at
S2 and ends at the first failed gate. S3 applies only when S2 passes.

## Fixture tallies (backtest must match exactly)
- Johnson 1868: H2 126-47 PASS; S2 35-19 FAIL, 1 short (36 of 54 needed).
- Clinton 1998: H2 228-206 and 221-212 PASS; S2 45-55 FAIL (22 short) and 50-50 FAIL (17 short).
- Trump 2019: H2 230-197-1 and 229-198-1 PASS. S2 (2020) 48-52 and 47-53 FAIL.
- Trump 2021: H2 232-197 PASS; S2 57-43 FAIL, 10 short.
- Mayorkas 2024: H2 214-216 FAIL, then 214-213 PASS; S1 51-48-1 and 51-49, point of order
  sustained, path ends.
- Belknap 1876: S2 35-25, 36-25 (x3), 37-25 FAIL, each 5 short.
- Swayne 1905: twelve S2 votes FAIL; the closest, 35-47, is 20 short.
- Archbald 1913: S2 PASS on I, III, IV, V and XIII (42-20, just over two-thirds), FAIL on the other
  eight; S3 39-35 PASS.
- Ritter 1936: S2 FAIL on I-VI (55-29 is 1 short), PASS on VII at exactly 56 of 84; S3 0-76 FAIL.
- Claiborne 1986: S2 PASS on I, II and IV; III 46-17 with 35 present FAIL, 20 short of 66.
- Hastings 1989: S2 PASS on I-V and VII-IX; VI 48-47, XVI 0-95 and XVII 60-35 FAIL.
- Nixon 1989: S1 34-63 (dismissal rejected); S2 89-8 and 78-19 PASS, 57-40 FAIL, 8 short.
- Porteous 2010: H2 412-0, 410-0, 416-0, 423-0; S2 96-0, 69-27, 88-8, 90-6 PASS; S3 94-2 PASS.

Each article walks the path's required stages and ends at its first failed gate. Conviction on
any one article removes the official, so `expected_complete` is a case-level outcome: the case
completes when at least one article passes S2. A case that did not complete ends at the furthest
stage any article reached, and `expected_ends_at` names that stage. Votes on optional stages (S3)
are checked but do not change where a case ends; an S3 vote taken on the judgment as a whole uses
the label `judgment` rather than an article number. A fixture with no vote on any required stage
has no case outcome and fails the backtest.

## Scenario resolution
p_pro resolves in this order: override, member stage value, member `*`, party stage, party `*`.
If none resolves, raise an error. A shift is p' = sigmoid(logit p + sum of deltas); 0 and 1 stay
fixed. Deterministic classification: p >= hi gives PRO, p <= lo gives CON, otherwise UNCERTAIN.
The verdict is PASS at pro_min, FAIL at pro_max, otherwise CONTESTED.
A party prior or override may be a range `{low, high}` or `{beta: [a, b]}` (see
`src/impsolver/uncertainty.py`): classification uses low (Beta 5th percentile) for PRO and high
(95th percentile) for CON; everything else uses the mean (a range's midpoint).

## Flips
- Greedy: cheapest members first, by cost 1-p.
- ILP: x_i is PRO, a_i is absent (only with --allow-absence), x+a<=1.
  - Majority: sum x - sum(1-x-a-present) >= 1 (>= 0 in the fail direction).
  - 2/3: 3*sum x >= 2*sum(1-a).
  - Objective: 1e4 times the change count plus secondary costs; a flip beats an absence.
  - Solved with CBC (`COIN_CMD` on PuLP 4, the bundled `PULP_CBC_CMD` on PuLP 2.9). The counts are
    exact. When solutions have the same count and secondary costs within about `TIE_EPS` (1e-6),
    which members are listed, and at which gates under `--per-gate-stance` (every gate flip costs
    the same), can depend on the CBC build.
- Constraints `BLOC<=N` and `--exclude`. Report INFEASIBLE. Absences are labelled
  "procedural sensitivity, not a recommendation".

## Monte Carlo
Gaussian copula: u_i = sqrt(rho) z_bloc + sqrt(1-rho) e_i, and PRO iff u_i < Phi^-1(p).
With alignment: u_ig = sqrt(rho) z_bloc + sqrt(1-rho)(s_ig F_i·w + sqrt(psi_i) e_i), where
psi_i = 1-||F_i||^2. s_ig is the sign of (bloc lean - 0.5), and the lean is the mean p of the
bloc's free members at the gate. Defaults: 100k draws in 10k chunks, PCG64(seed). By default the
same draw is reused at every gate in a chamber; `gate_correlation` < 1 loosens that (see below).
Attendance (`attendance: fixed|random`, default fixed): with random, each present member is absent
in a draw with probability Member.p_absent, else the alignment file's n_missed/n_possible, else
`absence_rate` (default 0). One draw per chamber covers all its gates, from a separate stream
PCG64([seed, 0xA77E]). Absent members leave votes cast, the 2/3-of-present denominator and quorum.
Deterministic `evaluate` and `flips` keep fixed attendance.
Uncertain priors (`uncertainty_draws` N > 0): N outer draws from PCG64([seed, 0x0DD5]) sample each
range (uniform) or Beta prior once, shared by every member and stage resolving to it; each runs
the inner draws (default 2,000) with the same seed. P(complete) is the mean over outer draws, with
the 5th/95th percentiles across them and s.e. sqrt(var_t/N + p(1-p)/draws).

## Alignment, defection prior, calibration, viability, portfolio
See `docs/design-reference.md` and the module docstrings in `src/impsolver/`.

## Report contract
`portfolio --format json` (and the data embedded in `--html`) is a `PortfolioResult`; its schema
is `schemas/report.schema.json`. Version 2 (`src/impsolver/contract.py`) adds what a page needs to
draw from the JSON alone, and changes no number:
- `meta` (version, draws, file names, each scenario's seed, rho and cutoffs) and `inputs` (the
  portfolio as given).
- On each slot: `house_lane` (the scheduler always uses the lane that frees first, so replaying
  that recovers it), `house_start_reason` (`window_start`, `lane_free`, `release`, `after`,
  `not_before`) and `trial_start_reason` (`ready`, `committee`, `floor_busy`) with the case
  involved, `ready`, committee dates, and `house_days`, `trial_days`, `wait_trial_days` and
  `slack_days` in session days.
- On each plan: `budget`, the session days available and used per resource (House lanes, Senate
  committee, Senate floor) between the window's start and deadline.
- On each dropped candidate: `numbers`. LOW_P gives `p` and `p_floor`; NO_FIT gives `deadline`,
  `earliest_end` (scheduled first, with no deadline) and `days_over`; EXCLUDED gives `by`, `value`
  and `swap_value` (the best plan without the excluding cases); DEPENDENCY_DROPPED gives
  `waits_on`; NOT_SELECTED gives `value_without` and `value_with` (the best insertion into the
  recommended order).
- On each sensitivity row: `slots`, the recommended order re-scheduled under that setting.
- `gates[candidate]`: for the article the page shows, each gate's rule (with a sentence), seats,
  vacancies, members present, votes required, tally by bloc, the rank pivot (the member at position
  `required` when present members are sorted by supplied probability), and per-member columns
  (`p`, `source`, `cls`) aligned with the chamber roster.

`what_if` lists the recommended order under other settings, as sensitivity rows with a `kind`:
`setting` rows change the House lane count (`house_lanes`) or switch trial Saturdays, and `order`
rows swap two neighbours in the recommended order (`order` holds the swapped order,
`base_rescheduled` its value and `best` the recommended order's value). They are computed with
the sensitivities and never set `fragile`. The page's gate forms use only `gates`: the browser
repeats `thresholds.required_pro` on the counted classes and does not simulate.

## Changes since the original design
These change behavior relative to the original design.
- `alignment_chamber_weight` (default `{house: 1, senate: 0}`) multiplies `alignment_weight` for each
  chamber. The Senate defaults to 0 because the 2021 calibration found no Senate co-defection
  signal (permutation p = 0.75). Set it to 1 to restore the original behavior.
- `national_swing` (default false) draws one party swing per bloc for both chambers instead of one
  per chamber.
- `gate_correlation` c (default 1, the original design) sets how much each member's draw carries
  from one gate to the next in a chamber: the factor weights and individual noise at a later gate
  are sqrt(c) times the previous gate's plus sqrt(1-c) times a fresh standard normal, so marginals
  are preserved. The bloc swing stays fixed across gates, so national and portfolio-shared swings
  stay fully shared. Default results do not change.
- `senate_tie_break` (`none` | `pro` | `con`, default `none`) says how an exact tie on a Senate
  majority vote (S1, S3) is resolved. With `none`, a tie defeats the motion, as in the original design. Whether
  and how a presiding officer may break such a tie in an impeachment trial is not settled here, so
  the tool takes it as the user's stated assumption. The setting is applied in the deterministic
  bounds, the Monte Carlo and the ILP.
- Succession is causal. Branches after a trigger differ only in work that starts after its verdict.
  A cancelled dependent whose House work had begun keeps its lane through its House phase, and a
  variant (for example a successor in the office) needs fresh House time from the day after the verdict.
- Succession branches adapt. After a trigger's verdict, each branch re-orders the cases whose
  House work has not started, over every permutation when at most 6 remain (`ADAPTIVE_REORDER`),
  and keeps the original order on ties or above that limit. Work started before the verdict must
  stay in any re-ordered branch with its House start. Expected removals with succession can only rise;
  `succession_order` can change when a branch's best order differs from the order the branch would
  have kept. Results without succession rules, and the shipped examples, do not change.
- A portfolio candidate without `article` is removed if any article convicts: P0 is P(at least one
  article completes) from one simulation in which all articles share the party swings and member
  draws, and the joint removals distribution uses the same rule. Before, P0 was the first article's
  P(complete). Only scenarios with more than one article change.
- `party_priors` and `overrides` values may be ranges or Beta distributions, and
  `uncertainty_draws` (default 0, off) adds an outer Monte Carlo loop over them that reports a
  5-95% interval for P(complete). Number-valued files and default results do not change.
- Portfolio search: exact up to `exact_limit` = 10 eligible candidates, beam of 4096 above that.
- `flips` uses the ILP by default (`--greedy` for the heuristic).
- Unknown stage keys and shift articles are errors. Unknown member ids and blocs are warnings, and
  `validate` exits 2 on any warning. `validate --portfolio` applies the same checks to every
  scenario a portfolio references, without simulating them.
