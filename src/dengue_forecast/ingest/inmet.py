"""Ingestão INMET — estações meteorológicas históricas (chuva, temperatura, umidade).

Fonte oficial: https://portal.inmet.gov.br/dadoshistoricos (ZIPs anuais BDMEP).
Quando o portal está indisponível, o modo sample carrega séries diárias já
normalizadas (no sample do repo: estação A901 Cuiabá, precip via Open-Meteo
Archive nas coordenadas da estação — ver README / data/sample/ATTRIBUTION.md).
"""

from __future__ import annotations

import io
import zipfile
from pathlib import Path

import pandas as pd

from dengue_forecast.config import Settings, get_settings
from dengue_forecast.ingest.http import HttpClient
from dengue_forecast.ingest.io_utils import write_bronze_parquet
from dengue_forecast.logging_setup import get_logger
from dengue_forecast.schemas.bronze import validate_inmet
from dengue_forecast.warehouse import Warehouse

log = get_logger(__name__)

INMET_ZIP_URL = "https://portal.inmet.gov.br/uploads/dadoshistoricos/{year}.zip"

# Estações automáticas conhecidas em MT (código BDMEP / API Tempo)
MT_STATIONS: dict[str, dict[str, float | str]] = {
    "A901": {
        "name": "CUIABA",
        "latitude": -15.789444,
        "longitude": -56.089167,
        "altitude_m": 185.0,
    },
    "A902": {
        "name": "CACERES",
        "latitude": -16.050278,
        "longitude": -57.635556,
        "altitude_m": 130.0,
    },
    "A904": {
        "name": "RONDONOPOLIS",
        "latitude": -16.45,
        "longitude": -54.616667,
        "altitude_m": 290.0,
    },
    "A917": {
        "name": "SINOP",
        "latitude": -11.982222,
        "longitude": -55.566389,
        "altitude_m": 371.0,
    },
}


def _parse_bdmep_csv(text: str, station_id: str, uf: str) -> pd.DataFrame:
    """Parseia CSV diário BDMEP (separador `;`, cabeçalho variável)."""
    # BDMEP costuma ter metadados nas primeiras linhas; tentamos achar o header
    lines = text.splitlines()
    header_idx = 0
    for i, line in enumerate(lines[:20]):
        low = line.lower()
        if "data" in low and ("precipita" in low or "temp" in low):
            header_idx = i
            break
    raw = pd.read_csv(
        io.StringIO("\n".join(lines[header_idx:])),
        sep=";",
        decimal=",",
        encoding="latin-1",
        engine="python",
    )
    cols = {c.lower().strip(): c for c in raw.columns}

    def pick(*candidates: str) -> str | None:
        for cand in candidates:
            for key, orig in cols.items():
                if cand in key:
                    return orig
        return None

    date_col = pick("data")
    precip_col = pick("precipita")
    tmean_col = pick("temp. med", "temperatura media", "temp_med")
    tmax_col = pick("temp. max", "temperatura maxima")
    tmin_col = pick("temp. min", "temperatura minima")
    humid_col = pick("umidade")

    meta = MT_STATIONS.get(station_id, {})
    out = pd.DataFrame(
        {
            "station_id": station_id,
            "station_name": meta.get("name", station_id),
            "uf": uf,
            "latitude": meta.get("latitude"),
            "longitude": meta.get("longitude"),
            "date": pd.to_datetime(raw[date_col], dayfirst=True, errors="coerce")
            if date_col
            else pd.NaT,
            "precip_mm": pd.to_numeric(raw[precip_col], errors="coerce") if precip_col else pd.NA,
            "temp_mean_c": pd.to_numeric(raw[tmean_col], errors="coerce") if tmean_col else pd.NA,
            "temp_max_c": pd.to_numeric(raw[tmax_col], errors="coerce") if tmax_col else pd.NA,
            "temp_min_c": pd.to_numeric(raw[tmin_col], errors="coerce") if tmin_col else pd.NA,
            "humidity_mean_pct": pd.to_numeric(raw[humid_col], errors="coerce")
            if humid_col
            else pd.NA,
        }
    )
    return out.dropna(subset=["date"]).reset_index(drop=True)


