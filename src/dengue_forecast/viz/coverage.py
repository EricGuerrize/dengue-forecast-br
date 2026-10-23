"""Critério de cobertura dos municípios publicados no painel web."""

from __future__ import annotations

import pandas as pd


def complete_city(
    city: pd.DataFrame,
    city_forward: pd.DataFrame,
    city_alerts: pd.DataFrame,
    city_metrics: pd.DataFrame,
    expected_weeks: pd.DatetimeIndex,
) -> bool:
    """Exige série semanal sem lacunas, população e resultados nos dois horizontes."""
    ordered = city.sort_values("week_start")
    if not pd.DatetimeIndex(ordered["week_start"]).equals(expected_weeks):
        return False
    if ordered[["casos", "populacao_2022"]].isna().any().any():
        return False
    if (ordered["populacao_2022"] <= 0).any():
        return False
    for horizon in (4, 8):
        pred = city_forward[
            (city_forward["horizon"] == horizon) & (city_forward["model"] == "lightgbm")
        ]
        alert = city_alerts[
            (city_alerts["horizon"] == horizon) & (city_alerts["model"] == "lightgbm")
        ]
        metric = city_metrics[
            (city_metrics["horizon"] == horizon) & (city_metrics["model"] == "lightgbm")
        ]
        if len(pred) != 1 or len(alert) != 1 or len(metric) != 1:
            return False
        if pd.isna(pred["y_pred"].iloc[0]) or pd.isna(alert["pred_incidencia_100k"].iloc[0]):
            return False
        if pd.isna(metric["mae_casos"].iloc[0]) or metric["n"].iloc[0] <= 0:
            return False
    return True
