"""Ingestão InfoDengue (casos semanais + clima + alerta por município)."""

from __future__ import annotations

from io import StringIO
from pathlib import Path

import pandas as pd

from dengue_forecast.config import Settings, get_settings
from dengue_forecast.ingest.http import HttpClient
from dengue_forecast.ingest.ibge_codes import mt_geocodes
from dengue_forecast.ingest.io_utils import write_bronze_parquet
from dengue_forecast.logging_setup import get_logger
from dengue_forecast.schemas.bronze import validate_infodengue
from dengue_forecast.warehouse import Warehouse

log = get_logger(__name__)

INFO_DENGUE_URL = "https://info.dengue.mat.br/api/alertcity"

# Colunas da API → bronze normalizado
_RENAME = {
    "data_iniSE": "data_ini_se",
    "SE": "se",
    "casos": "casos",
    "casos_est": "casos_est",
    "p_inc100k": "p_inc100k",
    "nivel": "nivel",
    "municipio_nome": "municipio_nome",
    "pop": "pop",
    "tempmed": "tempmed",
    "umidmed": "umidmed",
}


def _normalize(raw: pd.DataFrame, geocode: int, uf: str) -> pd.DataFrame:
    df = raw.rename(columns=_RENAME).copy()
    keep = [
        "data_ini_se",
        "se",
        "casos",
        "casos_est",
        "p_inc100k",
        "nivel",
        "municipio_nome",
        "pop",
        "tempmed",
        "umidmed",
    ]
    for col in keep:
        if col not in df.columns:
            df[col] = pd.NA
    df = df[keep]
    df["geocode"] = geocode
    df["uf"] = uf
    df["data_ini_se"] = pd.to_datetime(df["data_ini_se"], errors="coerce")
    return df


def fetch_municipality(
    client: HttpClient,
    geocode: int,
    *,
    start_year: int,
    end_year: int,
    disease: str = "dengue",
) -> pd.DataFrame:
    """Baixa série semanal de um município via API InfoDengue (CSV)."""
    params = {
        "geocode": geocode,
        "disease": disease,
        "format": "csv",
        "ew_start": 1,
        "ey_start": start_year,
        "ew_end": 53,
        "ey_end": end_year,
    }
    text = client.get_text(INFO_DENGUE_URL, params=params)
    if not text.strip():
        return pd.DataFrame()
    return pd.read_csv(StringIO(text))


def load_from_sample_csv(path: Path, geocode: int, uf: str) -> pd.DataFrame:
    """Carrega CSV InfoDengue do diretório sample (offline)."""
    raw = pd.read_csv(path)
    return _normalize(raw, geocode, uf)


def ingest_infodengue(
    *,
    uf: str = "MT",
    start_year: int = 2019,
    end_year: int = 2025,
    geocodes: list[int] | None = None,
    settings: Settings | None = None,
    client: HttpClient | None = None,
    warehouse: Warehouse | None = None,
    sample_dir: Path | None = None,
) -> dict[str, int]:
    """
    Ingere InfoDengue para municípios da UF.

    Se `sample_dir` for informado, lê CSVs locais (CI / `make demo`) e não
    acessa a rede.
    """
    settings = settings or get_settings()
    uf = uf.upper()
    if uf != "MT":
        raise ValueError("Fase 1 cobre apenas UF=MT; demais UFs no roadmap.")

    codes = geocodes or mt_geocodes()
    owns_wh = warehouse is None
    owns_client = client is None and sample_dir is None
    warehouse = warehouse or Warehouse(settings.warehouse)
    client = client or (None if sample_dir else HttpClient(settings))

    wrote = 0
    skipped = 0
    failed = 0
    rows_total = 0

    try:
        for geocode in codes:
            if sample_dir is not None:
                csv_path = Path(sample_dir) / "infodengue" / f"{geocode}.csv"
                if not csv_path.exists():
                    log.warning("sample_missing", geocode=geocode, path=str(csv_path))
                    continue
                df = load_from_sample_csv(csv_path, geocode, uf)
            else:
                assert client is not None
                try:
                    raw = fetch_municipality(
                        client, geocode, start_year=start_year, end_year=end_year
                    )
                except Exception as exc:  # noqa: BLE001 — um município fora do ar não derruba o estado
                    log.warning("infodengue_failed", geocode=geocode, error=str(exc))
                    failed += 1
                    continue
                if raw.empty:
                    log.warning("infodengue_empty", geocode=geocode)
                    continue
                df = _normalize(raw, geocode, uf)

            # Filtra anos pedidos
            years = df["data_ini_se"].dt.year
            df = df[(years >= start_year) & (years <= end_year)].reset_index(drop=True)
            if df.empty:
                continue

            df = validate_infodengue(df)
            partition_key = f"{uf}/{geocode}/{start_year}-{end_year}"
            _, did_write = write_bronze_parquet(
                df,
                warehouse=warehouse,
                source="infodengue",
                partition_key=partition_key,
                bronze_root=settings.bronze,
                partition_cols={"uf": uf, "geocode": geocode},
            )
            rows_total += len(df)
            if did_write:
                wrote += 1
            else:
                skipped += 1

        parquet_root = settings.bronze / "infodengue"
        if any(parquet_root.glob("**/data.parquet")):
            warehouse.register_parquet_view(
                "bronze_infodengue",
                parquet_root / "**" / "data.parquet",
            )
    finally:
        if owns_client and client is not None:
            client.close()
        if owns_wh:
            warehouse.close()

    summary = {
        "wrote": wrote,
        "skipped": skipped,
        "failed": failed,
        "rows": rows_total,
        "geocodes": len(codes),
    }
    log.info("infodengue_done", **summary)
    return summary
