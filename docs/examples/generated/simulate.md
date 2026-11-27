```console
$ impsolver simulate examples/scenario-example.yaml --draws 20000
Example Official: 20000 draws, rho=0.6, seed=7, aligned=False

Article I, path A: P(complete)=0.0241 (MC s.e. 0.0011)
  H1   reached 1.0000  pass|reached 0.5756  PRO mean 236.2 [p5 173, p50 220, p95 350]
  H2   reached 0.5756  pass|reached 0.7051  PRO mean 220.9 [p5 165, p50 214, p95 300]
  S1   reached 0.4058  pass|reached 0.2758  PRO mean 48.8 [p5 36, p50 47, p95 68]
  S2   reached 0.1119  pass|reached 0.2154  PRO mean 48.8 [p5 36, p50 47, p95 68]
  S3   reached 0.0241  pass|reached 1.0000  PRO mean 48.8 [p5 36, p50 47, p95 68]
```
