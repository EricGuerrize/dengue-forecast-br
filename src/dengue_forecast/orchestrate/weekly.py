"""Um ciclo: bronze recente, silver/gold, previsão e nowcast.

A primeira rodada pede o histórico desde 2019. As seguintes revisam só o ano
corrente e o anterior, porque o InfoDengue reescreve as últimas semanas.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from dengue_forecast.config import Settings, get_settings
from dengue_forecast.logging_setup import get_logger
from dengue_forecast.warehouse import Warehouse

log = get_logger(__name__)

# Segunda-feira 12:00 UTC = 08:00 em Cuiabá (America/Cuiaba, UTC−4, sem horário de verão).
WEEKLY_CRON = "0 12 * * 1"
SAMPLE_YEARS = (2022, 2023, 2024)

Step = Callable[..., dict]


@dataclass(frozen=True)
class RefreshPlan:
    live: bool
    years: tuple[int, ...]


def refresh_years(*, has_history: bool, backfill_start: int, end_year: int) -> tuple[int, ...]:
    if end_year < backfill_start:
        raise ValueError(f"Ano final {end_year} é anterior ao início {backfill_start}.")
    if not has_history:
        return tuple(range(backfill_start, end_year + 1))
    start = max(backfill_start, end_year - 1)
    return tuple(range(start, end_year + 1))


def build_plan(
    *,
    sample_dir: Path | None,
    has_history: bool,
    end_year: int,
    backfill_start: int = 2019,
    force_backfill: bool = False,
) -> RefreshPlan:
    if sample_dir is not None:
        return RefreshPlan(live=False, years=SAMPLE_YEARS)
    history = has_history and not force_backfill
    return RefreshPlan(
        live=True,
        years=refresh_years(
            has_history=history,
            backfill_start=backfill_start,
            end_year=end_year,
        ),
    )


def warehouse_has_source(settings: Settings, source: str) -> bool:
    if not settings.warehouse.exists():
        return False
    with Warehouse(settings.warehouse) as warehouse:
        row = warehouse.con.execute(
            "SELECT 1 FROM meta.ingestion_manifest WHERE source = ? LIMIT 1",
            [source],
        ).fetchone()
    return row is not None


def _step_ibge(*, settings: Settings, sample_dir: Path | None, **_: object) -> dict:
    from dengue_forecast.ingest.ibge import ingest_ibge

    return ingest_ibge(uf="MT", sample_dir=sample_dir, settings=settings)


def _step_infodengue(
    *,
    settings: Settings,
    sample_dir: Path | None,
    plan: RefreshPlan,
    **_: object,
) -> dict:
    from dengue_forecast.ingest.infodengue import ingest_infodengue

    geocodes = None
    if sample_dir is not None:
        geocodes = sorted(int(path.stem) for path in (sample_dir / "infodengue").glob("*.csv"))
    return ingest_infodengue(
        uf="MT",
        start_year=plan.years[0],
        end_year=plan.years[-1],
        geocodes=geocodes,
        sample_dir=sample_dir,
        settings=settings,
    )


def _step_inmet(
    *,
    settings: Settings,
    sample_dir: Path | None,
    plan: RefreshPlan,
    **_: object,
) -> dict:
    from dengue_forecast.ingest.inmet import ingest_inmet

    wrote = rows = stations = 0
    failed: list[int] = []
    for year in plan.years:
        try:
            summary = ingest_inmet(year=year, uf="MT", sample_dir=sample_dir, settings=settings)
        except Exception as exc:  # noqa: BLE001 — um ano sem ZIP não cancela o ciclo
            if sample_dir is not None:
                raise
            log.warning("weekly_inmet_failed", year=year, error=str(exc))
            failed.append(year)
            continue
        wrote += int(summary.get("wrote", 0))
        rows += int(summary.get("rows", 0))
        stations += int(summary.get("stations", 0))
    return {"wrote": wrote, "rows": rows, "stations": stations, "failed_years": failed}


def _step_sivep(
    *,
    settings: Settings,
    sample_dir: Path | None,
    plan: RefreshPlan,
    **_: object,
) -> dict:
    from dengue_forecast.ingest.sivep import ingest_sivep

    years = plan.years[-2:]
    try:
        summary = ingest_sivep(
            uf="MT",
            years=years,
            sample_dir=sample_dir,
            settings=settings,
        )
    except Exception as exc:  # noqa: BLE001 — SRAG é complemento; dengue segue sem ele
        if sample_dir is not None:
            raise
        log.warning("weekly_sivep_failed", error=str(exc))
        return {"status": "skipped", "rows": 0, "reason": str(exc)}
    return summary


def _step_transform(*, settings: Settings, **_: object) -> dict:
    from dengue_forecast.transform import run_dbt_build

    run_dbt_build(settings)
    return {"status": "ok"}


def _step_forecast(*, settings: Settings, **_: object) -> dict:
    from dengue_forecast.forecast import run_forecast

    return run_forecast(settings)


def _step_nowcast(*, settings: Settings, sample_dir: Path | None, **_: object) -> dict:
    from dengue_forecast.nowcast import run_nowcast

    return run_nowcast(settings, sample_dir=sample_dir)


def default_steps() -> dict[str, Step]:
    return {
        "ibge": _step_ibge,
        "infodengue": _step_infodengue,
        "inmet": _step_inmet,
        "sivep": _step_sivep,
        "transform": _step_transform,
        "forecast": _step_forecast,
        "nowcast": _step_nowcast,
    }


def run_weekly(
    *,
    settings: Settings | None = None,
    sample_dir: Path | None = None,
    end_year: int | None = None,
    backfill_start: int = 2019,
    force_backfill: bool = False,
    steps: dict[str, Step] | None = None,
) -> dict[str, object]:
    """Roda a cadeia inteira. `steps` existe para o teste fixar a ordem."""
    settings = settings or get_settings()
    end = end_year if end_year is not None else date.today().year
    has_history = False if steps is not None else warehouse_has_source(settings, "infodengue")
    plan = build_plan(
        sample_dir=sample_dir,
        has_history=has_history,
        end_year=end,
        backfill_start=backfill_start,
        force_backfill=force_backfill,
    )
    pipeline = steps or default_steps()
    order = ("ibge", "infodengue", "inmet", "sivep", "transform", "forecast", "nowcast")
    summary: dict[str, object] = {"years": plan.years, "live": plan.live}
    kwargs = {"settings": settings, "sample_dir": sample_dir, "plan": plan}
    for name in order:
        log.info("weekly_step", step=name, years=plan.years, live=plan.live)
        summary[name] = pipeline[name](**kwargs)
    log.info("weekly_done", years=plan.years, live=plan.live)
    return summary
