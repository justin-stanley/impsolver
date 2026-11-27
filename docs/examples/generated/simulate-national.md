```console
$ impsolver simulate examples/scenario-cabinet-a-national.yaml --draws 20000
Official A: 20000 draws, rho=0.6, seed=21, aligned=False

Article I, path A: P(complete)=0.3251 (MC s.e. 0.0033)
  H1   reached 1.0000  pass|reached 0.8849  PRO mean 295.0 [p5 211, p50 283, p95 418]
  H2   reached 0.8849  pass|reached 0.9179  PRO mean 273.0 [p5 204, p50 253, p95 403]
  S1   reached 0.8122  pass|reached 0.9782  PRO mean 69.4 [p5 47, p50 68, p95 98]
  S2   reached 0.7945  pass|reached 0.4091  PRO mean 61.4 [p5 45, p50 56, p95 93]
  S3   reached 0.3251  pass|reached 1.0000  PRO mean 61.4 [p5 45, p50 56, p95 93]
```
