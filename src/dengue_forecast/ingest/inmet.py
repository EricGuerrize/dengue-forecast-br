"""Ingestão INMET — estações meteorológicas históricas (chuva, temperatura, umidade).

Fonte oficial: https://portal.inmet.gov.br/dadoshistoricos (ZIPs anuais BDMEP).
Quando o portal está indisponível, o modo sample carrega séries diárias já
normalizadas (no sample do repo: estação A901 Cuiabá, precip via Open-Meteo
Archive nas coordenadas da estação — ver README / data/sample/ATTRIBUTION.md).
"""

from __future__ import annotations

import io
import unicodedata
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
MT_STATIONS: dict[str, dict[str, float | str | None]] = {
    "A901": {
        "name": "CUIABA",
        "latitude": -15.789444,
        "longitude": -56.089167,
        "altitude_m": 185.0,
    },
    "A902": {
        "name": "TANGARA DA SERRA",
        "latitude": None,
        "longitude": None,
        "altitude_m": None,
    },
    "A904": {
        "name": "SORRISO",
        "latitude": None,
        "longitude": None,
        "altitude_m": None,
    },
    "A917": {
        "name": "SINOP",
        "latitude": -11.982222,
        "longitude": -55.566389,
        "altitude_m": 371.0,
    },
}


def _fold(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text)
    stripped = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return stripped.lower().strip()


def _to_float(value: str) -> float:
    return float(str(value).strip().replace(",", "."))


def _preamble(lines: list[str]) -> dict[str, float | str]:
    """Nome e coordenada nas linhas de metadado, antes da tabela horária."""
    found: dict[str, float | str] = {}
    for line in lines[:30]:
        if ";" not in line:
            continue
        key, _, value = line.partition(";")
        folded = _fold(key)
        cleaned = value.strip()
        if not cleaned:
            continue
        if folded.startswith("latitude"):
            found["latitude"] = _to_float(cleaned)
        elif folded.startswith("longitude"):
            found["longitude"] = _to_float(cleaned)
        elif folded.startswith("estacao"):
            found["name"] = cleaned
    return found


def _pick(
    columns: dict[str, str],
    *candidates: str,
    exclude: tuple[str, ...] = (),
) -> str | None:
    for candidate in candidates:
        for key, original in columns.items():
            if candidate in key and not any(blocked in key for blocked in exclude):
                return original
    return None


def _numeric(raw: pd.DataFrame, column: str | None) -> pd.Series:
    if column is None:
        return pd.Series(float("nan"), index=raw.index, dtype="float64")
    return pd.to_numeric(raw[column], errors="coerce").astype("float64")


def _dates(raw: pd.DataFrame, column: str | None) -> pd.Series:
    if column is None:
        return pd.Series(pd.NaT, index=raw.index, dtype="datetime64[ns]")
    text = raw[column].astype("string").str.strip()
    iso = text.str.match(r"^\d{4}[-/]\d{2}[-/]\d{2}", na=False)
    parsed = pd.Series(pd.NaT, index=raw.index, dtype="datetime64[ns]")
    if bool(iso.any()):
        normalized = text.loc[iso].str.replace("/", "-", regex=False)
        parsed.loc[iso] = pd.to_datetime(normalized, format="%Y-%m-%d", errors="coerce")
    rest = ~iso & text.notna()
    if bool(rest.any()):
        parsed.loc[rest] = pd.to_datetime(text.loc[rest], dayfirst=True, errors="coerce")
    return parsed


def _parse_bdmep_csv(text: str, station_id: str, uf: str) -> pd.DataFrame:
    """CSV horário do BDMEP vira uma linha por dia.

    O arquivo traz metadado nas primeiras linhas e uma observação por hora.
    Chuva do dia é a soma. Temperatura e umidade são a média. Máxima e mínima
    do dia saem das colunas horárias de máxima e mínima.
    """
    lines = text.splitlines()
    header_idx = 0
    for i, line in enumerate(lines[:40]):
        folded = _fold(line)
        if "data" in folded and ("precipita" in folded or "temp" in folded):
            header_idx = i
            break
    raw = pd.read_csv(
        io.StringIO("\n".join(lines[header_idx:])),
        sep=";",
        decimal=",",
        encoding="latin-1",
        engine="python",
    )
    columns = {_fold(str(column)): column for column in raw.columns}
    date_col = _pick(columns, "data (yyyy-mm-dd)", "data")
    precip_col = _pick(columns, "precipita")
    tmean_col = _pick(columns, "bulbo seco", "temperatura media", "temp. med", "temp_med")
    tmax_col = _pick(columns, "temperatura maxima", "temp. max", exclude=("orvalho",))
    tmin_col = _pick(columns, "temperatura minima", "temp. min", exclude=("orvalho",))
    humid_col = _pick(columns, "umidade relativa do ar, horaria", "umidade relativa do ar")

    file_meta = _preamble(lines[:header_idx])
    fallback = MT_STATIONS.get(station_id, {})
    hourly = pd.DataFrame(
        {
            "station_id": station_id,
            "station_name": file_meta.get("name", fallback.get("name", station_id)),
            "uf": uf,
            "latitude": file_meta.get("latitude", fallback.get("latitude")),
            "longitude": file_meta.get("longitude", fallback.get("longitude")),
            "date": _dates(raw, date_col).dt.normalize(),
            "precip_mm": _numeric(raw, precip_col),
            "temp_mean_c": _numeric(raw, tmean_col),
            "temp_max_c": _numeric(raw, tmax_col),
            "temp_min_c": _numeric(raw, tmin_col),
            "humidity_mean_pct": _numeric(raw, humid_col),
        }
    )
    hourly = hourly.dropna(subset=["date"])
    if hourly.empty:
        return hourly.reset_index(drop=True)

    daily = hourly.groupby(
        ["station_id", "station_name", "uf", "latitude", "longitude", "date"],
        as_index=False,
        dropna=False,
    ).agg(
        precip_mm=("precip_mm", lambda series: series.sum(min_count=1)),
        temp_mean_c=("temp_mean_c", "mean"),
        temp_max_c=("temp_max_c", "max"),
        temp_min_c=("temp_min_c", "min"),
        humidity_mean_pct=("humidity_mean_pct", "mean"),
    )
    return daily.sort_values("date").reset_index(drop=True)


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