def load_sample_station(path: Path) -> pd.DataFrame:
    """Carrega CSV normalizado do sample (offline)."""
    df = pd.read_csv(path)
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    keep = [
        "station_id",
        "station_name",
        "uf",
        "latitude",
        "longitude",
        "date",
        "precip_mm",
        "temp_mean_c",
        "temp_max_c",
        "temp_min_c",
        "humidity_mean_pct",
    ]
    return df[[c for c in keep if c in df.columns]]


def _stations_from_zip(zip_bytes: bytes, uf: str, station_ids: set[str]) -> dict[str, pd.DataFrame]:
    """Extrai CSVs de estações alvo de um ZIP anual INMET."""
    result: dict[str, pd.DataFrame] = {}
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        for name in zf.namelist():
            upper = name.upper()
            matched = next((sid for sid in station_ids if sid in upper), None)
            if matched is None:
                continue
            if not name.lower().endswith((".csv", ".txt")):
                continue
            with zf.open(name) as fh:
                # BDMEP frequentemente em latin-1
                text = fh.read().decode("latin-1", errors="replace")
            result[matched] = _parse_bdmep_csv(text, matched, uf)
            log.info("inmet_station_parsed", station=matched, file=name, rows=len(result[matched]))
    return result


def ingest_inmet(
    *,
    year: int,
    uf: str = "MT",
    station_ids: list[str] | None = None,
    settings: Settings | None = None,
    client: HttpClient | None = None,
    warehouse: Warehouse | None = None,
    sample_dir: Path | None = None,
) -> dict[str, int]:
    """Ingere observações diárias INMET (ou sample) para estações da UF."""
    settings = settings or get_settings()
    uf = uf.upper()
    if uf != "MT":
        raise ValueError("Fase 1 cobre apenas UF=MT.")

    targets = set(station_ids or list(MT_STATIONS.keys()))
    owns_wh = warehouse is None
    owns_client = client is None and sample_dir is None
    warehouse = warehouse or Warehouse(settings.warehouse)
    client = client or (None if sample_dir else HttpClient(settings))

    frames: dict[str, pd.DataFrame] = {}
    try:
        if sample_dir is not None:
            sample_inmet = Path(sample_dir) / "inmet"
            for csv_path in sorted(sample_inmet.glob("*.csv")):
                df = load_sample_station(csv_path)
                df = df[df["date"].dt.year == year]
                if df.empty:
                    continue
                sid = str(df["station_id"].iloc[0])
                if sid not in targets:
                    continue
                frames[sid] = df
        else:
            assert client is not None
            url = INMET_ZIP_URL.format(year=year)
            log.info("inmet_download", url=url)
            try:
                zip_bytes = client.get_bytes(url)
                frames = _stations_from_zip(zip_bytes, uf, targets)
            except Exception as exc:  # noqa: BLE001 — documentamos falha de rede
                log.error(
                    "inmet_download_failed",
                    year=year,
                    error=str(exc),
                    hint="Use data/sample ou tente novamente; portal INMET pode estar instável.",
                )
                raise

        wrote = skipped = rows_total = 0
        for sid, df in frames.items():
            df = validate_inmet(df)
            partition_key = f"{uf}/{sid}/{year}"
            _, did_write = write_bronze_parquet(
                df,
                warehouse=warehouse,
                source="inmet",
                partition_key=partition_key,
                bronze_root=settings.bronze,
                partition_cols={"uf": uf, "station_id": sid, "year": year},
            )
            rows_total += len(df)
            if did_write:
                wrote += 1
            else:
                skipped += 1

        if frames:
            warehouse.register_parquet_view(
                "bronze_inmet",
                settings.bronze / "inmet" / "**" / "data.parquet",
            )

        summary = {
            "wrote": wrote,
            "skipped": skipped,
            "rows": rows_total,
            "stations": len(frames),
            "year": year,
        }
        log.info("inmet_done", **summary)
        return summary
    finally:
        if owns_client and client is not None:
            client.close()
        if owns_wh:
            warehouse.close()
