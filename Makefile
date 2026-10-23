.PHONY: setup lint test ingest demo transform forecast nowcast refresh viz export-web clean docker-build docker-up

PYTHON ?= python3
PIP ?= $(PYTHON) -m pip

setup:
	$(PIP) install -e ".[dev,transform,forecast,viz,orchestrate]"
	pre-commit install || true

lint:
	ruff check src tests scripts/export_web.py
	ruff format --check src tests scripts/export_web.py

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

transform:
	dfc transform

forecast:
	dfc forecast

nowcast:
	dfc nowcast --sample-dir data/sample

refresh:
	dfc refresh --sample-dir data/sample

viz:
	dfc viz

export-web:
	$(PYTHON) scripts/export_web.py

clean:
	rm -rf data/bronze data/silver data/gold data/warehouse.duckdb data/artifacts data/forecast
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true

docker-build:
	docker build -t dengue-forecast-br:local .

docker-up:
	docker compose up --build
