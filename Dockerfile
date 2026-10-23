FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    DFC_DATA_DIR=/app/data \
    PORT=8501 \
    DBT_SEND_ANONYMOUS_USAGE_STATS=false \
    DO_NOT_TRACK=1

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md LICENSE ./
COPY src ./src
COPY dbt ./dbt
COPY .streamlit ./.streamlit
COPY data/sample ./data/sample
COPY data/reference ./data/reference
COPY scripts/docker-entrypoint.sh /entrypoint.sh
COPY Makefile ./

RUN pip install --upgrade pip && pip install -e ".[transform,forecast,viz]" \
    && chmod +x /entrypoint.sh

EXPOSE 8501

ENTRYPOINT ["/entrypoint.sh"]
