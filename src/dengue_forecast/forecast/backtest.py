"""Backtest temporal: sazonal, SARIMA e LightGBM."""

from __future__ import annotations

import warnings

import pandas as pd

from dengue_forecast.forecast.features import FEATURE_COLUMNS

MODELS = ("sazonal", "sarima", "lightgbm")


def seasonal_naive(casos: pd.Series, *, horizon: int, season: int) -> float:
    """Casos da mesma semana do ciclo anterior.

    `casos` termina na semana de origem. O alvo está `horizon` passos à frente.
    A leitura cai `season` passos antes desse alvo, e só vale se esse ponto
    já faz parte da história.
    """
    idx = len(casos) - 1 + horizon - season
    if idx < 0 or idx >= len(casos):
        return float("nan")
    return float(casos.iloc[idx])


def sarima_forecast(casos: pd.Series, *, horizon: int, season: int) -> float:
    """Previsão SARIMA de `horizon` passos. NaN se a série for curta ou o ajuste falhar."""
    path = sarima_path(casos, horizon=horizon, season=season)
    if path is None:
        return float("nan")
    return float(path[horizon - 1])


def sarima_path(casos: pd.Series, *, horizon: int, season: int) -> pd.Series | None:
    """Caminho de previsão com 1 a `horizon` passos, ou None se não couber."""
    if len(casos) < season * 2 or horizon < 1:
        return None
    try:
        from statsmodels.tsa.statespace.sarimax import SARIMAX
    except ImportError:
        return None

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        try:
            model = SARIMAX(
                casos.astype(float).to_numpy(),
                order=(1, 0, 0),
                seasonal_order=(0, 1, 0, season),
                enforce_stationarity=False,
                enforce_invertibility=False,
            )
            fit = model.fit(disp=False, maxiter=25, method="lbfgs")
            forecast = fit.forecast(horizon)
        except Exception:  # noqa: BLE001 — série curta ou não convergente
            return None
    values = pd.Series(forecast, dtype=float).clip(lower=0)
    if values.isna().any():
        return None
    return values


