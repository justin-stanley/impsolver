```console
$ impsolver score --alignment alignment/us-116.json --draws 4000
score: events trump-2021; base rate observed share per event; min votes 100
lower is better (Brier = mean squared error, log = mean log loss in nats)

house: 1 event(s), 160 members, 8 crossed
  trump-2021: 41 members left out as not voting
  trump-2021 unmatched: Peter Meijer, David Valadao
  marginal P(cross), by beta:
    beta  0.00  Brier 0.0475  log 0.1985
    beta  0.25  Brier 0.0463  log 0.1861
    beta  0.50  Brier 0.0451  log 0.1765
    beta  0.75  Brier 0.0440  log 0.1696
    beta  1.00  Brier 0.0432  log 0.1654  <- default
    beta  1.25  Brier 0.0430  log 0.1642
    beta  1.50  Brier 0.0438  log 0.1661
    beta  1.75  Brier 0.0456  log 0.1714
    beta  2.00  Brier 0.0483  log 0.1799
    beta  2.50  Brier 0.0560  log 0.2063
    beta  3.00  Brier 0.0659  log 0.2437
  best by log: beta 1.25; by Brier: beta 1.25
  conditional P(cross | other members), top 5 of 132:
    beta 1.25, rho 0, weight 0               Brier 0.0430  log 0.1642
    beta 1, rho 0, weight 0                  Brier 0.0432  log 0.1654
    beta 1.5, rho 0, weight 0                Brier 0.0438  log 0.1661
    beta 1.25, rho 0, weight 0.5, kappa 50   Brier 0.0442  log 0.1691
    beta 0.75, rho 0, weight 0               Brier 0.0440  log 0.1696
    default: beta 1, rho 0.6, weight 1, kappa 50: Brier 0.0465  log 0.1828
  best by Brier: beta 1.25, rho 0, weight 0
  smallest effective draws: 7 of 4000; best settings skip points below 100

senate: 1 event(s), 46 members, 7 crossed
  trump-2021: 8 members left out as not voting
  marginal P(cross), by beta:
    beta  0.00  Brier 0.1290  log 0.4265
    beta  0.25  Brier 0.1234  log 0.4053
    beta  0.50  Brier 0.1192  log 0.3919
    beta  0.75  Brier 0.1165  log 0.3852
    beta  1.00  Brier 0.1157  log 0.3846  <- default
    beta  1.25  Brier 0.1170  log 0.3896
    beta  1.50  Brier 0.1203  log 0.3996
    beta  1.75  Brier 0.1252  log 0.4138
    beta  2.00  Brier 0.1310  log 0.4316
    beta  2.50  Brier 0.1438  log 0.4759
    beta  3.00  Brier 0.1567  log 0.5289
  best by log: beta 1; by Brier: beta 1
  conditional P(cross | other members), top 5 of 132:
    beta 1, rho 0, weight 0                  Brier 0.1157  log 0.3846
    beta 0.75, rho 0, weight 0               Brier 0.1165  log 0.3852
    beta 1.25, rho 0, weight 0               Brier 0.1170  log 0.3896
    beta 0.5, rho 0, weight 0                Brier 0.1192  log 0.3919
    beta 1.5, rho 0, weight 0                Brier 0.1203  log 0.3996
    default: beta 1, rho 0.6, weight 0: Brier 0.1279  log 0.4262
  best by Brier: beta 1, rho 0, weight 0
  smallest effective draws: 1 of 4000; best settings skip points below 100
note: base rate is each event's observed crossing share, so scores measure how well the settings rank and spread members, not how well the overall rate is guessed
note: one event only: no leave-one-event-out scores; all scores are in-sample
note: the sweep reports only; it does not change any default
```
