.PHONY: install test lint docs demo fetch reproduce release-check

install:
	uv sync --extra dev --extra docs
	uv run pre-commit install

test:
	uv run pytest -q --cov

lint:
	uv run pre-commit run --all-files

demo:
	mkdir -p docs/demo
	uv run impsolver portfolio examples/portfolio-example.yaml --html docs/demo/index.html

docs: demo
	uv run python docs/examples/run_examples.py --check
	uv run mkdocs build --strict

fetch:
	scripts/fetch-voteview.sh 116 117 118 119

reproduce: fetch
	uv run python scripts/reproduce.py

release-check:
	uv build
	uv run pytest -q
