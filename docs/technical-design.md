# impsolver — technical design (recovered)

This spec was rebuilt on 2026-11-27 from the transcript of the earlier session. The tool is neutral:
the user supplies the candidates, and the tool never nominates targets.

## Stack
Python 3.12, pydantic v2 (strict, extra=forbid), ruamel.yaml (safe), numpy, PuLP<3 (CBC),
pytest + hypothesis, ruff, mypy strict, uv. The CLI uses argparse (`impsolver = impsolver.cli:main`)
and runs fully offline.

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

## Rules (rules/us-federal.yaml)
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

## Scenario resolution
p_pro resolves in this order: override, member stage value, member `*`, party stage, party `*`.
If none resolves, raise an error. A shift is p' = sigmoid(logit p + sum of deltas); 0 and 1 stay
fixed. Deterministic classification: p >= hi gives PRO, p <= lo gives CON, otherwise UNCERTAIN.
The verdict is PASS at pro_min, FAIL at pro_max, otherwise CONTESTED.

## Flips
- Greedy: cheapest members first, by cost 1-p.
- ILP: x_i is PRO, a_i is absent (only with --allow-absence), x+a<=1.
  - Majority: sum x - sum(1-x-a-present) >= 1 (>= 0 in the fail direction).
  - 2/3: 3*sum x >= 2*sum(1-a).
  - Objective: 1e4 times the change count plus secondary costs; a flip beats an absence.
- Constraints `BLOC<=N` and `--exclude`. Report INFEASIBLE. Absences are labelled
  "procedural sensitivity, not a recommendation".

## Monte Carlo
Gaussian copula: u_i = sqrt(rho) z_bloc + sqrt(1-rho) e_i, and PRO iff u_i < Phi^-1(p).
With alignment: u_ig = sqrt(rho) z_bloc + sqrt(1-rho)(s_ig F_i·w + sqrt(psi_i) e_i), where
psi_i = 1-||F_i||^2. s_ig is the sign of (bloc lean - 0.5), and the lean is the mean p of the
bloc's free members at the gate. Defaults: 100k draws in 10k chunks, PCG64(seed).

## Alignment, defection prior, calibration, viability, portfolio
These follow the spec relayed in parts 2 and 3; see the module docstrings in `src/impsolver/`.
