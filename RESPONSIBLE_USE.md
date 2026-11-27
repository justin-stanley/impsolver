# Responsible use and neutrality

impsolver does arithmetic and simulation on public rules. It is meant for analysis, teaching and
research about how impeachment and removal votes work. This policy says what the project will and
will not host, so moderation follows written rules rather than anyone's politics.

## What the tool is

- **Rules, not predictions.** Gate thresholds, quorum and paths come from public House and Senate
  rules. Every probability comes from the user. Outputs are conditional on those inputs; they are
  not forecasts of any real vote.
- **Neutral by construction.** impsolver evaluates only the targets in its input files. No code
  path suggests, ranks or adds targets, and the test suite checks this.
- **Symmetric.** Every feature works the same way for any party and for either side of a vote.

## What the project will not ship

- Lists of real officials as targets, or rankings of real people as targets.
- Scenarios about real, current officials with invented probabilities. Examples use placeholder
  officials ("Official A") and placeholder numbers.
- Historical material other than public roll-call records with cited sources.

## Contributions and discussions

- **Data corrections** need a primary source: the House Clerk, the House Press Gallery,
  senate.gov or Voteview. They are judged only on that source.
- **Out of scope:** advocacy for or against any official or party, and requests to evaluate a
  named real person. Such issues and discussions are closed or locked with a link to this policy.
- **Numerical changes** to default results must be called out in the pull request and the
  CHANGELOG.

## Reporting misuse or a policy concern

Use GitHub's private reporting: **Security → Report a vulnerability** on the repository page,
and say that it is a responsible-use report. For questions that are not sensitive, open an issue
with the "question" template.

## Known limits

The validation evidence is thin and several modelling choices move the results. Read
[Limitations](https://github.com/justin-stanley/impsolver#limitations) before quoting any number produced with this tool.
