"""Features defasadas no grão município × semana, sem usar o futuro."""

from __future__ import annotations

import pandas as pd

FEATURE_COLUMNS = [
    "casos_atual",
    "casos_lag_1",
    "casos_lag_2",
    "casos_lag_4",
    "casos_lag_8",
    "casos_lag_52",
    "incidencia_atual",
    "incidencia_lag_1",
    "incidencia_lag_4",
    "incidencia_lag_8",
    "precip_atual",
    "precip_lag_1",
    "precip_lag_4",
    "precip_lag_8",
    "temp_atual",
    "temp_lag_1",
    "temp_lag_4",
    "humidity_lag_1",
    "epiweek",
    "month",
]

HORIZONS = (4, 8)


def build_features(gold: pd.DataFrame, *, horizons: tuple[int, ...] = HORIZONS) -> pd.DataFrame:
    """Uma linha por município e semana, com lags e alvos h semanas à frente.

    O alvo da linha da semana `t` é o número de casos em `t+h`. As colunas
    `*_atual` e `*_lag_*` usam a semana `t` e as anteriores. O caso de `t+h`
    não entra em nenhuma feature.
    """
    need = {
        "geocode",
        "municipio_nome",
        "week_start",
        "casos",
        "populacao_2022",
        "incidencia_100k",
        "precip_mm",
        "temp_mean_c",
        "humidity_mean_pct",
    }
    missing = need - set(gold.columns)
    if missing:
        raise ValueError(f"Gold sem colunas: {sorted(missing)}")

    parts: list[pd.DataFrame] = []
    frame = gold.copy()
    frame["week_start"] = pd.to_datetime(frame["week_start"])
    frame = frame.sort_values(["geocode", "week_start"])

    for _, grp in frame.groupby("geocode", sort=False):
        g = grp.copy()
        g["epiweek"] = g["week_start"].dt.isocalendar().week.astype(int)
        g["month"] = g["week_start"].dt.month.astype(int)
        g["casos_atual"] = g["casos"]
        g["incidencia_atual"] = g["incidencia_100k"]
        g["precip_atual"] = g["precip_mm"]
        g["temp_atual"] = g["temp_mean_c"]
        for lag in (1, 2, 4, 8, 52):
            g[f"casos_lag_{lag}"] = g["casos"].shift(lag)
        for lag in (1, 4, 8):
            g[f"incidencia_lag_{lag}"] = g["incidencia_100k"].shift(lag)
            g[f"precip_lag_{lag}"] = g["precip_mm"].shift(lag)
        for lag in (1, 4):
            g[f"temp_lag_{lag}"] = g["temp_mean_c"].shift(lag)
        g["humidity_lag_1"] = g["humidity_mean_pct"].shift(1)
        for horizon in horizons:
            g[f"target_h{horizon}"] = g["casos"].shift(-horizon)
            g[f"target_week_h{horizon}"] = g["week_start"] + pd.to_timedelta(horizon * 7, unit="D")
        parts.append(g)

    out = pd.concat(parts, ignore_index=True)
    return out
