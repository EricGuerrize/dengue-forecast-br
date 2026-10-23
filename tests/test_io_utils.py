"""Idempotência do manifesto de ingestão."""

from __future__ import annotations

from dengue_forecast.ingest.io_utils import content_hash_dataframe, write_bronze_parquet
from dengue_forecast.warehouse import Warehouse


def test_content_hash_stable(tiny_infodengue_df) -> None:
    a = content_hash_dataframe(tiny_infodengue_df)
    b = content_hash_dataframe(tiny_infodengue_df.copy())
    assert a == b


def test_write_bronze_idempotent(tmp_settings, tiny_infodengue_df) -> None:
    with Warehouse(tmp_settings.warehouse) as wh:
        path1, wrote1 = write_bronze_parquet(
            tiny_infodengue_df,
            warehouse=wh,
            source="infodengue",
            partition_key="MT/5103403/test",
            bronze_root=tmp_settings.bronze,
            partition_cols={"uf": "MT", "geocode": 5103403},
        )
        path2, wrote2 = write_bronze_parquet(
            tiny_infodengue_df,
            warehouse=wh,
            source="infodengue",
            partition_key="MT/5103403/test",
            bronze_root=tmp_settings.bronze,
            partition_cols={"uf": "MT", "geocode": 5103403},
        )
        assert wrote1 is True
        assert wrote2 is False
        assert path1 == path2
        assert path1.exists()
        h = wh.get_manifest_hash("infodengue", "MT/5103403/test")
        assert h is not None
