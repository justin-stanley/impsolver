```console
$ impsolver evaluate examples/scenario-example.yaml
Example Official (cabinet_secretary) on shorthand-119; cutoffs 0.1/0.9

Article I, path A: FAIL, ends at H2; binding gate H2
  gate  label                              pro min pro max  need verdict
  H1    table/refer privileged resolution      214     433   217 CONTESTED
  H2    adopt article                          214     214   217 FAIL
  S1    dismiss/point of order/table            47      47    50 FAIL
  S2    conviction                              47      47    67 FAIL (presiding: president_pro_tempore_or_vp)
  S3    disqualification                        47      47    51 FAIL
  controlling coalition at binding gate (non-PRO members): R 219
```
