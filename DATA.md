# Data sources and citation

impsolver's code is MIT-licensed (see `LICENSE`). Some files in this repository are derived from
third-party data, which keeps its own terms and citation request.

## Voteview

Rosters and alignment loadings are built from Voteview's member and roll-call vote files. Voteview
asks users to cite the dataset as:

> Lewis, Jeffrey B., Keith Poole, Howard Rosenthal, Adam Boche, Aaron Rudkin, and Luke Sonnet
> (2026). *Voteview: Congressional Roll-Call Votes Database.* https://voteview.com/

Source: the citation request on <https://voteview.com/data>, accessed 2026-11-27. Voteview is
hosted and maintained by the UCLA Department of Political Science and Social Science Computing
(<https://voteview.com/about>). As of that date the site did not state a separate license for the
data files. If you reuse the derived files below, cite Voteview as above.

### Files derived from Voteview

| File | Built from (accessed 2026-11-27) | Command |
| --- | --- | --- |
| `compositions/us-119.yaml` | `H119_members.csv`, `S119_members.csv`, `H119_votes.csv`, `S119_votes.csv` | `impsolver roster` |
| `alignment/us-116.json` | `H116_votes.csv`, `S116_votes.csv`, `H116_members.csv`, `S116_members.csv` | `impsolver align` |
| `alignment/us-119.json` | `H119_votes.csv`, `S119_votes.csv`, `H119_members.csv`, `S119_members.csv` | `impsolver align` |

Each file carries the citation and access date: the roster in its header comment, the alignment
files in their `source` field. The raw CSVs are not redistributed. Download them with
`scripts/fetch-voteview.sh` (they come from `https://voteview.com/static/data/out/`), then rebuild
with the commands in `README.md`. Pass `--accessed YYYY-MM-DD` so the citation in the regenerated
file records when you downloaded the data.

### Corrections applied on top of Voteview

Voteview reflects recorded votes, so it lags some changes. The `us-119` roster applies two facts
checked on 2026-11-27 against current official sources:

- Rep. Kevin Kiley (K000401) is an independent who caucuses with Republicans
  (`--member-caucus K000401=R`). Sources: [Fox40](https://fox40.com/inside-california-politics/kevin-kiley-independent-republican-caucus/),
  [Semafor](https://www.semafor.com/article/09/16/2026/kiley-says-he-wont-caucus-with-republicans-if-reelected).
- Rep. Kevin Hern (H001082) resigned effective 2026-11-27 (`--vacate H001082`). Source: floor
  proceedings shown on the [House Press Gallery](https://pressgallery.house.gov/member-data/party-breakdown).

The resulting party counts were checked against the
[House Press Gallery party breakdown](https://pressgallery.house.gov/member-data/party-breakdown)
and the [Senate party division](https://www.senate.gov/history/partydiv.htm).

## Historical roll calls

The backtest fixtures in `src/impsolver/data/fixtures/` record public roll-call tallies. Each
fixture lists the House Clerk (<https://clerk.house.gov/Votes>) and U.S. Senate
(<https://www.senate.gov/legislative/votes_new.htm>) pages it was checked against, and the date of
that check. Trials before 1989 cite the senate.gov impeachment case pages or the House precedents
(Hinds', Cannon's and Deschler's) published on <https://www.govinfo.gov>. These records are works of the U.S. government.
