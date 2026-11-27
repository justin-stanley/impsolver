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
| `alignment/us-116-118.json` | `H{116,117,118}_votes.csv`, `S{116,117,118}_votes.csv`, `H{116,117,118}_members.csv`, `S{116,117,118}_members.csv` | `impsolver align` (pooled, equal weight) |

`us-116-118.json` pools the 116th, 117th and 118th Congresses with every roll call weighted
equally. Members are matched across congresses by Bioguide ID, and each member's party and bloc
are those of the latest congress they served in (votes cast under an earlier party are scored
against that party's bloc). Like the other files it maps independents (party code 328) to the
Democratic bloc: the senate.gov
[party division page](https://www.senate.gov/about/parties-leadership/party-division.htm)
(checked 2026-11-27) says both independents in the 117th Congress, and the independents of the
118th, Manchin included after his switch, caucused with the Democrats. The House had no
independents in either congress.

The alignment files also record each member's missed votes (`n_missed`, roll calls coded 9, "not
voting") out of the roll calls Voteview lists them on (`n_possible`); `attendance: random` uses
that ratio as a missed-vote rate.

Each file carries the citation and access date: the roster in its header comment, the alignment
files in their `source` field. The raw CSVs are not redistributed. Download them with
`scripts/fetch-voteview.sh` (they come from `https://voteview.com/static/data/out/`), then rebuild
with the commands below. Pass `--accessed YYYY-MM-DD` so the citation in the regenerated file
records when you downloaded the data. `make reproduce` runs all of this and checks the result
against the committed files.

```bash
scripts/fetch-voteview.sh 116 117 118 119
V=data/voteview
impsolver roster --members $V/H119_members.csv --members $V/S119_members.csv \
  --votes $V/H119_votes.csv --votes $V/S119_votes.csv --caucus 328=D \
  --member-caucus K000401=R --vacate H001082 --as-of 2026-11-27 --accessed 2026-11-27 \
  --out compositions/us-119.yaml
impsolver align --votes $V/H116_votes.csv --votes $V/S116_votes.csv \
  --members $V/H116_members.csv --members $V/S116_members.csv --caucus 328=D \
  --accessed 2026-11-27 --out alignment/us-116.json
impsolver align --votes $V/H119_votes.csv --votes $V/S119_votes.csv \
  --members $V/H119_members.csv --members $V/S119_members.csv --caucus 328=D \
  --member-caucus K000401=R --accessed 2026-11-27 --out alignment/us-119.json
# 116th-118th pooled; add --half-life N to weight recent congresses more (default: equal weight)
impsolver align --votes $V/H116_votes.csv --votes $V/S116_votes.csv \
  --votes $V/H117_votes.csv --votes $V/S117_votes.csv \
  --votes $V/H118_votes.csv --votes $V/S118_votes.csv \
  --members $V/H116_members.csv --members $V/S116_members.csv \
  --members $V/H117_members.csv --members $V/S117_members.csv \
  --members $V/H118_members.csv --members $V/S118_members.csv \
  --caucus 328=D --accessed 2026-11-27 --out alignment/us-116-118.json
```

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

## A roster for a new Congress from certified results

Voteview reflects recorded votes, so it cannot supply the roster of a new Congress before that
Congress votes. `impsolver roster --from-results` builds one from certified
election results instead. The repository does not ship a 120th-Congress roster: build it yourself
once the results are certified, and check it against official sources before you use it.

Write one CSV row per seat with the columns `chamber,state,district,name,party`, plus the
optional `bioguide_id` and `caucus`:

```text
chamber,state,district,name,party,bioguide_id,caucus
house,AA,1,Alice Alpha,R,A000001,
house,AA,2,Bob van Bravo Jr.,D,,
house,AA,4,,,,
house,BB,AL,Gus Golf,R,G000777,
senate,AA,,Sam One,R,,
```

- `chamber` is `house` or `senate`, and `state` is the 2-letter postal code. Rows for
  non-voting delegates (DC and the territories) are skipped.
- `district` is the House district number. `AL`, `0` and `00` mark an at-large seat, stored as
  district 1 as in the Voteview roster; the command fails when a state marked at-large also has
  numbered districts, in the CSV or in `--previous`. A district above the highest one the
  `--previous` roster lists for that state is flagged in the header. Without `--previous` the
  district numbers are not checked against apportionment. Leave it blank for the Senate.
- A row with a blank `name` is a vacant seat (for example a race not yet decided or certified).
- `party` is a code of 1 to 4 letters (`R`, `D`, `I`, ...); `Republican`, `Democrat`,
  `Democratic` and `Independent` are also accepted. Any other text (a state party's full name,
  for example) is an error: write the code of the party bloc you mean, and use `caucus` if the
  member caucuses with another party. `caucus` sets the member's bloc and beats
  `--member-caucus`, which beats the caucus a returning member had in `--previous` (kept only
  when the party is unchanged, and flagged), which beats `--caucus PARTY=BLOC`. Write `none` to
  use the member's own party.
- `bioguide_id` is the member's Biographical Directory ID
  (<https://bioguide.congress.gov/>). A member without one gets a placeholder id, `new:CA-06` in
  the House or `new:CA-S1` in the Senate, until an ID is assigned.

With `--previous COMPOSITION` (for example `compositions/us-119.yaml`), a row with a Bioguide ID
keeps that ID and is flagged when it is not in the previous roster. A row without one is matched
to a previous member of the same chamber and state with the same surname and a compatible given
name: the same first name, a prefix of at least 3 letters (`Nic` and `Nicholas`), a lone initial
(`J. Smith` and `SMITH, John`) or a first name equal to another given name (`Robert Smith` and
`SMITH, J. Robert`). Nicknames such as `Bob` for `Robert` do not match; such a member gets a
placeholder, flagged with the previous member who shares the surname, so add the `bioguide_id`.
The match is flagged in the member's `notes` and in the file header. A match is accepted only
when it is one to one, whatever the row order: if a row fits two previous members, or two rows
fit one previous member, none of them is matched, and each gets a placeholder and a flag. Name
matching stays within a chamber, so a House member elected to the Senate (or the reverse) needs
`bioguide_id` in the CSV; without it they get a new placeholder such as `new:CA-S1`. `--previous`
must list named members with states; a roster written with `party_shorthand` is refused.
Previous senators whose seats were not
up can be carried over with `--senate-holdovers`. A state keeps as many holdovers as it has seats
not listed in the results. A composition does not record Senate classes, so when a state has
more candidates than open seats (any state where the senator whose seat was up retired, resigned
or was defeated) the command stops and names them. Pass `--vacate ID` for each previous senator
who does not hold over, or list the seat in the CSV. Expect to do this for every such state.

The command fails if a seat appears twice, a state has more than 2 senators, a chamber has more
rows than seats, or a named row has no party. It also fails when the results do not cover every
seat (435 and 100), unless `--allow-missing` counts the unlisted seats as vacant. The header
names the results file, the `--source` you give (required), the access date and the previous
roster, and lists every vacancy, placeholder and flagged match.

```bash
impsolver roster --from-results results-120.csv \
  --source "Clerk of the House, election statistics for November 3, 2026" \
  --previous compositions/us-119.yaml --senate-holdovers --vacate ID_OF_DEPARTING_SENATOR \
  --caucus I=D \
  --name us-120 --as-of 2027-01-03 --accessed 2027-01-02 --out compositions/us-120.yaml
```

Primary sources for the rows:

- The Clerk of the House publishes the official vote counts for each federal election in its
  election statistics (<https://history.house.gov/Institution/Election-Statistics/Election-Statistics/>).
- The Clerk's member data and official list of members
  (<https://clerk.house.gov/Members>) and the Senate's list of senators
  (<https://www.senate.gov/senators/>) show who was sworn in.
- Bioguide IDs: <https://bioguide.congress.gov/>.

Once the new Congress has voted, rebuild the roster from Voteview with the commands above and
check the two against each other; `impsolver compare --composition A --composition B SCENARIO`
evaluates one scenario against both.

## Historical roll calls

The backtest fixtures in `src/impsolver/data/fixtures/` record public roll-call tallies. Each
fixture lists the House Clerk (<https://clerk.house.gov/Votes>) and U.S. Senate
(<https://www.senate.gov/legislative/votes_new.htm>) pages it was checked against, and the date of
that check. Trials before 1989 cite the senate.gov impeachment case pages or the House precedents
(Hinds', Cannon's and Deschler's) published on <https://www.govinfo.gov>. These records are works
of the U.S. government.
