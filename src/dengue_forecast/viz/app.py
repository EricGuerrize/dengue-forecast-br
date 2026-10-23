"""Tela local das previsões. Os números vêm dos parquets de `dfc forecast`."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import altair as alt
import pandas as pd
import pydeck as pdk
import streamlit as st

from dengue_forecast.config import get_settings
from dengue_forecast.forecast.storage import DISPLAY_FILES, active_dir
from dengue_forecast.viz.frames import ALERT_COLORS, chart_frame, load_outputs

SERIES_COLORS = {
    "observado": "#1c1917",
    "nowcast": "#c2410c",
    "lightgbm": "#9a3412",
    "sazonal": "#0369a1",
    "sarima": "#7c3aed",
}

ALERT_LABELS = {
    "verde": "Abaixo da mediana",
    "amarelo": "Entre mediana e p90",
    "vermelho": "Acima do p90",
    "sem_dado": "Sem dados",
}


def _format_number(value: object, decimals: int = 0) -> str:
    if pd.isna(value):
        return "—"
    return f"{float(value):,.{decimals}f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _forecast_dir() -> Path:
    return get_settings().forecast


@st.cache_data(show_spinner=False)
def _load_cached(directory: str, modified: tuple[float, ...]) -> dict[str, pd.DataFrame]:
    """Recarrega os parquets quando algum arquivo de previsão muda."""
    return load_outputs(Path(directory))


def _centroids() -> pd.DataFrame:
    path = get_settings().root / "data" / "reference" / "municipio_centroide_mt.csv"
    if not path.exists():
        return pd.DataFrame(columns=["codigo_ibge", "latitude", "longitude"])
    return pd.read_csv(path)


def _optional(name: str) -> pd.DataFrame | None:
    directory = (
        active_dir(_forecast_dir()) if name in ("nowcast", "alert_validation") else _forecast_dir()
    )
    path = directory / f"{name}.parquet"
    if not path.exists():
        return None
    return pd.read_parquet(path)


def main() -> None:
    st.set_page_config(page_title="Dengue em Mato Grosso", page_icon="🦟", layout="wide")
    st.title("Dengue em Mato Grosso")
    st.caption("Casos semanais e previsões municipais de 4 ou 8 semanas")

    directory = _forecast_dir()
    required = DISPLAY_FILES
    source = active_dir(directory)
    modified = tuple(
        (source / f"{name}.parquet").stat().st_mtime
        for name in required
        if (source / f"{name}.parquet").exists()
    )
    try:
        outputs = _load_cached(str(source), modified)
    except FileNotFoundError as exc:
        st.warning(str(exc))
        st.code("dfc forecast", language="bash")
        return

    history = outputs["history"]
    backtest = outputs["backtest"]
    forward = outputs["forward"]
    metrics = outputs["metrics"]
    alerts = outputs["alerts"]
    nowcast = _optional("nowcast")
    srag = _optional("srag")
    if history.empty:
        st.info("O histórico está vazio. Execute a ingestão e a previsão novamente.")
        return
    n_cities = int(history["geocode"].nunique())
    last_available = pd.to_datetime(history["week_start"]).max()
    age_days = (date.today() - last_available.date()).days
    st.caption(
        f"Última semana disponível: **{last_available:%d/%m/%Y}** · "
        f"{n_cities} municípios no conjunto de dados"
    )
    if age_days > 14:
        st.warning(
            f"A última semana registrada foi há {age_days} dias. Estas projeções foram calculadas "
            "a partir desse recorte e não representam a situação atual."
        )

    names = history[["geocode", "municipio_nome"]].drop_duplicates().sort_values("municipio_nome")
    names["geocode"] = names["geocode"].astype(int)
    label_by_code = dict(zip(names["geocode"], names["municipio_nome"], strict=True))

    with st.sidebar:
        st.header("Explore os dados")
        choice = st.selectbox(
            "Município",
            options=list(label_by_code),
            format_func=lambda code: label_by_code[code],
            index=list(label_by_code).index(5103403) if 5103403 in label_by_code else 0,
        )
        horizon = st.radio(
            "Previsão",
            options=[4, 8],
            horizontal=True,
            format_func=lambda h: f"{h} semanas",
        )
        period = st.selectbox(
            "Histórico no gráfico",
            options=[26, 52, 104, 0],
            format_func=lambda n: "Todo o período" if n == 0 else f"Últimas {n} semanas",
            index=1,
        )
        st.caption("Os alertas comparam cada município com seu próprio histórico.")

    city_hist = history[history["geocode"] == choice].sort_values("week_start")
    city_forward = forward[
        (forward["geocode"] == choice)
        & (forward["horizon"] == horizon)
        & (forward["model"] == "lightgbm")
    ]
    city_alert = alerts[
        (alerts["geocode"] == choice)
        & (alerts["horizon"] == horizon)
        & (alerts["model"] == "lightgbm")
    ]

    last = city_hist.iloc[-1]
    pred_casos = float(city_forward["y_pred"].iloc[0]) if not city_forward.empty else float("nan")
    alert_row = city_alert.iloc[0] if not city_alert.empty else None
    nowcast_value = None
    if nowcast is not None:
        city_now = nowcast[nowcast["geocode"] == choice].copy()
        city_now["week_start"] = pd.to_datetime(city_now["week_start"])
        same_week = city_now["week_start"] == pd.to_datetime(last["week_start"])
        if same_week.any():
            nowcast_value = float(city_now.loc[same_week, "casos_nowcast"].iloc[0])

    last_week = pd.to_datetime(last["week_start"]).date()
    st.header(label_by_code[choice])
    if not city_forward.empty:
        target_week = pd.to_datetime(city_forward["target_week"].iloc[0])
        st.caption(
            f"Previsão para a semana de {target_week:%d/%m/%Y} · "
            f"última observação: {last_week:%d/%m/%Y}"
        )
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Casos na última semana", _format_number(last["casos"]), help=str(last_week))
    c2.metric(
        "Estimativa corrigida",
        _format_number(nowcast_value, 1)
        if nowcast_value is not None and nowcast_value > last["casos"] * 1.01
        else "—",
        help="Casos da última semana corrigidos pelo atraso de notificação",
    )
    c3.metric(f"Casos previstos em {horizon} semanas", _format_number(pred_casos))
    level = alert_row["alerta"] if alert_row is not None else "sem_dado"
    c4.metric("Faixa de alerta", ALERT_LABELS.get(level, "Sem dados"))

    if alert_row is not None:
        st.write(
            "Incidência prevista: "
            f"**{_format_number(alert_row['pred_incidencia_100k'], 1)}** casos por 100 mil. "
            f"Mediana histórica: {_format_number(alert_row['p50_incidencia'], 1)}; "
            f"percentil 90: {_format_number(alert_row['p90_incidencia'], 1)}. "
            "A faixa compara o município com seu próprio histórico; não é um limiar oficial da SES."
        )

    chart = chart_frame(
        history,
        backtest.iloc[0:0],
        forward,
        geocode=int(choice),
        horizon=int(horizon),
        nowcast=nowcast,
    )
    if period:
        chart = chart[chart["week_start"] >= last_available - pd.Timedelta(weeks=period)]
    if chart.empty:
        st.info("Sem pontos para este município e horizonte.")
    else:
        present = [name for name in SERIES_COLORS if name in set(chart["serie"])]
        lines = (
            alt.Chart(chart)
            .mark_line(point=alt.OverlayMarkDef(size=28))
            .encode(
                x=alt.X("week_start:T", title="Semana"),
                y=alt.Y("valor:Q", title="Casos"),
                color=alt.Color(
                    "serie:N",
                    title="Série",
                    scale=alt.Scale(
                        domain=present,
                        range=[SERIES_COLORS[name] for name in present],
                    ),
                ),
                tooltip=["week_start:T", "serie:N", alt.Tooltip("valor:Q", format=".1f")],
            )
            .properties(height=360)
        )
        boundary = (
            alt.Chart(pd.DataFrame({"week_start": [last_available]}))
            .mark_rule(color="#78716c", strokeDash=[4, 4])
            .encode(x="week_start:T")
        )
        st.altair_chart(lines + boundary, width="stretch")
        st.caption(
            "A linha tracejada marca a última observação. A estimativa corrigida aparece "
            "quando o ajuste "
            "por atraso supera 1%. Os pontos futuros são projeções dos modelos "
            "para a semana indicada."
        )

    if srag is not None:
        city_srag = srag[srag["geocode"] == choice].copy()
        if not city_srag.empty:
            city_srag["week_start"] = pd.to_datetime(city_srag["week_start"])
            latest = city_srag["week_start"].max()
            recent = city_srag[city_srag["week_start"] == latest]
            fonte = str(recent["fonte"].iloc[0]) if "fonte" in recent.columns else "opendatasus"
            st.subheader(f"SRAG na semana de {pd.Timestamp(latest).date()}")
            if fonte == "sample":
                st.caption("Contagens ilustrativas do conjunto de exemplo.")
            show_srag = recent[["virus", "casos"]].copy()
            show_srag["casos"] = show_srag["casos"].map(lambda v: f"{int(v)}")
            st.dataframe(
                show_srag.rename(columns={"virus": "Vírus", "casos": "Casos"}),
                hide_index=True,
                width="stretch",
            )

    st.subheader("Qualidade da previsão")
    st.caption(
        "Erro médio absoluto nas previsões anteriores. Quanto menor, melhor; "
        "compare também a quantidade de pontos avaliados."
    )
    city_metrics = metrics[(metrics["geocode"] == choice) & (metrics["horizon"] == horizon)]
    if city_metrics.empty:
        st.write("Ainda não há métricas para este recorte.")
    else:
        show = city_metrics[["model", "n", "mae_casos", "mae_incidencia_100k"]].copy()
        show["mae_casos"] = show["mae_casos"].map(lambda v: f"{v:.1f}")
        show["mae_incidencia_100k"] = show["mae_incidencia_100k"].map(lambda v: f"{v:.2f}")
        st.dataframe(
            show.rename(
                columns={
                    "model": "Modelo",
                    "n": "Previsões avaliadas",
                    "mae_casos": "Erro médio em casos",
                    "mae_incidencia_100k": "Erro médio por 100 mil",
                }
            ),
            hide_index=True,
            width="stretch",
        )

    st.subheader("Mapa de alertas em Mato Grosso")
    st.caption(
        f"Horizonte de {horizon} semanas · modelo LightGBM · cores relativas ao histórico local"
    )
    map_alerts = alerts[(alerts["horizon"] == horizon) & (alerts["model"] == "lightgbm")].copy()
    centroids = _centroids().rename(columns={"codigo_ibge": "geocode"})
    map_alerts = map_alerts.merge(
        centroids[["geocode", "latitude", "longitude"]],
        on="geocode",
        how="left",
    )
    map_alerts["cor"] = map_alerts["alerta"].map(ALERT_COLORS)
    map_alerts["rotulo"] = map_alerts["alerta"].map(ALERT_LABELS)
    map_alerts["casos_formatados"] = map_alerts["pred_casos"].map(_format_number)
    located = map_alerts.dropna(subset=["latitude", "longitude"])
    if not located.empty:
        st.pydeck_chart(
            pdk.Deck(
                initial_view_state=pdk.ViewState(latitude=-13.6, longitude=-56.1, zoom=5),
                layers=[
                    pdk.Layer(
                        "ScatterplotLayer",
                        located,
                        get_position="[longitude, latitude]",
                        get_fill_color="cor",
                        get_radius=28000,
                        pickable=True,
                    )
                ],
                tooltip={"text": "{municipio_nome}\n{rotulo}\n{casos_formatados} casos previstos"},
            )
        )
    show = map_alerts[
        ["municipio_nome", "rotulo", "pred_casos", "pred_incidencia_100k", "target_week"]
    ].copy()
    show["pred_casos"] = show["pred_casos"].map(lambda v: f"{v:.0f}")
    show["pred_incidencia_100k"] = show["pred_incidencia_100k"].map(lambda v: f"{v:.1f}")
    show["target_week"] = pd.to_datetime(show["target_week"]).dt.date
    st.dataframe(
        show.rename(
            columns={
                "municipio_nome": "Município",
                "rotulo": "Faixa de alerta",
                "pred_casos": "Casos previstos",
                "pred_incidencia_100k": "Incidência /100 mil",
                "target_week": "Semana alvo",
            }
        ),
        hide_index=True,
        width="stretch",
    )
    validation = _optional("alert_validation")
    if validation is not None:
        current = validation[validation["horizon"] == horizon]
        if not current.empty:
            row = current.iloc[0]
            st.subheader("Validação da faixa vermelha")
            st.write(
                f"No backtest de {horizon} semanas, {row['n']:.0f} previsões foram avaliadas. "
                f"Precisão: {row['red_precision']:.1%}; "
                f"sensibilidade: {row['red_recall']:.1%}. "
                "Os cortes foram calculados com o histórico disponível em cada origem."
            )
    st.caption(
        "As previsões apoiam a vigilância epidemiológica; não substituem boletins oficiais "
        "nem avaliação clínica."
    )


if __name__ == "__main__":
    main()
