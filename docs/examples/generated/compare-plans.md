```console
$ impsolver compare-plans examples/scenario-cabinet-a.yaml examples/scenario-cabinet-b.yaml --draws 4000

A: examples/scenario-cabinet-a.yaml
  Official A (cabinet_secretary) on shorthand-119: P(removal)=0.2802
  Official A: P(removal) alone 0.2802
    R prior                       -0.05 0.2137               +0.05 0.3475  swing 0.1337
    D prior                       -0.05 0.2352     +0.05 (clipped) 0.3200  swing 0.0848
    rho                         rho 0.4 0.3020             rho 0.8 0.2347  swing 0.0673
    I prior                       -0.05 0.2787               +0.05 0.2818  swing 0.0030

B: examples/scenario-cabinet-b.yaml
  Official B (cabinet_secretary) on shorthand-119: P(removal)=0.1648
  Official B: P(removal) alone 0.1648
    R prior                       -0.05 0.1030               +0.05 0.2223  swing 0.1193
    D prior                       -0.05 0.1305     +0.05 (clipped) 0.2028  swing 0.0723
    rho                         rho 0.4 0.1608             rho 0.8 0.1368  swing 0.0240
    I prior                       -0.05 0.1643               +0.05 0.1650  swing 0.0008
```
