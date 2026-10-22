"""Registro bronze no DuckDB (lakehouse leve)."""

from __future__ import annotations

from pathlib import Path

import duckdb

from dengue_forecast.logging_setup import get_logger

log = get_logger(__name__)

MANIFEST_DDL = """
CREATE TABLE IF NOT EXISTS meta.ingestion_manifest (
    source       VARCHAR NOT NULL,
    partition_key VARCHAR NOT NULL,
    content_hash VARCHAR NOT NULL,
    row_count    BIGINT NOT NULL,
    parquet_path VARCHAR NOT NULL,
    ingested_at  TIMESTAMP NOT NULL DEFAULT current_timestamp,
    PRIMARY KEY (source, partition_key)
);
"""


class Warehouse:
    """Conexão DuckDB com schema `meta` e views bronze."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._con = duckdb.connect(str(self.path))
        self._con.execute("CREATE SCHEMA IF NOT EXISTS meta")
        self._con.execute(MANIFEST_DDL)

    @property
    def con(self) -> duckdb.DuckDBPyConnection:
        return self._con

    def close(self) -> None:
        self._con.close()

    def __enter__(self) -> Warehouse:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def register_parquet_view(self, view_name: str, parquet_glob: str | Path) -> None:
        """Cria/substitui view apontando para arquivos parquet particionados."""
        glob = str(parquet_glob).replace("'", "''")
        self._con.execute(
            f"CREATE OR REPLACE VIEW {view_name} AS "
            f"SELECT * FROM read_parquet('{glob}', hive_partitioning=true, union_by_name=true)"
        )
        log.info("view_registered", view=view_name, glob=glob)

    def upsert_manifest(
        self,
        *,
        source: str,
        partition_key: str,
        content_hash: str,
        row_count: int,
        parquet_path: str,
    ) -> None:
        self._con.execute(
            """
            INSERT OR REPLACE INTO meta.ingestion_manifest
                (source, partition_key, content_hash, row_count, parquet_path, ingested_at)
            VALUES (?, ?, ?, ?, ?, current_timestamp)
            """,
            [source, partition_key, content_hash, row_count, parquet_path],
        )

    def get_manifest_hash(self, source: str, partition_key: str) -> str | None:
        row = self._con.execute(
            """
            SELECT content_hash FROM meta.ingestion_manifest
            WHERE source = ? AND partition_key = ?
            """,
            [source, partition_key],
        ).fetchone()
        return row[0] if row else None