def split_origin(
    features: pd.DataFrame,
    origin: pd.Timestamp,
    *,
    horizon: int,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Treino só com alvos já observados até a origem; previsão é a linha da origem."""
    target_week = f"target_week_h{horizon}"
    target = f"target_h{horizon}"
    train = features[(features[target_week] <= origin) & features[target].notna()].copy()
    pred = features[features["week_start"] == origin].copy()
    return train, pred


def _usable_features(train: pd.DataFrame) -> list[str]:
    return [col for col in FEATURE_COLUMNS if col in train.columns and train[col].notna().any()]


def _lgbm_predict(
    train: pd.DataFrame,
    pred: pd.DataFrame,
    *,
    horizon: int,
    n_estimators: int,
) -> pd.Series:
    import lightgbm as lgb

    cols = _usable_features(train)
    if not cols or train.empty or pred.empty:
        return pd.Series([float("nan")] * len(pred), index=pred.index)
    dataset = lgb.Dataset(
        train[cols],
        label=train[f"target_h{horizon}"],
        free_raw_data=False,
    )
    booster = lgb.train(
        {
            "objective": "regression",
            "learning_rate": 0.08,
            "num_leaves": 15,
            "min_data_in_leaf": 5,
            "verbose": -1,
            "seed": 7,
        },
        dataset,
        num_boost_round=n_estimators,
    )
    values = booster.predict(pred[cols])
    return pd.Series(values, index=pred.index).clip(lower=0)


def backtest_models(
    features: pd.DataFrame,
    *,
    horizons: tuple[int, ...] = (4, 8),
    season: int = 52,
    min_train_weeks: int = 52,
    step_weeks: int = 4,
    n_estimators: int = 80,
    sarima_max_origins: int = 4,
) -> pd.DataFrame:
    """Walk-forward. Cada origem prevê só com informação até aquela semana."""
    rows: list[dict[str, object]] = []
    weeks = sorted(pd.to_datetime(features["week_start"].unique()))
    if len(weeks) <= min_train_weeks:
        return pd.DataFrame(rows)

    origins = list(weeks[min_train_weeks::step_weeks])
    sarima_origins = set(origins[-sarima_max_origins:]) if sarima_max_origins else set()

    for horizon in horizons:
        for origin in origins:
            train, pred = split_origin(features, origin, horizon=horizon)
            if pred.empty:
                continue
            pred = pred[pred[f"target_h{horizon}"].notna()]
            if pred.empty:
                continue
            lgbm_pred = _lgbm_predict(train, pred, horizon=horizon, n_estimators=n_estimators)
            sarima_done: dict[int, pd.Series | None] = {}
            for idx, row in pred.iterrows():
                history = features[
                    (features["geocode"] == row["geocode"]) & (features["week_start"] <= origin)
                ].sort_values("week_start")
                casos = history["casos"].reset_index(drop=True)
                seasonal = seasonal_naive(casos, horizon=horizon, season=season)
                geocode = int(row["geocode"])
                if origin in sarima_origins:
                    if geocode not in sarima_done:
                        sarima_done[geocode] = sarima_path(casos, horizon=horizon, season=season)
                    path = sarima_done[geocode]
                    sarima = float("nan") if path is None else float(path.iloc[horizon - 1])
                else:
                    sarima = float("nan")
                base = {
                    "geocode": int(row["geocode"]),
                    "municipio_nome": row["municipio_nome"],
                    "origin_week": origin,
                    "target_week": row[f"target_week_h{horizon}"],
                    "horizon": horizon,
                    "y_true": float(row[f"target_h{horizon}"]),
                    "populacao_2022": int(row["populacao_2022"]),
                }
                preds = {
                    "lightgbm": float(lgbm_pred.loc[idx]),
                    "sazonal": seasonal,
                    "sarima": sarima,
                }
                for model, y_pred in preds.items():
                    rows.append({**base, "model": model, "y_pred": y_pred})
    return pd.DataFrame(rows)


def forward_forecast(
    features: pd.DataFrame,
    *,
    horizons: tuple[int, ...] = (4, 8),
    season: int = 52,
    n_estimators: int = 80,
) -> pd.DataFrame:
    """Previsão a partir da última semana observada, ainda sem casos realizados."""
    rows: list[dict[str, object]] = []
    last_origin = pd.to_datetime(features["week_start"]).max()
    for horizon in horizons:
        train, pred = split_origin(features, last_origin, horizon=horizon)
        if pred.empty:
            continue
        lgbm_pred = _lgbm_predict(train, pred, horizon=horizon, n_estimators=n_estimators)
        for idx, row in pred.iterrows():
            history = features[
                (features["geocode"] == row["geocode"]) & (features["week_start"] <= last_origin)
            ].sort_values("week_start")
            casos = history["casos"].reset_index(drop=True)
            preds = {
                "lightgbm": float(lgbm_pred.loc[idx]),
                "sazonal": seasonal_naive(casos, horizon=horizon, season=season),
                "sarima": sarima_forecast(casos, horizon=horizon, season=season),
            }
            for model, y_pred in preds.items():
                rows.append(
                    {
                        "geocode": int(row["geocode"]),
                        "municipio_nome": row["municipio_nome"],
                        "origin_week": last_origin,
                        "target_week": row[f"target_week_h{horizon}"],
                        "horizon": horizon,
                        "y_pred": y_pred,
                        "populacao_2022": int(row["populacao_2022"]),
                        "model": model,
                    }
                )
    return pd.DataFrame(rows)


def metrics_table(backtest: pd.DataFrame) -> pd.DataFrame:
    """MAE de casos e de incidência por 100 mil habitantes."""
    if backtest.empty:
        return pd.DataFrame(
            columns=[
                "geocode",
                "municipio_nome",
                "model",
                "horizon",
                "n",
                "mae_casos",
                "mae_incidencia_100k",
            ]
        )
    df = backtest.dropna(subset=["y_pred"]).copy()
    df["inc_true"] = df["y_true"] / df["populacao_2022"] * 100_000
    df["inc_pred"] = df["y_pred"] / df["populacao_2022"] * 100_000
    df["abs_casos"] = (df["y_true"] - df["y_pred"]).abs()
    df["abs_inc"] = (df["inc_true"] - df["inc_pred"]).abs()
    grouped = df.groupby(
        ["geocode", "municipio_nome", "model", "horizon"],
        as_index=False,
    ).agg(
        n=("abs_casos", "size"),
        mae_casos=("abs_casos", "mean"),
        mae_incidencia_100k=("abs_inc", "mean"),
    )
    return grouped.sort_values(["geocode", "horizon", "mae_casos"]).reset_index(drop=True)
