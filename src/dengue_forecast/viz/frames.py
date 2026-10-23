"""Séries longas para o gráfico da tela, sem depender do Streamlit."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from dengue_forecast.forecast.storage import DISPLAY_FILES, active_dir

ALERT_COLORS = {
    "verde": [46, 125, 50],
    "amarelo": [249, 168, 37],
    "vermelho": [198, 40, 40],
    "sem_dado": [120, 113, 108],
}


def load_outputs(forecast_dir: Path) -> dict[str, pd.DataFrame]:
    source = active_dir(forecast_dir)
    missing = [name for name in DISPLAY_FILES if not (source / f"{name}.parquet").exists()]
    if missing:
        raise FileNotFoundError(
            f"Arquivos de previsão ausentes ({', '.join(missing)}). Rode `dfc forecast`."
        )
    return {name: pd.read_parquet(source / f"{name}.parquet") for name in DISPLAY_FILES}


def chart_frame(
    history: pd.DataFrame,
    backtest: pd.DataFrame,
    forward: pd.DataFrame,
    *,
    geocode: int,
    horizon: int,
    nowcast: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Observado, nowcast e previsões no mesmo eixo de semana."""
    hist = history[history["geocode"] == geocode][["week_start", "casos"]].copy()
    hist["serie"] = "observado"
    hist = hist.rename(columns={"casos": "valor"})

    pieces = [hist]
    if nowcast is not None and not nowcast.empty:
        corrected = nowcast[nowcast["geocode"] == geocode].copy()
        corrected = corrected[corrected["casos_nowcast"] > corrected["casos"] * 1.01]
        if not corrected.empty:
            corrected["serie"] = "nowcast"
            corrected = corrected.rename(columns={"casos_nowcast": "valor"})
            pieces.append(corrected[["week_start", "serie", "valor"]])
    for source in (backtest, forward):
        part = source[(source["geocode"] == geocode) & (source["horizon"] == horizon)].copy()
        if part.empty:
            continue
        part = part.rename(columns={"target_week": "week_start", "y_pred": "valor"})
        part["serie"] = part["model"]
        pieces.append(part[["week_start", "serie", "valor"]])

    out = pd.concat(pieces, ignore_index=True)
    out["week_start"] = pd.to_datetime(out["week_start"])
    return out.dropna(subset=["valor"]).sort_values(["week_start", "serie"]).reset_index(drop=True)
