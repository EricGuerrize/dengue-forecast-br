"""Features, backtest e alerta da fase 3."""

from __future__ import annotations

import duckdb
import pandas as pd

from dengue_forecast.forecast.alerts import classify_alert
from dengue_forecast.forecast.backtest import seasonal_naive, split_origin
from dengue_forecast.forecast.features import build_features
from dengue_forecast.forecast.run import run_forecast
from dengue_forecast.forecast.storage import active_dir
from dengue_forecast.viz.frames import chart_frame


def _panel(n: int = 40, geocodes: tuple[int, ...] = (5103403, 5107602)) -> pd.DataFrame:
    weeks = pd.date_range("2022-01-02", periods=n, freq="7D")
    frames = []
    for offset, geocode in enumerate(geocodes):
        casos = pd.Series(range(offset * 100, offset * 100 + n), dtype=float)
        frames.append(
            pd.DataFrame(
                {
                    "geocode": geocode,
                    "municipio_nome": "Cuiabá" if geocode == 5103403 else "Rondonópolis",
                    "uf": "MT",
                    "week_start": weeks,
                    "casos": casos,
                    "populacao_2022": 100_000,
                    "incidencia_100k": casos,
                    "precip_mm": 2.0,
                    "temp_mean_c": 26.0,
                    "humidity_mean_pct": 70.0,
                }
            )
        )
    return pd.concat(frames, ignore_index=True)


def test_lags_nao_cruzam_municipio_e_alvo_e_o_futuro() -> None:
    gold = _panel()
    feats = build_features(gold, horizons=(4,))
    cuiaba = feats[feats["geocode"] == 5103403].sort_values("week_start").reset_index(drop=True)
    assert cuiaba.loc[10, "casos_atual"] == 10
    assert cuiaba.loc[10, "casos_lag_1"] == 9
    assert cuiaba.loc[10, "target_h4"] == 14
    assert pd.isna(cuiaba.loc[0, "casos_lag_1"])
    assert pd.isna(cuiaba.loc[len(cuiaba) - 1, "target_h4"])

    rondo = feats[feats["geocode"] == 5107602].sort_values("week_start").reset_index(drop=True)
    assert pd.isna(rondo.loc[0, "casos_lag_1"])
    assert rondo.loc[1, "casos_lag_1"] == 100


def test_sazonal_le_a_semana_do_ciclo_anterior() -> None:
    casos = pd.Series(range(80), dtype=float)
    assert seasonal_naive(casos, horizon=4, season=52) == 31


def test_split_origin_nao_treina_com_alvo_futuro() -> None:
    feats = build_features(_panel(n=30, geocodes=(5103403,)), horizons=(4,))
    origin = pd.Timestamp("2022-01-02") + pd.Timedelta(days=7 * 20)
    train, pred = split_origin(feats, origin, horizon=4)
    assert train["target_week_h4"].max() <= origin
    assert (pred["week_start"] == origin).all()
    assert pred["casos_atual"].iloc[0] != pred["target_h4"].iloc[0]


def test_alerta_usa_mediana_e_p90_do_municipio() -> None:
    history = pd.Series(range(1, 11), dtype=float)
    assert classify_alert(5, history)[0] == "verde"
    assert classify_alert(6, history)[0] == "amarelo"
    assert classify_alert(10, history)[0] == "vermelho"


def test_run_forecast_grava_parquet(tmp_settings) -> None:
    gold = _panel(n=36, geocodes=(5103403,))
    con = duckdb.connect(str(tmp_settings.warehouse))
    con.execute("CREATE SCHEMA gold")
    con.register("gold_df", gold)
    con.execute("CREATE TABLE gold.municipio_semana AS SELECT * FROM gold_df")
    con.close()

    summary = run_forecast(
        tmp_settings,
        horizons=(4,),
        season=8,
        min_train_weeks=12,
        step_weeks=8,
        n_estimators=20,
        sarima_max_origins=1,
    )
    assert summary["municipios"] == 1
    output = active_dir(tmp_settings.forecast)
    assert (output / "backtest.parquet").exists()
    assert (output / "alerts.parquet").exists()

    backtest = pd.read_parquet(output / "backtest.parquet")
    lgbm = backtest[backtest["model"] == "lightgbm"]
    assert not lgbm.empty
    assert (lgbm["y_pred"] >= 0).all()
    assert (lgbm["target_week"] - lgbm["origin_week"]).dt.days.eq(28).all()

    alerts = pd.read_parquet(output / "alerts.parquet")
    assert set(alerts["alerta"]) <= {"verde", "amarelo", "vermelho", "sem_dado"}


def test_grafico_alinha_previsao_na_semana_alvo() -> None:
    history = _panel(n=8, geocodes=(5103403,))
    origin = history["week_start"].iloc[3]
    target = origin + pd.Timedelta(days=28)
    backtest = pd.DataFrame(
        {
            "geocode": [5103403],
            "target_week": [target],
            "horizon": [4],
            "model": ["lightgbm"],
            "y_pred": [12.0],
        }
    )
    forward = backtest.iloc[0:0].copy()
    chart = chart_frame(history, backtest, forward, geocode=5103403, horizon=4)
    point = chart[(chart["serie"] == "lightgbm")].iloc[0]
    assert point["week_start"] == target
    assert point["valor"] == 12
