"""SIVEP-Gripe agregado por município e semana.

O arquivo nacional do OpenDataSUS é uma lista nominal. Este módulo lê só as
colunas de data, município, UF e classificação, soma as linhas e apaga o
arquivo baixado. Nome de paciente não entra no parquet.
"""

from __future__ import annotations

import tempfile
from collections.abc import Callable
from datetime import date, timedelta
from pathlib import Path

import httpx
import pandas as pd

from dengue_forecast.config import Settings, get_settings
from dengue_forecast.ingest.http import HttpClient
from dengue_forecast.ingest.io_utils import write_bronze_parquet
from dengue_forecast.logging_setup import get_logger
from dengue_forecast.warehouse import Warehouse

log = get_logger(__name__)

CKAN_PACKAGE_URL = "https://dadosabertos.saude.gov.br/api/3/action/package_show"
CKAN_PACKAGES = ("srag-2019-a-2026",)
S3_SRAG_ROOT = "https://s3.sa-east-1.amazonaws.com/ckan.saude.gov.br/SRAG"

_LINE_COLUMNS = {
    "DT_SIN_PRI",
    "DT_NOTIFIC",
    "CO_MUN_RES",
    "CO_MUN_NOT",
    "CLASSI_FIN",
    "PCR_VSR",
    "SG_UF_NOT",
}
_AGG_COLUMNS = {"geocode", "week_start", "virus", "casos", "uf", "municipio_nome", "fonte"}


def pick_srag_resource(resources: list[dict[str, object]], year: int) -> str:
    """CSV do ano epidemiológico, o mais recente quando há mais de um."""
    token = f"INFLUD{year % 100:02d}"
    candidates: list[tuple[str, str]] = []
    for resource in resources:
        name = str(resource.get("name", ""))
        url = str(resource.get("url", ""))
        if not url.lower().split("?", 1)[0].endswith(".csv"):
            continue
        if token not in name.upper() and token not in url.upper():
            continue
        modified = str(resource.get("metadata_modified") or "")
        candidates.append((modified, url))
    if not candidates:
        raise LookupError(f"Nenhum CSV de SRAG para {year}.")
    candidates.sort()
    return candidates[-1][1]


def _parse_dates(values: pd.Series) -> pd.Series:
    """ISO (`2024-01-02` ou com hora) sem trocar dia e mês; o resto como data brasileira."""
    text = values.astype("string").str.strip()
    iso = text.str.match(r"^\d{4}-\d{2}-\d{2}", na=False)
    parsed = pd.Series(pd.NaT, index=values.index, dtype="datetime64[ns]")
    if bool(iso.any()):
        day = text.loc[iso].str.slice(0, 10)
        parsed.loc[iso] = pd.to_datetime(day, format="%Y-%m-%d", errors="coerce")
    rest = ~iso & text.notna()
    if bool(rest.any()):
        parsed.loc[rest] = pd.to_datetime(text.loc[rest], dayfirst=True, errors="coerce")
    return parsed


def municipio_geocode7(value: object) -> int | None:
    """Código IBGE de 7 dígitos. O CSV do SIVEP manda 6; o dígito é o módulo 10."""
    try:
        number = int(str(value).split(".", 1)[0])
    except (TypeError, ValueError):
        return None
    if 1_100_000 <= number <= 5_300_108:
        return number
    if not 100_000 <= number <= 999_999:
        return None
    code = f"{number:06d}"
    total = 0
    for digit, weight in zip(code, (1, 2, 1, 2, 1, 2), strict=True):
        product = int(digit) * weight
        total += product // 10 + product % 10
    check = (10 - (total % 10)) % 10
    return int(f"{code}{check}")


def srag_object_url(year: int, stamp: str) -> str:
    return f"{S3_SRAG_ROOT}/{year}/INFLUD{year % 100:02d}-{stamp}.csv"


def latest_direct_url(
    year: int,
    *,
    today: date,
    exists: Callable[[str], bool],
    window_days: int = 45,
) -> str | None:
    """O catálogo CKAN cai. O objeto no S3 leva a data de publicação no nome."""
    for offset in range(window_days + 1):
        day = today - timedelta(days=offset)
        url = srag_object_url(year, day.strftime("%d-%m-%Y"))
        if exists(url):
            return url
    return None


