"""Silver/gold: dbt build offline sobre o sample de MT."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from dengue_forecast.ingest.ibge import ingest_ibge
from dengue_forecast.ingest.ibge_codes import SAMPLE_GEOCODES
from dengue_forecast.ingest.infodengue import ingest_infodengue
from dengue_forecast.ingest.inmet import ingest_inmet
from dengue_forecast.ingest.io_utils import write_bronze_parquet
from dengue_forecast.transform.dbt_runner import dbt_executable, run_dbt_build
from dengue_forecast.warehouse import Warehouse

pytestmark = pytest.mark.skipif(
    not dbt_executable().exists(),
    reason="dbt ausente; instale com pip install -e '.[transform]'",
)


def _load_bronze(tmp_settings, sample_dir) -> None:
    with Warehouse(tmp_settings.warehouse) as wh:
        ingest_ibge(sample_dir=sample_dir, settings=tmp_settings, warehouse=wh)
        ingest_infodengue(
            uf="MT",
            start_year=2022,
            end_year=2024,
            geocodes=SAMPLE_GEOCODES,
            sample_dir=sample_dir,
            settings=tmp_settings,
            warehouse=wh,
        )
        for year in (2022, 2023, 2024):
            ingest_inmet(
                year=year,
                uf="MT",
                station_ids=["A901"],
                sample_dir=sample_dir,
                settings=tmp_settings,
                warehouse=wh,
            )
        a904 = pd.DataFrame(
            {
                "station_id": ["A904"],
                "station_name": ["RONDONOPOLIS"],
                "uf": ["MT"],
                "latitude": [-16.45],
                "longitude": [-54.616667],
                "date": [pd.Timestamp("2023-06-01")],
                "precip_mm": [10.0],
                "temp_mean_c": [24.0],
                "temp_max_c": [31.0],
                "temp_min_c": [18.0],
                "humidity_mean_pct": [70.0],
            }
        )
        write_bronze_parquet(
            a904,
            warehouse=wh,
            source="inmet",
            partition_key="MT/A904/2023",
            bronze_root=tmp_settings.bronze,
            partition_cols={"uf": "MT", "station_id": "A904", "year": 2023},
        )
        wh.register_parquet_view(
            "bronze_inmet",
            tmp_settings.bronze / "inmet" / "**" / "data.parquet",
        )


def test_gold_municipio_semana(tmp_settings, sample_dir, tmp_path: Path) -> None:
    _load_bronze(tmp_settings, sample_dir)
    run_dbt_build(tmp_settings, target_path=tmp_path / "dbt-target", capture=True)

    with Warehouse(tmp_settings.warehouse) as wh:
        gold = wh.con.execute("select * from gold.municipio_semana").df()
        estacao = wh.con.execute("select * from silver.estacao_municipio").df()

    assert not gold.empty
    assert gold.duplicated(["geocode", "week_start"]).sum() == 0
    assert (gold["populacao_2022"] > 0).all()

    cuiaba = gold[gold["geocode"] == 5103403].sort_values("week_start")
    assert not cuiaba.empty
    assert set(cuiaba["populacao_2022"]) == {650912}
    assert set(cuiaba["station_id"]) == {"A901"}
    assert (cuiaba["distance_km"] < 30).all()
    assert (pd.to_datetime(cuiaba["week_start"]).dt.day_of_week == 6).all()
    assert cuiaba["precip_mm"].notna().any()
    deltas = pd.to_datetime(cuiaba["week_start"]).diff().dt.days.dropna()
    assert (deltas == 7).all()
    expected = cuiaba["casos"] / cuiaba["populacao_2022"] * 100_000
    assert (cuiaba["incidencia_100k"] - expected).abs().max() < 0.001

    por_mun = estacao.set_index("codigo_ibge")["station_id"]
    assert por_mun.loc[5103403] == "A901"
    assert por_mun.loc[5108402] == "A901"
    assert por_mun.loc[5107602] == "A904"
    assert 5107909 not in por_mun.index


def test_cli_transform_help() -> None:
    from typer.testing import CliRunner

    from dengue_forecast.cli import app

    result = CliRunner().invoke(app, ["transform", "--help"])
    assert result.exit_code == 0
    assert "dbt" in result.stdout.lower()
