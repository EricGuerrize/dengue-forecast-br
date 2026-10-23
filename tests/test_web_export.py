"""Contrato do recorte público para o painel da Vercel."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from dengue_forecast.viz.coverage import complete_city


def test_snapshot_publico_tem_municipios_e_horizontes() -> None:
    path = Path(__file__).resolve().parents[1] / "public" / "data" / "dashboard.json"
    snapshot = json.loads(path.read_text(encoding="utf-8"))
    assert len(snapshot["cities"]) > 0
    assert {row["horizon"] for row in snapshot["validation"]} == {4, 8}
    assert all({"4", "8"} <= set(city["forecast"]) for city in snapshot["cities"])
    assert (
        max(point[0] for city in snapshot["cities"] for point in city["history"])
        == snapshot["lastWeek"]
    )


def test_exportador_exclui_municipio_com_semana_ausente() -> None:
    weeks = pd.date_range("2026-01-04", periods=3, freq="7D")
    city = pd.DataFrame(
        {
            "week_start": weeks,
            "casos": [1, 2, 3],
            "populacao_2022": [1000] * 3,
        }
    )
    predictions = pd.DataFrame(
        {
            "horizon": [4, 8],
            "model": ["lightgbm"] * 2,
            "y_pred": [2.0, 3.0],
        }
    )
    alerts = pd.DataFrame(
        {
            "horizon": [4, 8],
            "model": ["lightgbm"] * 2,
            "pred_incidencia_100k": [1.0, 2.0],
        }
    )
    metrics = pd.DataFrame(
        {
            "horizon": [4, 8],
            "model": ["lightgbm"] * 2,
            "mae_casos": [1.0, 1.0],
            "n": [3, 3],
        }
    )
    assert complete_city(city, predictions, alerts, metrics, weeks)
    assert not complete_city(city.iloc[:2], predictions, alerts, metrics, weeks)
    assert not complete_city(city, predictions.iloc[:1], alerts, metrics, weeks)
