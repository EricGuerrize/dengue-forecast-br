FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    DFC_DATA_DIR=/app/data

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md LICENSE ./
COPY src ./src
COPY data/sample ./data/sample
COPY Makefile ./

RUN pip install --upgrade pip && pip install -e ".[dev]"

# Bind em 0.0.0.0:$PORT em fases futuras (dashboard Streamlit).
# Fase 1: demo offline gera artefatos em data/artifacts.
CMD ["dfc", "demo", "--sample-dir", "data/sample", "--output-dir", "data/artifacts"]
