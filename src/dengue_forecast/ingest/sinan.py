"""Ingestão SINAN (DATASUS / PySUS) — opcional.

O FTP do DATASUS e o pacote PySUS são historicamente instáveis (timeouts,
mudança de paths, dependências nativas). Por isso a ingestão SINAN é
**opcional** na fase 1: se PySUS não estiver instalado ou a rede falhar,
registramos o erro e seguimos sem bloquear o restante do pipeline.

Instalação opcional::

    pip install 'dengue-forecast[sinan]'
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from dengue_forecast.config import Settings, get_settings
from dengue_forecast.ingest.io_utils import write_bronze_parquet
from dengue_forecast.logging_setup import get_logger
from dengue_forecast.warehouse import Warehouse

log = get_logger(__name__)


def ingest_sinan(
    *,
    year: int,
    uf: str = "MT",
    settings: Settings | None = None,
    warehouse: Warehouse | None = None,
    sample_dir: Path | None = None,
) -> dict[str, object]:
    """
    Tenta baixar notificações agregadas SINAN-DENGUE via PySUS.

    Retorna dict com status; nunca grava microdados individuais no repositório.
    Apenas contagens agregadas por município/semana epidemiológica.
    """
    settings = settings or get_settings()
    uf = uf.upper()
    owns_wh = warehouse is None
    warehouse = warehouse or Warehouse(settings.warehouse)

    try:
        if sample_dir is not None:
            sample_path = Path(sample_dir) / "sinan" / f"denet{str(year)[-2:]}_{uf}.parquet"
            if not sample_path.exists():
                msg = (
                    "SINAN sample ausente — fonte opcional. "
                    "Use `pip install '.[sinan]'` e `dfc ingest sinan` online."
                )
                log.warning("sinan_sample_missing", path=str(sample_path), detail=msg)
                return {"status": "skipped", "reason": "sample_missing", "year": year, "uf": uf}

        try:
            from pysus import SINAN  # type: ignore[import-untyped]
        except ImportError:
            log.warning(
                "sinan_pysus_missing",
                hint="pip install 'dengue-forecast[sinan]' — ingestão SINAN é opcional",
            )
            return {"status": "skipped", "reason": "pysus_not_installed", "year": year, "uf": uf}

        try:
            files = SINAN.download(year=[year], disease="Dengue")
            # PySUS retorna paths; agregamos apenas contagens (sem PII)
            frames: list[pd.DataFrame] = []
            for path in files if isinstance(files, list) else [files]:
                raw = pd.read_parquet(path) if str(path).endswith(".parquet") else pd.read_csv(path)
                if "ID_MUNICIP" not in raw.columns and "ID_MN_RESI" in raw.columns:
                    raw = raw.rename(columns={"ID_MN_RESI": "ID_MUNICIP"})
                # Filtra UF pelo prefixo do geocode (51 = MT)
                if "ID_MUNICIP" in raw.columns:
                    raw["ID_MUNICIP"] = raw["ID_MUNICIP"].astype(str).str.zfill(6).str[:6]
                    # códigos SINAN às vezes têm 6 dígitos sem dígito verificador
                    uf_prefix = "51" if uf == "MT" else None
                    if uf_prefix:
                        raw = raw[raw["ID_MUNICIP"].str.startswith(uf_prefix)]
                week_col = next(
                    (c for c in ("SEM_PRI", "SEM_NOT", "DT_SIN_PRI") if c in raw.columns),
                    None,
                )
                if week_col is None or "ID_MUNICIP" not in raw.columns:
                    continue
                agg = (
                    raw.groupby(["ID_MUNICIP", week_col], dropna=False)
                    .size()
                    .reset_index(name="casos_notificados")
                )
                agg = agg.rename(columns={"ID_MUNICIP": "geocode_sinan", week_col: "semana"})
                frames.append(agg)

            if not frames:
                return {"status": "empty", "year": year, "uf": uf}

            df = pd.concat(frames, ignore_index=True)
            df["year"] = year
            df["uf"] = uf
            # Garantia ética: só colunas agregadas
            df = df[["geocode_sinan", "semana", "casos_notificados", "year", "uf"]]

            _, wrote = write_bronze_parquet(
                df,
                warehouse=warehouse,
                source="sinan",
                partition_key=f"{uf}/{year}",
                bronze_root=settings.bronze,
                partition_cols={"uf": uf, "year": year},
            )
            warehouse.register_parquet_view(
                "bronze_sinan",
                settings.bronze / "sinan" / "**" / "data.parquet",
            )
            return {
                "status": "ok",
                "wrote": wrote,
                "rows": len(df),
                "year": year,
                "uf": uf,
            }
        except Exception as exc:  # noqa: BLE001
            log.error(
                "sinan_ingest_failed",
                year=year,
                uf=uf,
                error=str(exc),
                hint="FTP DATASUS/PySUS instável — mantenha SINAN opcional",
            )
            return {"status": "error", "error": str(exc), "year": year, "uf": uf}
    finally:
        if owns_wh:
            warehouse.close()
