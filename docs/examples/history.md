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

The fixtures live in `src/impsolver/data/fixtures/`, each with links to the House Clerk and
senate.gov pages it was checked against.
