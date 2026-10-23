"""Nowcast do atraso de notificação. Semanas recentes ainda não fecharam."""

from __future__ import annotations

import pandas as pd
import pytest

from dengue_forecast.nowcast.delay import empirical_cdf, nowcast_cases
from dengue_forecast.viz.frames import chart_frame


def test_cdf_acumula_a_parcela_ja_notificada() -> None:
    counts = pd.DataFrame({"delay_weeks": [0, 1, 2], "n": [1, 1, 2]})
    cdf = empirical_cdf(counts)
    assert cdf.loc[0] == pytest.approx(0.25)
    assert cdf.loc[1] == pytest.approx(0.5)
    assert cdf.loc[2] == pytest.approx(1.0)


def test_semana_recente_sobe_e_semana_fechada_fica() -> None:
    cdf = empirical_cdf(pd.DataFrame({"delay_weeks": [0, 1], "n": [1, 1]}))
    weekly = pd.DataFrame(
        {
            "geocode": [5103403, 5103403],
            "week_start": pd.to_datetime(["2024-12-15", "2024-12-22"]),
            "casos": [10.0, 10.0],
        }
    )
    out = nowcast_cases(weekly, cdf, as_of=pd.Timestamp("2024-12-22"))
    recent = out.loc[out["week_start"] == "2024-12-22", "casos_nowcast"].iloc[0]
    older = out.loc[out["week_start"] == "2024-12-15", "casos_nowcast"].iloc[0]
    assert recent == pytest.approx(20.0)
    assert older == pytest.approx(10.0)
    assert out.loc[out["week_start"] == "2024-12-22", "fracao_notificada"].iloc[0] == pytest.approx(
        0.5
    )


def test_semana_fechada_ha_muito_tempo_nao_sobe() -> None:
    cdf = empirical_cdf(pd.DataFrame({"delay_weeks": [0, 1, 2, 3, 4], "n": [40, 30, 15, 10, 5]}))
    weekly = pd.DataFrame(
        {
            "geocode": [5103403],
            "week_start": pd.to_datetime(["2024-12-22"]),
            "casos": [51.0],
        }
    )
    out = nowcast_cases(weekly, cdf, as_of=pd.Timestamp("2026-10-22"))
    assert out["fracao_notificada"].iloc[0] == pytest.approx(1.0)
    assert out["casos_nowcast"].iloc[0] == pytest.approx(51.0)


def test_fracao_minima_limita_a_inflacao() -> None:
    cdf = empirical_cdf(pd.DataFrame({"delay_weeks": [0, 8], "n": [1, 19]}))
    weekly = pd.DataFrame(
        {
            "geocode": [5103403],
            "week_start": pd.to_datetime(["2024-12-22"]),
            "casos": [10.0],
        }
    )
    out = nowcast_cases(weekly, cdf, as_of=pd.Timestamp("2024-12-22"), min_fraction=0.25)
    assert out["casos_nowcast"].iloc[0] == pytest.approx(40.0)


def test_grafico_mostra_nowcast_na_semana_observada() -> None:
    history = pd.DataFrame(
        {
            "geocode": [5103403],
            "week_start": pd.to_datetime(["2024-12-22"]),
            "casos": [10.0],
        }
    )
    nowcast = pd.DataFrame(
        {
            "geocode": [5103403],
            "week_start": pd.to_datetime(["2024-12-22"]),
            "casos": [10.0],
            "casos_nowcast": [18.0],
        }
    )
    empty = pd.DataFrame(columns=["geocode", "horizon", "target_week", "y_pred", "model"])
    chart = chart_frame(history, empty, empty, geocode=5103403, horizon=4, nowcast=nowcast)
    assert set(chart["serie"]) == {"observado", "nowcast"}
    assert chart.loc[chart["serie"] == "nowcast", "valor"].iloc[0] == pytest.approx(18.0)
