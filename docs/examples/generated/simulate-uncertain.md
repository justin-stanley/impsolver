```console
$ impsolver simulate examples/scenario-cabinet-a-uncertain.yaml
Official A: 2000 draws, rho=0.6, seed=21, aligned=False, 200 outer draws over uncertain priors

Article I, path A: P(complete)=0.2665 (MC s.e. 0.0113), 5-95% over priors [0.1510, 0.3906]
  H1   reached 1.0000  pass|reached 0.8873  PRO mean 295.5 [p5 211, p50 282, p95 419]
  H2   reached 0.8873  pass|reached 0.9035  PRO mean 272.0 [p5 204, p50 251, p95 403]
  S1   reached 0.8017  pass|reached 0.8338  PRO mean 69.2 [p5 46, p50 68, p95 98]
  S2   reached 0.6685  pass|reached 0.3986  PRO mean 61.6 [p5 45, p50 57, p95 94]
  S3   reached 0.2665  pass|reached 1.0000  PRO mean 61.6 [p5 45, p50 57, p95 94]
```
