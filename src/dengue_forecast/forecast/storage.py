"""Publicação consistente dos arquivos de uma rodada de previsão."""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from uuid import uuid4

import pandas as pd

FORECAST_FILES = (
    "history",
    "features",
    "backtest",
    "forward",
    "metrics",
    "alerts",
    "alert_validation",
)
DISPLAY_FILES = ("history", "backtest", "forward", "metrics", "alerts")


def active_dir(forecast_dir: Path) -> Path:
    """Devolve uma versão completa; aceita parquets antigos na raiz."""
    pointer = forecast_dir / "current.json"
    if not pointer.exists():
        return forecast_dir
    run_id = json.loads(pointer.read_text(encoding="utf-8"))["run_id"]
    if (
        not isinstance(run_id, str)
        or len(run_id) != 32
        or any(char not in "0123456789abcdef" for char in run_id)
    ):
        raise ValueError("Ponteiro da previsão inválido.")
    return forecast_dir / "runs" / run_id


def publish_forecast(forecast_dir: Path, frames: dict[str, pd.DataFrame]) -> Path:
    """Grava tudo antes de mudar o ponteiro que os leitores usam."""
    missing = set(FORECAST_FILES) - set(frames)
    if missing:
        raise ValueError(f"Tabelas ausentes: {sorted(missing)}")
    runs = forecast_dir / "runs"
    runs.mkdir(parents=True, exist_ok=True)
    run_id = uuid4().hex
    staging = runs / f".{run_id}.staging"
    published = runs / run_id
    staging.mkdir()
    try:
        for name in FORECAST_FILES:
            frames[name].to_parquet(staging / f"{name}.parquet", index=False)
        staging.rename(published)
        pointer_tmp = forecast_dir / f".current.{run_id}.tmp"
        pointer_tmp.write_text(json.dumps({"run_id": run_id}), encoding="utf-8")
        os.replace(pointer_tmp, forecast_dir / "current.json")
    except Exception:
        (forecast_dir / f".current.{run_id}.tmp").unlink(missing_ok=True)
        shutil.rmtree(staging, ignore_errors=True)
        shutil.rmtree(published, ignore_errors=True)
        raise
    return published
