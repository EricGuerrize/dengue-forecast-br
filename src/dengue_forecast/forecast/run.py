"""Lê o gold, roda o backtest e grava os parquets que a tela consome."""

from __future__ import annotations

import pandas as pd

from dengue_forecast.config import Settings, get_settings
from dengue_forecast.forecast.alerts import build_alerts, validate_alerts
from dengue_forecast.forecast.backtest import backtest_models, forward_forecast, metrics_table
from dengue_forecast.forecast.features import HORIZONS, build_features
from dengue_forecast.forecast.storage import publish_forecast
from dengue_forecast.logging_setup import get_logger
from dengue_forecast.warehouse import Warehouse

log = get_logger(__name__)

HISTORY_COLUMNS = [
    "geocode",
    "municipio_nome",
    "uf",
    "week_start",
    "casos",
    "incidencia_100k",
    "precip_mm",
    "temp_mean_c",
    "populacao_2022",
    "station_id",
]


def load_gold(settings: Settings) -> pd.DataFrame:
    if not settings.warehouse.exists():
        raise FileNotFoundError(
            f"Warehouse ausente ({settings.warehouse}). Rode `make demo` e `make transform`."
        )
    with Warehouse(settings.warehouse) as wh:
        found = {
            f"{schema}.{name}"
            for schema, name in wh.con.execute(
                """
                SELECT table_schema, table_name
                FROM information_schema.tables
                WHERE table_name = 'municipio_semana'
                """
            ).fetchall()
        }
        if "gold.municipio_semana" not in found:
            raise FileNotFoundError("Tabela gold.municipio_semana ausente. Rode `dfc transform`.")
        return wh.con.execute("SELECT * FROM gold.municipio_semana").df()


def run_forecast(
    settings: Settings | None = None,
    *,
    horizons: tuple[int, ...] = HORIZONS,
    season: int = 52,
    min_train_weeks: int = 52,
    step_weeks: int = 4,
    n_estimators: int = 80,
    sarima_max_origins: int = 4,
) -> dict[str, int]:
    settings = settings or get_settings()
    gold = load_gold(settings)
    features = build_features(gold, horizons=horizons)
    backtest = backtest_models(
        features,
        horizons=horizons,
        season=season,
        min_train_weeks=min_train_weeks,
        step_weeks=step_weeks,
        n_estimators=n_estimators,
        sarima_max_origins=sarima_max_origins,
    )
    forward = forward_forecast(
        features,
        horizons=horizons,
        season=season,
        n_estimators=n_estimators,
    )
    metrics = metrics_table(backtest)
    alerts = build_alerts(forward, features)
    alert_validation = validate_alerts(backtest, features)

    keep = [col for col in HISTORY_COLUMNS if col in gold.columns]
    publish_forecast(
        settings.forecast,
        {
            "history": gold[keep],
            "features": features,
            "backtest": backtest,
            "forward": forward,
            "metrics": metrics,
            "alerts": alerts,
            "alert_validation": alert_validation,
        },
    )

    summary = {
        "municipios": int(gold["geocode"].nunique()),
        "semanas": int(gold["week_start"].nunique()),
        "backtest_rows": len(backtest),
        "alertas": len(alerts),
    }
    log.info("forecast_done", **summary)
    return summary
