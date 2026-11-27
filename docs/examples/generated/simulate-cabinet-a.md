```console
$ impsolver simulate examples/scenario-cabinet-a.yaml --draws 20000
Official A: 20000 draws, rho=0.6, seed=21, aligned=False

Article I, path A: P(complete)=0.2634 (MC s.e. 0.0031)
  H1   reached 1.0000  pass|reached 0.8849  PRO mean 295.2 [p5 211, p50 283, p95 419]
  H2   reached 0.8849  pass|reached 0.9203  PRO mean 273.4 [p5 205, p50 253, p95 405]
  S1   reached 0.8143  pass|reached 0.8450  PRO mean 69.3 [p5 47, p50 68, p95 98]
  S2   reached 0.6881  pass|reached 0.3828  PRO mean 61.4 [p5 45, p50 56, p95 93]
  S3   reached 0.2634  pass|reached 1.0000  PRO mean 61.4 [p5 45, p50 56, p95 93]
```
