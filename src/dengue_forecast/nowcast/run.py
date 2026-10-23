"""Grava o nowcast da série de dengue que já está em `data/forecast/`."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from dengue_forecast.config import Settings, get_settings
from dengue_forecast.forecast.storage import active_dir
from dengue_forecast.logging_setup import get_logger
from dengue_forecast.nowcast.delay import empirical_cdf, nowcast_cases

log = get_logger(__name__)


def load_delay_counts(settings: Settings, sample_dir: Path | None = None) -> pd.DataFrame:
    """Usa o atraso agregado do SIVEP se existir; senão, o prior do sample."""
    produced = settings.forecast / "srag_atraso.parquet"
    if produced.exists():
        return pd.read_parquet(produced)
    bundled = Path(sample_dir) if sample_dir else settings.root / "data" / "sample"
    csv_path = bundled / "srag" / "atraso.csv"
    if not csv_path.exists():
        raise FileNotFoundError(
            f"Sem distribuição de atraso em {produced} nem em {csv_path}. Rode `dfc ingest sivep`."
        )
    return pd.read_csv(csv_path)


def run_nowcast(
    settings: Settings | None = None,
    *,
    sample_dir: Path | None = None,
    as_of: pd.Timestamp | None = None,
    min_fraction: float = 0.25,
) -> dict[str, int | str]:
    settings = settings or get_settings()
    history_path = active_dir(settings.forecast) / "history.parquet"
    if not history_path.exists():
        raise FileNotFoundError(f"Histórico ausente ({history_path}). Rode `dfc forecast` antes.")

    history = pd.read_parquet(history_path)
    delay = load_delay_counts(settings, sample_dir)
    cdf = empirical_cdf(delay)
    # A data de hoje, não a última semana do arquivo. Um sample de 2024 visto em
    # 2026 já passou da janela de atraso; inflar essa semana trataria número
    # revisado como se ainda estivesse chegando notificação.
    if as_of is None:
        as_of = pd.Timestamp.today().normalize()
    corrected = nowcast_cases(history, cdf, as_of=pd.Timestamp(as_of), min_fraction=min_fraction)

    out = active_dir(settings.forecast)
    out.mkdir(parents=True, exist_ok=True)
    path = out / "nowcast.parquet"
    corrected.to_parquet(path, index=False)
    summary: dict[str, int | str] = {"rows": len(corrected), "path": str(path)}
    log.info("nowcast_done", **summary)
    return summary
