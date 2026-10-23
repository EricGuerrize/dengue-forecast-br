"""Publicação atômica e validação temporal dos alertas."""

from __future__ import annotations

import pandas as pd
import pytest

from dengue_forecast.forecast.alerts import classify_thresholds, validate_alerts
from dengue_forecast.forecast.storage import FORECAST_FILES, active_dir, publish_forecast


def test_falha_na_publicacao_preserva_rodada_ativa(tmp_path, monkeypatch) -> None:
    output = tmp_path / "forecast"
    frames = {name: pd.DataFrame({"value": [1]}) for name in FORECAST_FILES}
    first = publish_forecast(output, frames)
    assert active_dir(output) == first

    original = pd.DataFrame.to_parquet

    def fail_on_alerts(self, path, *args, **kwargs):
        if str(path).endswith("alerts.parquet"):
            raise OSError("disco cheio")
        return original(self, path, *args, **kwargs)

    monkeypatch.setattr(pd.DataFrame, "to_parquet", fail_on_alerts)
    with pytest.raises(OSError, match="disco cheio"):
        publish_forecast(output, frames)
    assert active_dir(output) == first
    assert pd.read_parquet(first / "alerts.parquet")["value"].tolist() == [1]
    assert list((output / "runs").iterdir()) == [first]


def test_validacao_usa_apenas_historico_disponivel_na_origem() -> None:
    weeks = pd.date_range("2024-01-07", periods=5, freq="7D")
    features = pd.DataFrame(
        {
            "geocode": [5103403] * 5,
            "week_start": weeks,
            "incidencia_100k": [0, 0, 0, 1, 2],
        }
    )
    origin = weeks[-1]
    backtest = pd.DataFrame(
        {
            "geocode": [5103403] * 3,
            "origin_week": [origin] * 3,
            "horizon": [4] * 3,
            "model": ["lightgbm"] * 3,
            "y_pred": [3, 3, 0],
            "y_true": [3, 0, 3],
            "populacao_2022": [100_000] * 3,
        }
    )
    result = validate_alerts(backtest, features).iloc[0]
    assert result["n"] == 3
    assert result["red_precision"] == pytest.approx(0.5)
    assert result["red_recall"] == pytest.approx(0.5)
    assert classify_thresholds(0, 0, 0) == "verde"
