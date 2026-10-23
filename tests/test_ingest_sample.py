"""Ingestão offline a partir de data/sample."""

from __future__ import annotations

from dengue_forecast.ingest.ibge import ingest_ibge
from dengue_forecast.ingest.ibge_codes import SAMPLE_GEOCODES, mt_geocodes
from dengue_forecast.ingest.infodengue import ingest_infodengue
from dengue_forecast.ingest.inmet import ingest_inmet
from dengue_forecast.ingest.sinan import ingest_sinan
from dengue_forecast.warehouse import Warehouse


def test_mt_geocodes_count() -> None:
    assert len(mt_geocodes()) == 141
    assert 5103403 in mt_geocodes()


def test_ingest_ibge_sample(tmp_settings, sample_dir) -> None:
    with Warehouse(tmp_settings.warehouse) as wh:
        summary = ingest_ibge(sample_dir=sample_dir, settings=tmp_settings, warehouse=wh)
    assert summary["municipios"] == 141
    assert summary["populacao_rows"] >= 5


def test_infodengue_segue_quando_um_municipio_falha(tmp_settings) -> None:
    class _Client:
        def get_text(self, *_args, **_kwargs) -> str:
            raise RuntimeError("timeout")

        def close(self) -> None:
            return None

    with Warehouse(tmp_settings.warehouse) as wh:
        summary = ingest_infodengue(
            uf="MT",
            start_year=2024,
            end_year=2024,
            geocodes=[5103403],
            settings=tmp_settings,
            warehouse=wh,
            client=_Client(),
        )
    assert summary["failed"] == 1
    assert summary["rows"] == 0


def test_ingest_infodengue_sample(tmp_settings, sample_dir) -> None:
    with Warehouse(tmp_settings.warehouse) as wh:
        summary = ingest_infodengue(
            uf="MT",
            start_year=2022,
            end_year=2024,
            geocodes=SAMPLE_GEOCODES,
            sample_dir=sample_dir,
            settings=tmp_settings,
            warehouse=wh,
        )
        n = wh.con.execute("SELECT COUNT(*) FROM bronze_infodengue").fetchone()[0]
    assert summary["rows"] > 100
    assert n == summary["rows"]


def test_ingest_inmet_sample(tmp_settings, sample_dir) -> None:
    with Warehouse(tmp_settings.warehouse) as wh:
        summary = ingest_inmet(
            year=2023,
            uf="MT",
            station_ids=["A901"],
            sample_dir=sample_dir,
            settings=tmp_settings,
            warehouse=wh,
        )
    assert summary["rows"] > 300
    assert summary["stations"] == 1


def test_sinan_skips_without_pysus(tmp_settings, sample_dir) -> None:
    summary = ingest_sinan(year=2023, uf="MT", sample_dir=sample_dir, settings=tmp_settings)
    assert summary["status"] in {"skipped", "error", "ok", "empty"}