def _week_start(dates: pd.Series) -> pd.Series:
    return _parse_dates(dates).dt.to_period("W-SAT").dt.start_time


def _virus(frame: pd.DataFrame) -> pd.Series:
    classi = pd.to_numeric(frame["CLASSI_FIN"], errors="coerce")
    if "PCR_VSR" in frame.columns:
        pcr_vsr = pd.to_numeric(frame["PCR_VSR"], errors="coerce")
    else:
        pcr_vsr = pd.Series(pd.NA, index=frame.index)
    virus = pd.Series("outros", index=frame.index, dtype="object")
    virus = virus.mask(classi == 1, "influenza")
    virus = virus.mask(classi == 5, "covid")
    virus = virus.mask((classi == 2) & (pcr_vsr == 1), "vsr")
    return virus


def aggregate_line_list(
    raw: pd.DataFrame,
    *,
    uf: str = "MT",
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Conta casos e o atraso sintoma→notificação. Descarta colunas de pessoa."""
    uf = uf.upper()
    frame = raw.copy()
    if "SG_UF_NOT" in frame.columns:
        frame = frame[frame["SG_UF_NOT"].astype(str).str.upper() == uf]

    code_col = "CO_MUN_RES" if "CO_MUN_RES" in frame.columns else "CO_MUN_NOT"
    if code_col not in frame.columns or "DT_SIN_PRI" not in frame.columns:
        empty_cases = pd.DataFrame(columns=["geocode", "week_start", "virus", "casos", "uf"])
        empty_delay = pd.DataFrame(columns=["delay_weeks", "n"])
        return empty_cases, empty_delay

    frame["geocode"] = frame[code_col].map(municipio_geocode7)
    frame = frame[frame["geocode"].notna()]
    if uf == "MT":
        frame = frame[frame["geocode"].between(5_100_000, 5_199_999)]
    frame["week_start"] = _week_start(frame["DT_SIN_PRI"])
    frame = frame[frame["week_start"].notna()]
    if "CLASSI_FIN" not in frame.columns:
        frame["CLASSI_FIN"] = pd.NA
    frame["virus"] = _virus(frame)
    frame["uf"] = uf

    cases = frame.groupby(["geocode", "week_start", "virus", "uf"]).size().reset_index(name="casos")
    cases["geocode"] = cases["geocode"].astype(int)
    cases["casos"] = cases["casos"].astype(int)

    if "DT_NOTIFIC" in raw.columns:
        symptom = _parse_dates(frame["DT_SIN_PRI"])
        notified = _parse_dates(frame["DT_NOTIFIC"])
        delay_days = (notified - symptom).dt.days
        kept = delay_days.notna() & (delay_days >= 0)
        delay_weeks = (delay_days.loc[kept] // 7).astype(int)
        delay_counts = (
            delay_weeks.to_frame("delay_weeks")
            .groupby("delay_weeks")
            .size()
            .reset_index(name="n")
            .sort_values("delay_weeks")
        )
    else:
        delay_counts = pd.DataFrame(columns=["delay_weeks", "n"])

    return cases.reset_index(drop=True), delay_counts.reset_index(drop=True)


def _separator(header_line: str) -> str:
    return ";" if header_line.count(";") >= header_line.count(",") else ","


def _read_header(path: Path) -> tuple[str, str]:
    for encoding in ("utf-8", "latin-1"):
        try:
            line = path.read_text(encoding=encoding).splitlines()[0]
        except UnicodeDecodeError:
            continue
        return encoding, line
    raise UnicodeError(f"Não foi possível ler o cabeçalho de {path}")


def _usecols(header: list[str]) -> list[str]:
    allowed = {name.upper() for name in _LINE_COLUMNS | _AGG_COLUMNS}
    return [column for column in header if column.upper() in allowed or column in _AGG_COLUMNS]


def _write_outputs(
    cases: pd.DataFrame,
    delay: pd.DataFrame,
    *,
    settings: Settings,
    uf: str,
    warehouse: Warehouse,
) -> dict[str, object]:
    uf = uf.upper()
    cases = cases.copy()
    cases["week_start"] = pd.to_datetime(cases["week_start"])
    if "fonte" not in cases.columns:
        cases["fonte"] = "opendatasus"

    _, wrote_cases = write_bronze_parquet(
        cases,
        warehouse=warehouse,
        source="srag",
        partition_key=uf,
        bronze_root=settings.bronze,
        partition_cols={"uf": uf},
    )
    _, wrote_delay = write_bronze_parquet(
        delay,
        warehouse=warehouse,
        source="srag_atraso",
        partition_key=uf,
        bronze_root=settings.bronze,
        partition_cols={"uf": uf},
    )
    settings.forecast.mkdir(parents=True, exist_ok=True)
    cases.to_parquet(settings.forecast / "srag.parquet", index=False)
    delay.to_parquet(settings.forecast / "srag_atraso.parquet", index=False)
    return {
        "status": "ok",
        "rows": int(len(cases)),
        "delay_rows": int(len(delay)),
        "wrote_cases": wrote_cases,
        "wrote_delay": wrote_delay,
    }


def ingest_sivep_file(
    path: Path,
    *,
    settings: Settings | None = None,
    warehouse: Warehouse | None = None,
    uf: str = "MT",
) -> dict[str, object]:
    """Agrega um CSV local (lista nominal ou contagem pronta) e grava o bronze."""
    settings = settings or get_settings()
    owns_wh = warehouse is None
    warehouse = warehouse or Warehouse(settings.warehouse)
    try:
        encoding, header_line = _read_header(path)
        sep = _separator(header_line)
        columns = list(pd.read_csv(path, sep=sep, nrows=0, encoding=encoding).columns)
        selected = _usecols(columns)
        frame = pd.read_csv(path, sep=sep, usecols=selected, encoding=encoding)
        if {"geocode", "virus", "casos"} <= set(frame.columns):
            cases = frame
            delay = pd.DataFrame(columns=["delay_weeks", "n"])
            atraso_path = path.with_name("atraso.csv")
            if atraso_path.exists() and atraso_path != path:
                delay = pd.read_csv(atraso_path)
        else:
            cases, delay = aggregate_line_list(frame, uf=uf)
        return _write_outputs(cases, delay, settings=settings, uf=uf, warehouse=warehouse)
    finally:
        if owns_wh:
            warehouse.close()


def _download_csv(url: str, dest: Path, settings: Settings) -> None:
    timeout = httpx.Timeout(settings.http_timeout_s, read=1800.0)
    headers = {"User-Agent": settings.user_agent}
    with httpx.stream("GET", url, timeout=timeout, follow_redirects=True, headers=headers) as resp:
        resp.raise_for_status()
        with dest.open("wb") as handle:
            for chunk in resp.iter_bytes():
                handle.write(chunk)


def _url_exists(url: str, settings: Settings) -> bool:
    timeout = httpx.Timeout(20.0, read=20.0)
    headers = {"User-Agent": settings.user_agent}
    try:
        response = httpx.head(url, timeout=timeout, follow_redirects=True, headers=headers)
    except httpx.HTTPError:
        return False
    return response.status_code == 200


def _direct_resources(years: tuple[int, ...], settings: Settings) -> list[dict[str, object]]:
    today = date.today()
    found: list[dict[str, object]] = []
    for year in years:
        url = latest_direct_url(year, today=today, exists=lambda item: _url_exists(item, settings))
        if url is None:
            log.warning("sivep_direct_missing", year=year)
            continue
        found.append({"name": url.rsplit("/", 1)[-1], "url": url, "metadata_modified": ""})
    return found


def _resources(client: HttpClient, package_id: str) -> list[dict[str, object]]:
    payload = client.get_json(CKAN_PACKAGE_URL, params={"id": package_id})
    if not isinstance(payload, dict):
        return []
    result = payload.get("result", {})
    if not isinstance(result, dict):
        return []
    resources = result.get("resources", [])
    if not isinstance(resources, list):
        return []
    return [item for item in resources if isinstance(item, dict)]


def _aggregate_downloaded(path: Path, *, uf: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    encoding, header_line = _read_header(path)
    sep = _separator(header_line)
    columns = list(pd.read_csv(path, sep=sep, nrows=0, encoding=encoding).columns)
    selected = _usecols(columns)
    cases_parts: list[pd.DataFrame] = []
    delay_parts: list[pd.DataFrame] = []
    reader = pd.read_csv(
        path,
        sep=sep,
        usecols=selected,
        encoding=encoding,
        chunksize=100_000,
    )
    for chunk in reader:
        cases, delay = aggregate_line_list(chunk, uf=uf)
        if not cases.empty:
            cases_parts.append(cases)
        if not delay.empty:
            delay_parts.append(delay)
    if not cases_parts:
        return (
            pd.DataFrame(columns=["geocode", "week_start", "virus", "casos", "uf"]),
            pd.DataFrame(columns=["delay_weeks", "n"]),
        )
    cases = (
        pd.concat(cases_parts, ignore_index=True)
        .groupby(["geocode", "week_start", "virus", "uf"], as_index=False)["casos"]
        .sum()
    )
    delay = (
        pd.concat(delay_parts, ignore_index=True)
        .groupby("delay_weeks", as_index=False)["n"]
        .sum()
        .sort_values("delay_weeks")
        if delay_parts
        else pd.DataFrame(columns=["delay_weeks", "n"])
    )
    return cases, delay


def ingest_sivep(
    *,
    uf: str = "MT",
    years: tuple[int, ...] | None = None,
    settings: Settings | None = None,
    warehouse: Warehouse | None = None,
    sample_dir: Path | None = None,
    client: HttpClient | None = None,
) -> dict[str, object]:
    """Sample offline, ou agregação do CSV nacional do OpenDataSUS."""
    settings = settings or get_settings()
    uf = uf.upper()
    if sample_dir is not None:
        return ingest_sivep_file(
            Path(sample_dir) / "srag" / "casos.csv",
            settings=settings,
            warehouse=warehouse,
            uf=uf,
        )

    owns_wh = warehouse is None
    owns_client = client is None
    warehouse = warehouse or Warehouse(settings.warehouse)
    client = client or HttpClient(settings)
    if years is None:
        today = pd.Timestamp.today().year
        years = (today - 1, today)

    try:
        resources: list[dict[str, object]] = []
        for package_id in CKAN_PACKAGES:
            try:
                resources = _resources(client, package_id)
            except Exception as exc:  # noqa: BLE001 — catálogo fora do ar não derruba o ciclo
                log.warning("sivep_catalog_failed", package=package_id, error=str(exc))
                continue
            if resources:
                break
        if not resources:
            log.warning("sivep_catalog_empty")
            resources = _direct_resources(years, settings)
        if not resources:
            return {"status": "skipped", "reason": "catalogo_indisponivel", "rows": 0}

        case_parts: list[pd.DataFrame] = []
        delay_parts: list[pd.DataFrame] = []
        for year in years:
            try:
                url = pick_srag_resource(resources, year)
            except LookupError as exc:
                log.warning("sivep_year_missing", year=year, error=str(exc))
                continue
            with tempfile.TemporaryDirectory() as tmp:
                dest = Path(tmp) / f"srag_{year}.csv"
                log.info("sivep_download", year=year, url=url)
                _download_csv(url, dest, settings)
                cases, delay = _aggregate_downloaded(dest, uf=uf)
            if not cases.empty:
                case_parts.append(cases)
            if not delay.empty:
                delay_parts.append(delay)

        if not case_parts:
            return {"status": "skipped", "reason": "sem_casos", "rows": 0}

        cases = (
            pd.concat(case_parts, ignore_index=True)
            .groupby(["geocode", "week_start", "virus", "uf"], as_index=False)["casos"]
            .sum()
        )
        cases["fonte"] = "opendatasus"
        if delay_parts:
            delay = (
                pd.concat(delay_parts, ignore_index=True)
                .groupby("delay_weeks", as_index=False)["n"]
                .sum()
            )
        else:
            delay = pd.DataFrame(columns=["delay_weeks", "n"])
        summary = _write_outputs(cases, delay, settings=settings, uf=uf, warehouse=warehouse)
        log.info("sivep_done", rows=summary["rows"])
        return summary
    finally:
        if owns_client:
            client.close()
        if owns_wh:
            warehouse.close()
