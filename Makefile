.PHONY: setup lint test ingest demo clean docker-build docker-up

PYTHON ?= python3
PIP ?= $(PYTHON) -m pip

setup:
	$(PIP) install -e ".[dev]"
	pre-commit install || true

lint:
	ruff check src tests
	ruff format --check src tests

fmt:
	ruff check --fix src tests
	ruff format src tests

test:
	pytest tests -m "not integration"

test-all:
	pytest tests

ingest:
	dfc ingest --help

demo:
	dfc demo --sample-dir data/sample --output-dir data/artifacts

clean:
	rm -rf data/bronze data/silver data/gold data/warehouse.duckdb data/artifacts
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true

docker-build:
	docker build -t dengue-forecast-br:local .

docker-up:
	docker compose up --build
