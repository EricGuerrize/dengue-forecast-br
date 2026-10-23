"""Exploração offline: casos semanais Cuiabá × chuva com correlação defasada."""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

from dengue_forecast.config import Settings, get_settings
from dengue_forecast.ingest.ibge import ingest_ibge
from dengue_forecast.ingest.infodengue import ingest_infodengue
from dengue_forecast.ingest.inmet import ingest_inmet
from dengue_forecast.logging_setup import get_logger
from dengue_forecast.warehouse import Warehouse

log = get_logger(__name__)

CUIABA_GEOCODE = 5103403
CUIABA_STATION = "A901"


def _weekly_precip(daily: pd.DataFrame) -> pd.DataFrame:
    """Agrega precipitação diária em semanas epidemiológicas (dom–sáb)."""
    d = daily.copy()
    d["date"] = pd.to_datetime(d["date"])
    # W-SAT: período termina no sábado; start_time = domingo (como InfoDengue data_iniSE)
    d["week_start"] = d["date"].dt.to_period("W-SAT").dt.start_time
    return (
        d.groupby("week_start", as_index=False)
        .agg(precip_mm=("precip_mm", "sum"), temp_mean_c=("temp_mean_c", "mean"))
        .sort_values("week_start")
    )


def _lag_correlations(cases: pd.Series, rain: pd.Series, max_lag: int = 12) -> pd.DataFrame:
    rows = []
    for lag in range(0, max_lag + 1):
        shifted = rain.shift(lag)
        corr = cases.corr(shifted)
        rows.append({"lag_weeks": lag, "pearson_r": corr})
    return pd.DataFrame(rows)


def run_demo(
    *,
    sample_dir: Path | None = None,
    output_dir: Path | None = None,
    settings: Settings | None = None,
) -> Path:
    """
    Carrega sample → bronze → DuckDB e gera PNG casos × chuva (Cuiabá).

    Returns:
        Caminho do PNG gerado.
    """
    settings = settings or get_settings()
    sample = Path(sample_dir or settings.sample)
    out_dir = Path(output_dir or settings.artifacts)
    out_dir.mkdir(parents=True, exist_ok=True)

    if not sample.exists():
        raise FileNotFoundError(f"Sample não encontrado: {sample}")

    with Warehouse(settings.warehouse) as wh:
        ingest_ibge(sample_dir=sample, settings=settings, warehouse=wh)
        ingest_infodengue(
            uf="MT",
            start_year=2022,
            end_year=2024,
            geocodes=[CUIABA_GEOCODE, 5108402, 5107602, 5107909, 5101803],
            sample_dir=sample,
            settings=settings,
            warehouse=wh,
        )
        for year in (2022, 2023, 2024):
            ingest_inmet(
                year=year,
                uf="MT",
                station_ids=[CUIABA_STATION],
                sample_dir=sample,
                settings=settings,
                warehouse=wh,
            )

        cases = wh.con.execute(
            """
            SELECT data_ini_se AS week_start, casos, tempmed, umidmed
            FROM bronze_infodengue
            WHERE geocode = ?
            ORDER BY 1
            """,
            [CUIABA_GEOCODE],
        ).df()
        weather = wh.con.execute(
            """
            SELECT date, precip_mm, temp_mean_c
            FROM bronze_inmet
            WHERE station_id = ?
            ORDER BY 1
            """,
            [CUIABA_STATION],
        ).df()

    cases["week_start"] = pd.to_datetime(cases["week_start"])
    rain_w = _weekly_precip(weather)
    merged = cases.merge(rain_w, on="week_start", how="inner")
    if merged.empty:
        raise RuntimeError("Sem overlap casos×chuva no sample — verifique datas.")

    lags = _lag_correlations(merged["casos"], merged["precip_mm"], max_lag=12)
    best = lags.loc[lags["pearson_r"].abs().idxmax()]
    log.info(
        "demo_lag_peak",
        lag_weeks=int(best["lag_weeks"]),
        pearson_r=float(best["pearson_r"]),
        n_weeks=len(merged),
    )

    fig, axes = plt.subplots(3, 1, figsize=(11, 9), sharex=False, constrained_layout=True)

    ax0 = axes[0]
    ax0.plot(merged["week_start"], merged["casos"], color="#c0392b", label="Casos notificados")
    ax0.set_ylabel("Casos / semana")
    ax0.set_title("Cuiabá (5103403) — dengue semanal × precipitação (A901)")
    ax0.legend(loc="upper left")
    ax0_r = ax0.twinx()
    ax0_r.bar(
        merged["week_start"],
        merged["precip_mm"],
        width=5,
        alpha=0.35,
        color="#2980b9",
        label="Chuva (mm)",
    )
    ax0_r.set_ylabel("Chuva semanal (mm)")
    ax0_r.legend(loc="upper right")

    ax1 = axes[1]
    ax1.plot(lags["lag_weeks"], lags["pearson_r"], marker="o", color="#1a5276")
    ax1.axhline(0, color="gray", lw=0.8)
    ax1.set_xlabel("Defasagem da chuva (semanas)")
    ax1.set_ylabel("Correlação de Pearson")
    ax1.set_title(
        f"Correlação casos × chuva defasada (pico: lag={int(best['lag_weeks'])}w, "
        f"r={best['pearson_r']:.2f})"
    )
    ax1.set_xticks(range(0, 13))

    ax2 = axes[2]
    ax2.scatter(merged["precip_mm"], merged["casos"], alpha=0.6, c="#27ae60", edgecolors="none")
    ax2.set_xlabel("Chuva na mesma semana (mm)")
    ax2.set_ylabel("Casos")
    ax2.set_title("Dispersão contemporânea (sem lag)")

    png_path = out_dir / "cuiaba_casos_vs_chuva.png"
    fig.savefig(png_path, dpi=120)
    plt.close(fig)

    lags.to_csv(out_dir / "cuiaba_lag_correlation.csv", index=False)
    merged.to_csv(out_dir / "cuiaba_weekly_merged.csv", index=False)
    log.info("demo_chart_saved", path=str(png_path))
    return png_path
