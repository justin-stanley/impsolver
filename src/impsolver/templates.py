# SPDX-FileCopyrightText: 2026 Justin Stanley
# SPDX-License-Identifier: MIT
"""Commented starter files written by ``impsolver init``.

Every template uses placeholder officials and placeholder numbers. Written into one folder as
``composition.yaml``, ``scenario.yaml`` and ``portfolio.yaml``, the three validate together.
"""

from __future__ import annotations

COMPOSITION = """\
# Composition: who holds each seat. Written by `impsolver init composition`.
# The counts below are PLACEHOLDERS, not any real Congress. Replace them with current figures
# from primary sources (clerk.house.gov, senate.gov), or build a member-level roster from
# Voteview with `impsolver roster`.
schema_version: 1
name: example-chamber
as_of: 2027-01-04
bodies:
  house:
    seats: 435
    vacancies: 1                  # members + vacancies must equal seats
    # party_shorthand makes anonymous members per party (ids like R-001, D-001).
    party_shorthand: {R: 217, D: 217}
  senate:
    seats: 100
    party_shorthand: {R: 50, D: 48, I: 2}
    # Or list members instead of party_shorthand (give exactly one of the two):
    # members:
    #   - {id: S-EX1, name: Example Senator, party: R, state: XX}
    #   - {id: S-EX2, name: Another Senator, party: I, caucus: D, state: XX}
"""

SCENARIO = """\
# Scenario: one hypothetical case. Written by `impsolver init scenario`.
# The target and every probability are PLACEHOLDERS that you supply; impsolver evaluates only
# the targets you give it and does not nominate targets.
schema_version: 1
# With office "president", the Chief Justice presides at the Senate trial.
target: {name: Example Official, office: cabinet_secretary}
articles: [I]
rules: us-federal                 # built-in rule set, or a path to your own rules YAML
# Relative paths resolve against this file's folder. Create the composition with
#   impsolver init composition --out composition.yaml
composition: composition.yaml
# P(member votes PRO) per bloc; keys are stages (H1 H2 S1 S2 S3) or "*" for all of them.
party_priors:
  D: {"*": 0.90}
  I: {"*": 0.85}
  R: {"*": 0.30, H1: 0.40}
# A value may also be a range {low: 0.2, high: 0.4} or a distribution {beta: [3, 7]}; set
# uncertainty_draws: 200 to have `simulate` report a 5-95% interval over them.
# Per-member overrides use the member ids from the composition, for example:
# overrides:
#   R-001: {"*": 0.5}
# Shifts move a bloc on the log-odds scale, optionally at one stage or article:
# shifts:
#   - {label: example shift, bloc: R, delta: 0.5, stage: S2}
cutoffs: [0.1, 0.9]               # below / above these a member counts as CON / PRO in `evaluate`
rho: 0.6                          # correlation of the party swing in `simulate`
seed: 7
# senate_tie_break: none          # none | pro | con: your stated assumption for S1/S3 ties
"""

PORTFOLIO = """\
# Portfolio: several hypothetical cases to schedule. Written by `impsolver init portfolio`.
# Candidates, probabilities and durations are PLACEHOLDERS that you supply; the solver only
# orders and schedules them and never adds candidates.
schema_version: 1
start: 2027-01-04
deadline: 2028-12-15
house_concurrency: 2              # House cases worked on at once; the Senate tries one at a time
fatigue_delta: 0.1                # log-odds penalty per earlier attempt
p_floor: 0.05                     # candidates below this P are dropped
draws: 5000                       # Monte Carlo draws per scenario-backed candidate
calendar:
  house:
    weekdays: [0, 1, 2, 3, 4]     # 0 = Monday
    recess: [[2027-08-02, 2027-09-06]]
  senate:
    weekdays: [0, 1, 2, 3, 4]
    recess: [[2027-08-02, 2027-09-06]]
  trial_saturdays: true
candidates:
  # A candidate gives exactly one of `scenario` (a file; P comes from simulating it) or `p`.
  # Create the scenario with: impsolver init scenario --out scenario.yaml
  - {id: official-a, scenario: scenario.yaml, house_days: 40, senate_days: 25}
  # `after` lists candidate ids whose trials must end before this House phase starts.
  - {id: official-b, p: 0.4, house_days: 30, senate_days: 15, after: [official-a]}
  # Other optional fields: release, deadline, weight, excludes, senate_committee,
  # committee_floor_days, succession, variant_of (see the file-format reference).
"""

TEMPLATES: dict[str, str] = {
    "composition": COMPOSITION,
    "scenario": SCENARIO,
    "portfolio": PORTFOLIO,
}

# File names the templates expect for each other when they share a folder.
DEFAULT_NAMES: dict[str, str] = {k: f"{k}.yaml" for k in TEMPLATES}
