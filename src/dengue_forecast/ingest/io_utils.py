"""Utilitários de escrita parquet + hashing para idempotência."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pandas as pd

from dengue_forecast.logging_setup import get_logger
from dengue_forecast.warehouse import Warehouse

log = get_logger(__name__)


def content_hash_dataframe(df: pd.DataFrame) -> str:
    """Hash estável do conteúdo (parquet round-trip bytes)."""
    payload = df.sort_index(axis=1).to_csv(index=False).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def write_bronze_parquet(
    df: pd.DataFrame,
    *,
    warehouse: Warehouse,
    source: str,
    partition_key: str,
    bronze_root: Path,
    partition_cols: dict[str, str | int],
) -> tuple[Path, bool]:
    """
    Escreve parquet particionado se o hash mudou.

    Returns:
        (path, wrote) — wrote=False se pulou por idempotência.
    """
    digest = content_hash_dataframe(df)
    previous = warehouse.get_manifest_hash(source, partition_key)
    parts = "/".join(f"{k}={v}" for k, v in partition_cols.items())
    out_dir = bronze_root / source / parts
    out_path = out_dir / "data.parquet"

    if previous == digest and out_path.exists():
        log.info(
            "ingest_skip_unchanged",
            source=source,
            partition_key=partition_key,
            hash=digest[:12],
        )
        return out_path, False

    out_dir.mkdir(parents=True, exist_ok=True)
    df.to_parquet(out_path, index=False)
    warehouse.upsert_manifest(
        source=source,
        partition_key=partition_key,
        content_hash=digest,
        row_count=len(df),
        parquet_path=str(out_path),
    )
    log.info(
        "ingest_wrote",
        source=source,
        partition_key=partition_key,
        rows=len(df),
        path=str(out_path),
        hash=digest[:12],
    )
    return out_path, True
