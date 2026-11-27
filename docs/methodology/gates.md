# Rules and gates

The built-in rule set `us-federal` models five recorded votes. A case moves through them in order
and stops at the first gate it fails.

| Gate | Chamber | The vote | What PRO needs |
| --- | --- | --- | --- |
| H1 | House | Motion to table or refer the privileged resolution | The motion fails: PRO ≥ CON (a tie defeats it) |
| H2 | House | Adopt an article of impeachment | PRO > CON among votes cast |
| S1 | Senate | Motion to dismiss, or a point of order against the articles | The motion fails: PRO ≥ CON |
| S2 | Senate | Conviction | PRO ≥ two-thirds of senators present |
| S3 | Senate | Disqualification (optional, after conviction) | PRO > CON |

**PRO** means the side that moves the case forward. On H1 and S1 that is a *nay* on the motion.

**Paths.** Path A starts at H1, for a privileged resolution offered on the floor. Path B starts at
H2 and applies when a committee has reported (`committee_reports: true`). Removal happens when S2
passes; S3 is reported only after a conviction.

**Quorum.** Every gate needs a majority of sworn members present. A vote that misses quorum is
reported as `NO_QUORUM`, not as a failure on the merits.

**Two-thirds of those present.** Members answering "present" count in the denominator by default
(`present_in_denominator`). Absent members do not, so attendance moves the threshold:
2/3 of 100 is 67, of 99 is 66, of 54 is 36.

**Presiding officer.** For a presidential trial the Chief Justice presides at S2; otherwise the
President pro tempore or the Vice President. How an exact tie on a Senate majority vote (S1, S3)
is resolved in an impeachment trial is not settled in the rules file. The scenario input
`senate_tie_break` (`none`, `pro` or `con`) states that assumption explicitly; `none` keeps the
plain rule that a tie defeats the motion.

## Custom rules

A rule set is a YAML file with `stages`, `paths` and `quorum`. Each stage has a `rule` of kind
`majority_of_votes_cast`, `fraction_of_present` (with `p` and `q`) or `fraction_of_membership`,
and a `pass_direction` of `pass` (yea is PRO) or `fail` (nay is PRO). The schema is in
`schemas/rules.schema.json`.
