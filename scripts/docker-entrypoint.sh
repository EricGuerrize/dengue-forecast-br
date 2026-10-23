#!/bin/sh
# Sobe a tela. Se o ciclo ainda não rodou neste volume, monta o sample offline antes.
set -eu

PORT="${PORT:-8501}"
export PORT

cd /app

if [ ! -f data/forecast/current.json ] && [ ! -f data/forecast/alerts.parquet ]; then
  dfc demo --sample-dir data/sample --output-dir data/artifacts
  dfc transform
  dfc forecast
fi

FORECAST_DIR="$(python -c 'from dengue_forecast.forecast.storage import active_dir; from pathlib import Path; print(active_dir(Path("data/forecast")))')"
if [ ! -f "$FORECAST_DIR/nowcast.parquet" ]; then
  dfc ingest sivep --uf MT --sample-dir data/sample
  dfc nowcast
fi

exec dfc viz --port "$PORT"
