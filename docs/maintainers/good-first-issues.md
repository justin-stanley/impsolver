# Good first issues

Opened as issues on the first push with the `good first issue` label.

1. **Show the presiding officer in the HTML gate path.** `report.py` renders the S2 chip without
   saying who presides; add it from the stage's `presiding_officer`. Test: the string appears for a
   presidential scenario.
2. **`impsolver validate` for portfolio files.** Accept a portfolio YAML and check every scenario it
   references, printing warnings like the other commands.
3. **Per-chamber `BLOC<=N` caps in `flips`.** Today a cap counts both chambers together; add a
   `house:R<=5` form and keep the old form working.
4. **Week labels on short timelines.** In `timeline_svg`, label weeks when the plan spans
   less than 60 days.
5. **Docs: a worked example for `--allow-absence`.** Explain why absences are reported as procedural
   sensitivity and never as recommendations.
6. **Test the beam search directly.** Add a test that forces `exact_limit=1` on a 12-candidate
   portfolio and checks the result against exact search within a tolerance.
