"""dbt build da camada silver/gold sobre o warehouse bronze."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from dengue_forecast.config import Settings, get_settings
from dengue_forecast.logging_setup import get_logger

log = get_logger(__name__)


def centroide_csv(settings: Settings) -> Path:
    return settings.root / "data" / "reference" / "municipio_centroide_mt.csv"


def populacao_referencia_csv(settings: Settings) -> Path:
    return settings.root / "data" / "reference" / "populacao_mt_2022.csv"


def dbt_executable() -> Path:
    return Path(sys.executable).parent / "dbt"


def run_dbt_build(
    settings: Settings | None = None,
    *,
    target_path: Path | None = None,
    capture: bool = False,
) -> None:
    """Executa `dbt build` (seeds implícitos, models silver/gold e testes)."""
    settings = settings or get_settings()
    project = settings.root / "dbt"
    binary = dbt_executable()
    if not binary.exists():
        raise FileNotFoundError(
            "dbt não está neste ambiente. Instale com: pip install -e '.[transform]'"
        )
    centroides = centroide_csv(settings)
    if not centroides.exists():
        raise FileNotFoundError(f"Centróides ausentes: {centroides}")
    if not settings.warehouse.exists():
        raise FileNotFoundError(
            f"Warehouse ausente ({settings.warehouse}). Rode a ingestão bronze antes."
        )

    env = os.environ.copy()
    env["DFC_WAREHOUSE_PATH"] = str(settings.warehouse)
    env["DFC_CENTROIDE_CSV"] = str(centroides)
    env["DBT_SEND_ANONYMOUS_USAGE_STATS"] = "false"
    env["DO_NOT_TRACK"] = "1"

    cmd = [
        str(binary),
        "build",
        "--project-dir",
        str(project),
        "--profiles-dir",
        str(project),
        "--no-use-colors",
    ]
    if target_path is not None:
        target_path.mkdir(parents=True, exist_ok=True)
        log_path = target_path / "logs"
        log_path.mkdir(parents=True, exist_ok=True)
        cmd.extend(["--target-path", str(target_path), "--log-path", str(log_path)])

    log.info("dbt_build_start", warehouse=str(settings.warehouse))
    result = subprocess.run(
        cmd,
        env=env,
        check=False,
        capture_output=capture,
        text=True,
    )
    if result.returncode != 0:
        detail = ""
        if capture:
            detail = f"\n{(result.stdout or '')[-4000:]}\n{(result.stderr or '')[-2000:]}"
        raise RuntimeError(f"dbt build falhou (exit {result.returncode}).{detail}")
    log.info("dbt_build_ok")
