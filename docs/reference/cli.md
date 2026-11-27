# CLI

Every command accepts `--format json` (before or after the command name) for machine-readable
output. Errors print to stderr and exit with status 2; `backtest` exits with 1 on a mismatch.
`roster` and `align` build data from Voteview; run them with `--help` for their options.
`roster --from-results RESULTS.csv --source TEXT --name NAME` builds a composition for a new
Congress from certified results instead (see
[Data](../data.md#a-roster-for-a-new-congress-from-certified-results)).
`roster --member-scores FILE.csv` also attaches user-supplied scores (`id,score,source`) for a
scenario's [`score_prior`](../methodology/model.md#score-prior).

--8<-- "examples/generated/cli.md"
