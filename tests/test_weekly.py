"""Ciclo semanal: o que roda na primeira vez e o que roda na revisão."""

from __future__ import annotations

from dengue_forecast.orchestrate.weekly import WEEKLY_CRON, build_plan, refresh_years, run_weekly


def test_primeira_rodada_cobre_o_historico() -> None:
    assert refresh_years(has_history=False, backfill_start=2019, end_year=2025) == (
        2019,
        2020,
        2021,
        2022,
        2023,
        2024,
        2025,
    )


def test_rodada_seguinte_so_revisa_dois_anos() -> None:
    assert refresh_years(has_history=True, backfill_start=2019, end_year=2025) == (2024, 2025)


def test_cron_e_segunda_as_oito_em_cuiaba() -> None:
    assert WEEKLY_CRON == "0 12 * * 1"


def test_sample_fica_offline_nos_anos_do_recorte(sample_dir) -> None:
    plan = build_plan(sample_dir=sample_dir, has_history=False, end_year=2026)
    assert plan.live is False
    assert plan.years == (2022, 2023, 2024)


def test_backfill_ignora_historico_parcial() -> None:
    plan = build_plan(
        sample_dir=None,
        has_history=True,
        end_year=2026,
        backfill_start=2019,
        force_backfill=True,
    )
    assert plan.live is True
    assert plan.years[0] == 2019
    assert plan.years[-1] == 2026


def test_refresh_chama_a_cadeia_nessa_ordem(tmp_settings, sample_dir) -> None:
    calls: list[str] = []

    def step(name: str, result: dict | None = None):
        def _run(*_args, **_kwargs):
            calls.append(name)
            return {} if result is None else result

        return _run

    summary = run_weekly(
        settings=tmp_settings,
        sample_dir=sample_dir,
        steps={
            "ibge": step("ibge", {"rows": 5}),
            "infodengue": step("infodengue", {"rows": 10}),
            "inmet": step("inmet", {"rows": 3}),
            "sivep": step("sivep", {"rows": 4, "status": "ok"}),
            "transform": step("transform"),
            "forecast": step("forecast", {"municipios": 5}),
            "nowcast": step("nowcast", {"rows": 8}),
        },
    )
    assert calls == ["ibge", "infodengue", "inmet", "sivep", "transform", "forecast", "nowcast"]
    assert summary["nowcast"]["rows"] == 8
