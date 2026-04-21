.PHONY: install lint format test run run-http inspect clean

PY ?= .venv/bin/python
PIP ?= .venv/bin/pip
RUFF ?= .venv/bin/ruff
PYTEST ?= .venv/bin/pytest

install:
	python3 -m venv .venv
	$(PIP) install -U pip
	$(PIP) install -e ".[dev]"

lint:
	$(RUFF) check samanage_mcp tests

format:
	$(RUFF) format samanage_mcp tests
	$(RUFF) check --fix samanage_mcp tests

test:
	$(PYTEST) -q

run:
	.venv/bin/samanage-mcp

run-http:
	.venv/bin/samanage-mcp --http --host 127.0.0.1 --port 8765

inspect:
	npx -y @modelcontextprotocol/inspector .venv/bin/samanage-mcp

clean:
	rm -rf .venv .pytest_cache .ruff_cache **/__pycache__ *.egg-info build dist
