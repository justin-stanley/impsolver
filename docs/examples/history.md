# Replaying history

The backtest feeds recorded tallies through the built-in rules and checks the outcome, the
shortfall and where each case stopped. It tests the arithmetic only, not any probability.

--8<-- "examples/generated/backtest.md"

A few results worth noting:

- **Johnson 1868** fell one vote short: 35 of 54 senators voted guilty, and two-thirds of 54 is
  36.
- **Clinton 1999, article III,** was tied 50–50 and still 17 short of the 67 needed.
- **Mayorkas 2024** never reached a conviction vote. The Senate sustained points of order against
  both articles, so the path ends at S1.
- **Belknap 1876** was acquitted on all five articles, each five votes short. Most senators who
  voted not guilty said the Senate had no jurisdiction over an official who had already resigned.
- **Ritter 1936** was acquitted on the first six articles and convicted on the seventh by 56 of
  84, exactly two-thirds. A separate disqualification order then failed 0–76.
- **Claiborne 1986, article III,** drew 46 guilty, 17 not guilty and 35 "present". Present votes
  count toward the two-thirds, so 66 of 98 were needed and the article failed by 20. Without them
  it would have passed.
- **Archbald 1913** and **Porteous 2010** were convicted and then disqualified from future office
  by majority votes (39–35 and 94–2). Hastings, Nixon and Claiborne were removed without a
  disqualification vote.
- **Hastings 1989** was convicted on eight articles. Article VI drew a majority, 48–47, and was
  still 16 votes short.

A case completes when any article is convicted, because one conviction removes the official.
The per-article lines show which articles did and did not pass.

The fixtures live in `src/impsolver/data/fixtures/`. Each one links to the House Clerk or
senate.gov roll-call pages it was checked against. For trials before 1989 it links instead to
the senate.gov case pages or the House precedents on govinfo.gov.
