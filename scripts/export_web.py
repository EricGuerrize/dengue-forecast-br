"""Exporta um recorte agregado para o painel estático da Vercel."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from dengue_forecast.config import get_settings
from dengue_forecast.forecast.alerts import classify_thresholds, validate_alerts
from dengue_forecast.forecast.storage import active_dir
from dengue_forecast.viz.coverage import complete_city

ROOT = Path(__file__).resolve().parents[1]
DESTINATION = ROOT / "public" / "data" / "dashboard.json"


def _number(value: object, digits: int = 1) -> float | None:
    return None if pd.isna(value) else round(float(value), digits)


def build_snapshot(forecast_dir: Path) -> dict[str, object]:
    source = active_dir(forecast_dir)
    history = pd.read_parquet(source / "history.parquet")
    forward = pd.read_parquet(source / "forward.parquet")
    alerts = pd.read_parquet(source / "alerts.parquet")
    metrics = pd.read_parquet(source / "metrics.parquet")
    nowcast_path = source / "nowcast.parquet"
    nowcast = pd.read_parquet(nowcast_path) if nowcast_path.exists() else None
    validation_path = source / "alert_validation.parquet"
    if validation_path.exists():
        validation = pd.read_parquet(validation_path)
    else:
        backtest = pd.read_parquet(source / "backtest.parquet")
        features = pd.read_parquet(source / "features.parquet")
        validation = validate_alerts(backtest, features)

    history["week_start"] = pd.to_datetime(history["week_start"])
    latest = history["week_start"].max()
    recent = history[history["week_start"] >= latest - pd.Timedelta(weeks=104)]
    expected_weeks = pd.date_range(latest - pd.Timedelta(weeks=104), latest, freq="7D")
    cities = []
    for geocode, city in recent.groupby("geocode"):
        city = city.sort_values("week_start")
        city_forward_all = forward[forward["geocode"] == geocode]
        city_alerts_all = alerts[alerts["geocode"] == geocode]
        city_metrics = metrics[metrics["geocode"] == geocode]
        if not complete_city(city, city_forward_all, city_alerts_all, city_metrics, expected_weeks):
            continue
        name = str(city["municipio_nome"].iloc[-1])
        estimates = {}
        for horizon in (4, 8):
            city_forward = city_forward_all[city_forward_all["horizon"] == horizon]
            city_alert = city_alerts_all[
                (city_alerts_all["horizon"] == horizon) & (city_alerts_all["model"] == "lightgbm")
            ]
            alert = city_alert.iloc[0]
            models = {str(row.model): _number(row.y_pred) for row in city_forward.itertuples()}
            # Os dois percentis já foram calculados no pipeline; aplica a regra atual.
            incidence = float(alert["pred_incidencia_100k"])
            p50 = float(alert["p50_incidencia"])
            p90 = float(alert["p90_incidencia"])
            level = classify_thresholds(incidence, p50, p90)
            estimates[str(horizon)] = {
                "target": pd.Timestamp(alert["target_week"]).date().isoformat(),
                "cases": _number(alert["pred_casos"]),
                "incidence": _number(incidence),
                "p50": _number(p50),
                "p90": _number(p90),
                "alert": level,
                "models": models,
            }
        quality = {
            str(h): [
                {
                    "model": str(row.model),
                    "n": int(row.n),
                    "mae": _number(row.mae_casos),
                    "maeIncidence": _number(row.mae_incidencia_100k, 2),
                }
                for row in city_metrics[city_metrics["horizon"] == h].itertuples()
            ]
            for h in (4, 8)
        }
        last_nowcast = None
        if nowcast is not None:
            matching = nowcast[
                (nowcast["geocode"] == geocode)
                & (pd.to_datetime(nowcast["week_start"]) == city["week_start"].iloc[-1])
            ]
            if not matching.empty:
                corrected = float(matching["casos_nowcast"].iloc[0])
                observed = float(city["casos"].iloc[-1])
                if corrected > observed * 1.01:
                    last_nowcast = _number(corrected)
        cities.append(
            {
                "id": int(geocode),
                "name": name,
                "history": [
                    [row.week_start.date().isoformat(), _number(row.casos)]
                    for row in city.itertuples()
                ],
                "nowcast": last_nowcast,
                "forecast": estimates,
                "quality": quality,
            }
        )
    return {
        "generatedAt": datetime.now(UTC).isoformat(),
        "lastWeek": latest.date().isoformat(),
        "cities": sorted(cities, key=lambda city: city["name"]),
        "validation": [
            {
                "horizon": int(row.horizon),
                "n": int(row.n),
                "precision": _number(row.red_precision, 3),
                "recall": _number(row.red_recall, 3),
                "predictedRed": int(row.predicted_red),
                "observedRed": int(row.observed_red),
            }
            for row in validation.itertuples()
        ],
    }


def main() -> None:
    snapshot = build_snapshot(get_settings().forecast)
    DESTINATION.parent.mkdir(parents=True, exist_ok=True)
    DESTINATION.write_text(
        json.dumps(snapshot, ensure_ascii=False, separators=(",", ":")), encoding="utf-8"
    )
    print(f"Exportados {len(snapshot['cities'])} municípios para {DESTINATION}")


if __name__ == "__main__":
    main()
