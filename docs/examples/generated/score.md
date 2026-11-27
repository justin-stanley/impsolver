```console
$ impsolver score --alignment alignment/us-116.json --draws 4000
score: events trump-2021; base rate observed share per event; min votes 100
lower is better (Brier = mean squared error, log = mean log loss in nats)

house: 1 event(s), 201 members, 8 crossed
  trump-2021 unmatched: Peter Meijer, David Valadao
  marginal P(cross), by beta:
    beta  0.00  Brier 0.0382  log 0.1673
    beta  0.25  Brier 0.0374  log 0.1575
    beta  0.50  Brier 0.0367  log 0.1498
    beta  0.75  Brier 0.0359  log 0.1443
    beta  1.00  Brier 0.0354  log 0.1410  <- default
    beta  1.25  Brier 0.0353  log 0.1401
    beta  1.50  Brier 0.0360  log 0.1419
    beta  1.75  Brier 0.0378  log 0.1468
    beta  2.00  Brier 0.0406  log 0.1548
    beta  2.50  Brier 0.0492  log 0.1800
    beta  3.00  Brier 0.0606  log 0.2167
  best by log: beta 1.25; by Brier: beta 1.25
  conditional P(cross | other members), top 5 of 132:
    beta 1.25, rho 0, weight 0               Brier 0.0353  log 0.1401
    beta 1, rho 0, weight 0                  Brier 0.0354  log 0.1410
    beta 1.5, rho 0, weight 0                Brier 0.0360  log 0.1419
    beta 0.75, rho 0, weight 0               Brier 0.0359  log 0.1443
    beta 1.25, rho 0, weight 0.5, kappa 50   Brier 0.0361  log 0.1444
    default: beta 1, rho 0.6, weight 1, kappa 50: Brier 0.0380  log 0.1560
  best by Brier: beta 1.25, rho 0, weight 0
  smallest effective draws: 16 of 4000

senate: 1 event(s), 54 members, 7 crossed
  marginal P(cross), by beta:
    beta  0.00  Brier 0.1128  log 0.3857
    beta  0.25  Brier 0.1087  log 0.3682
    beta  0.50  Brier 0.1054  log 0.3570
    beta  0.75  Brier 0.1030  log 0.3514
    beta  1.00  Brier 0.1018  log 0.3508  <- default
    beta  1.25  Brier 0.1024  log 0.3550
    beta  1.50  Brier 0.1049  log 0.3636
    beta  1.75  Brier 0.1088  log 0.3760
    beta  2.00  Brier 0.1139  log 0.3917
    beta  2.50  Brier 0.1260  log 0.4315
    beta  3.00  Brier 0.1389  log 0.4799
  best by log: beta 1; by Brier: beta 1
  conditional P(cross | other members), top 5 of 132:
    beta 1, rho 0, weight 0                  Brier 0.1018  log 0.3508
    beta 0.75, rho 0, weight 0               Brier 0.1030  log 0.3514
    beta 1.25, rho 0, weight 0               Brier 0.1024  log 0.3550
    beta 0.5, rho 0, weight 0                Brier 0.1054  log 0.3570
    beta 1.5, rho 0, weight 0                Brier 0.1049  log 0.3636
    default: beta 1, rho 0.6, weight 0: Brier 0.1104  log 0.3868
  best by Brier: beta 1, rho 0, weight 0
  smallest effective draws: 3 of 4000
note: base rate is each event's observed crossing share, so scores measure how well the settings rank and spread members, not how well the overall rate is guessed
note: one event only: no leave-one-event-out scores; all scores are in-sample
note: the sweep reports only; it does not change any default
```
