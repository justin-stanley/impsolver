```console
$ impsolver portfolio examples/portfolio-example.yaml

Plan 1: E[removals]=1.377  order official-f > official-c > official-a > official-b
  official-f       House 2027-01-04..2027-02-05  trial 2027-02-06..2027-02-19  p0=0.450 p=0.450
  official-c       House 2027-01-04..2027-01-29  trial 2027-02-20..2027-02-22  p0=0.600 p=0.576
  official-a       House 2027-01-30..2027-03-26  trial 2027-03-27..2027-04-24  p0=0.279 p=0.240
  official-b       House 2027-02-06..2027-03-19  trial 2027-04-25..2027-05-12  p0=0.145 p=0.111

Plan 2: E[removals]=1.372  order official-f > official-a > official-c > official-b
  official-f       House 2027-01-04..2027-02-05  trial 2027-02-06..2027-02-19  p0=0.450 p=0.450
  official-a       House 2027-01-04..2027-02-26  trial 2027-02-27..2027-03-27  p0=0.279 p=0.259
  official-c       House 2027-02-06..2027-03-05  trial 2027-03-28..2027-03-30  p0=0.600 p=0.551
  official-b       House 2027-02-27..2027-04-09  trial 2027-04-10..2027-04-27  p0=0.145 p=0.111

Plan 3: E[removals]=1.370  order official-f > official-c > official-b > official-a
  official-f       House 2027-01-04..2027-02-05  trial 2027-02-06..2027-02-19  p0=0.450 p=0.450
  official-c       House 2027-01-04..2027-01-29  trial 2027-02-20..2027-02-22  p0=0.600 p=0.576
  official-b       House 2027-01-30..2027-03-12  trial 2027-03-13..2027-03-30  p0=0.145 p=0.122
  official-a       House 2027-02-06..2027-04-02  trial 2027-04-03..2027-05-01  p0=0.279 p=0.222
dropped official-e: LOW_P (P=0.020 < p_floor 0.05)
dropped official-d: EXCLUDED (excluded by official-c)

Sensitivity
  fatigue delta -0.2   best 1.754 base 1.698 regret 0.056
  fatigue delta +0.0   best 1.473 base 1.473 regret 0.000
  fatigue delta +0.2   best 1.292 base 1.292 regret 0.000
  fatigue delta +0.5   best 1.092 base 1.087 regret 0.005
  durations x0.75      best 1.377 base 1.377 regret 0.000
  durations x1.25      best 1.377 base 1.377 regret 0.000

With succession: official-f > official-c > official-a > official-b E=1.377

Removals (joint_monte_carlo): mean 1.364, sd 0.982 (independent sd 0.877)
  P(0)=0.185  P(1)=0.415  P(2)=0.280  P(3)=0.088  P(4)=0.031
  note: fixed-p candidates drawn independently: official-c, official-f
  note: one shared party-swing stream across scenario candidates, plus member noise
```
