## What and why

<!-- One change per pull request. Link the issue it closes. -->

## Checks

- [ ] Tests added or updated; `pytest -q`, `ruff check`, `ruff format --check` and `mypy src` pass
- [ ] No scenarios about named, real current officials (see RESPONSIBLE_USE.md)
- [ ] Data changes cite a primary source (House Clerk, House Press Gallery, senate.gov, Voteview)
- [ ] Changes to default numerical results are described here and in CHANGELOG.md
- [ ] Schemas regenerated if `model.py` changed (`impsolver schema --out schemas`)
