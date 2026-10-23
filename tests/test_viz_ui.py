"""Estados essenciais da interface local, quando Streamlit está instalado."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

streamlit = pytest.importorskip("streamlit")
from streamlit.testing.v1 import AppTest  # noqa: E402

APP = Path(__file__).resolve().parents[1] / "src" / "dengue_forecast" / "viz" / "app.py"


def test_tela_sem_previsao_mostra_orientacao(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("DFC_DATA_DIR", str(tmp_path))
    app = AppTest.from_file(str(APP)).run(timeout=20)
    assert not app.exception
    assert any("Arquivos de previsão ausentes" in warning.value for warning in app.warning)


def test_tela_atualiza_horizonte_e_mostra_data_dos_dados(tmp_path, monkeypatch) -> None:
    output = tmp_path / "forecast"
    output.mkdir()
    history = pd.DataFrame(
        {
            "geocode": [5103403, 5103403],
            "municipio_nome": ["Cuiabá", "Cuiabá"],
            "week_start": pd.to_datetime(["2024-01-07", "2024-01-14"]),
            "casos": [4.0, 5.0],
        }
    )
    forward = pd.DataFrame(
        {
            "geocode": [5103403, 5103403],
            "horizon": [4, 8],
            "model": ["lightgbm", "lightgbm"],
            "y_pred": [7.0, 9.0],
            "target_week": pd.to_datetime(["2024-02-11", "2024-03-10"]),
        }
    )
    alerts = pd.DataFrame(
        {
            "geocode": [5103403, 5103403],
            "horizon": [4, 8],
            "model": ["lightgbm", "lightgbm"],
            "alerta": ["amarelo", "vermelho"],
            "pred_incidencia_100k": [2.0, 4.0],
            "p50_incidencia": [1.0, 1.0],
            "p90_incidencia": [3.0, 3.0],
            "municipio_nome": ["Cuiabá", "Cuiabá"],
            "pred_casos": [7.0, 9.0],
            "target_week": pd.to_datetime(["2024-02-11", "2024-03-10"]),
        }
    )
    metrics = pd.DataFrame(
        {
            "geocode": [5103403, 5103403],
            "horizon": [4, 8],
            "model": ["lightgbm", "lightgbm"],
            "n": [3, 3],
            "mae_casos": [1.0, 2.0],
            "mae_incidencia_100k": [0.1, 0.2],
        }
    )
    backtest = forward.iloc[0:0].copy()
    for name, frame in {
        "history": history,
        "forward": forward,
        "alerts": alerts,
        "metrics": metrics,
        "backtest": backtest,
    }.items():
        frame.to_parquet(output / f"{name}.parquet", index=False)
    monkeypatch.setenv("DFC_DATA_DIR", str(tmp_path))
    app = AppTest.from_file(str(APP)).run(timeout=20)
    assert not app.exception
    assert any("não representam a situação atual" in warning.value for warning in app.warning)
    assert any(metric.label == "Casos previstos em 4 semanas" for metric in app.metric)
    app.sidebar.radio[0].set_value(8).run(timeout=20)
    assert not app.exception
    assert any(metric.label == "Casos previstos em 8 semanas" for metric in app.metric)
    assert any(metric.value == "Acima do p90" for metric in app.metric)
