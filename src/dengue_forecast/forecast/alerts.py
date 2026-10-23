"""Alerta local a partir da incidência prevista e do histórico do município."""

from __future__ import annotations

import pandas as pd


def classify_alert(
    pred_incidencia: float,
    history_incidencia: pd.Series,
) -> tuple[str, float, float]:
    """Verde abaixo da mediana, amarelo até o p90, vermelho acima.

    Os cortes são do próprio município, na janela já observada. Não são os
    limiares do boletim da SES.
    """
    history = history_incidencia.dropna()
    if history.empty or pred_incidencia != pred_incidencia:
        return "sem_dado", float("nan"), float("nan")
    p50 = float(history.quantile(0.5))
    p90 = float(history.quantile(0.9))
    return classify_thresholds(pred_incidencia, p50, p90), p50, p90


def classify_thresholds(pred_incidencia: float, p50: float, p90: float) -> str:
    """Aplica os cortes históricos já calculados para um município."""
    if any(pd.isna(value) for value in (pred_incidencia, p50, p90)):
        return "sem_dado"
    if pred_incidencia > p90:
        return "vermelho"
    if pred_incidencia == p50 == p90:
        return "verde"
    if pred_incidencia >= p50:
        return "amarelo"
    return "verde"


def build_alerts(forward: pd.DataFrame, features: pd.DataFrame) -> pd.DataFrame:
    """Um alerta por município, horizonte e modelo, na última origem."""
    if forward.empty:
        return pd.DataFrame()
    rows: list[dict[str, object]] = []
    for row in forward.itertuples(index=False):
        history = features[
            (features["geocode"] == row.geocode) & (features["week_start"] <= row.origin_week)
        ]
        pred_inc = float(row.y_pred) / int(row.populacao_2022) * 100_000
        level, p50, p90 = classify_alert(pred_inc, history["incidencia_100k"])
        rows.append(
            {
                "geocode": int(row.geocode),
                "municipio_nome": row.municipio_nome,
                "origin_week": row.origin_week,
                "target_week": row.target_week,
                "horizon": int(row.horizon),
                "model": row.model,
                "pred_casos": float(row.y_pred),
                "pred_incidencia_100k": pred_inc,
                "alerta": level,
                "p50_incidencia": p50,
                "p90_incidencia": p90,
                "populacao_2022": int(row.populacao_2022),
            }
        )
    return pd.DataFrame(rows)


def validate_alerts(backtest: pd.DataFrame, features: pd.DataFrame) -> pd.DataFrame:
    """Mede retrospectivamente a faixa vermelha, com cortes disponíveis na origem."""
    columns = ["horizon", "n", "red_precision", "red_recall", "predicted_red", "observed_red"]
    if backtest.empty:
        return pd.DataFrame(columns=columns)
    evaluated = backtest[(backtest["model"] == "lightgbm") & backtest["y_pred"].notna()]
    if evaluated.empty:
        return pd.DataFrame(columns=columns)

    rows: list[dict[str, object]] = []
    for geocode, city in evaluated.groupby("geocode"):
        history = features[features["geocode"] == geocode].sort_values("week_start")
        for origin, group in city.groupby("origin_week"):
            past = history[history["week_start"] <= origin]["incidencia_100k"]
            for prediction in group.itertuples(index=False):
                population = int(prediction.populacao_2022)
                if population <= 0:
                    continue
                predicted = float(prediction.y_pred) / population * 100_000
                observed = float(prediction.y_true) / population * 100_000
                pred_level = classify_alert(predicted, past)[0]
                true_level = classify_alert(observed, past)[0]
                if "sem_dado" in (pred_level, true_level):
                    continue
                rows.append(
                    {
                        "horizon": int(prediction.horizon),
                        "predicted_red": pred_level == "vermelho",
                        "observed_red": true_level == "vermelho",
                    }
                )
    if not rows:
        return pd.DataFrame(columns=columns)
    detail = pd.DataFrame(rows)
    summaries = []
    for horizon, group in detail.groupby("horizon"):
        predicted_red = int(group["predicted_red"].sum())
        observed_red = int(group["observed_red"].sum())
        true_positive = int((group["predicted_red"] & group["observed_red"]).sum())
        summaries.append(
            {
                "horizon": int(horizon),
                "n": len(group),
                "red_precision": true_positive / predicted_red if predicted_red else float("nan"),
                "red_recall": true_positive / observed_red if observed_red else float("nan"),
                "predicted_red": predicted_red,
                "observed_red": observed_red,
            }
        )
    return pd.DataFrame(summaries, columns=columns)
