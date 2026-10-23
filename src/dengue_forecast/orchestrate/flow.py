"""Flow Prefect do ciclo semanal. O trabalho em si está em `weekly.run_weekly`."""

from __future__ import annotations

from dengue_forecast.orchestrate.weekly import WEEKLY_CRON, run_weekly


def serve_weekly() -> None:
    """Sobe um processo local que dispara o ciclo toda segunda às 08:00 em Cuiabá."""
    try:
        from prefect import flow
    except ImportError as exc:
        raise RuntimeError(
            "Prefect não está instalado. Use: pip install -e '.[orchestrate]'"
        ) from exc

    @flow(name="dengue-semanal")
    def dengue_semanal() -> dict[str, object]:
        return run_weekly()

    dengue_semanal.serve(name="mt-segunda", cron=WEEKLY_CRON)
