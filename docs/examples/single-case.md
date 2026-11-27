# One hypothetical case

`examples/scenario-example.yaml` describes **Example Official**, a placeholder, on a
party-shorthand chamber (219 R and 214 D in the House; 53 R, 45 D and 2 I in the Senate). Democrats
and independents lean strongly PRO, Republicans strongly CON, with a little more Republican
support for not tabling at H1.

## Bounds per gate

--8<-- "examples/generated/evaluate.md"

The case ends at H2: even with every uncertain member counted as PRO, adoption falls 3 short.

The last block lists the members nearest the threshold at the binding gate, by the supplied
probabilities: the members not counted PRO, highest p first, enough to cover the shortfall plus
five (at most 25). Every Republican here has the same party prior, so the order among them is by
id alone. The list restates the inputs; it is not a forecast and suggests no one.

## Fewest changes needed

`flips` finds the fewest stance changes that make a gate pass. Here it targets conviction alone:

--8<-- "examples/generated/flips.md"

Twenty Republican senators would have to change sides. This is arithmetic, not a forecast or a
recommendation. `--allow-absence` also considers members being absent; those results are labelled
procedural sensitivity.

## Simulation

--8<-- "examples/generated/simulate.md"

Read the table as conditional probabilities: the chance of passing each gate given that the case
got there.
