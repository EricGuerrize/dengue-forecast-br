"""CLI Typer — ponto de entrada `dfc`."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console

from dengue_forecast import __version__
from dengue_forecast.config import get_settings
from dengue_forecast.logging_setup import configure_logging, get_logger

app = typer.Typer(
    name="dfc",
    help="dengue-forecast-br — ingestão, previsão, nowcast e ciclo semanal.",
    no_args_is_help=True,
    add_completion=False,
)
ingest_app = typer.Typer(help="Pipelines de ingestão para a camada bronze.", no_args_is_help=True)
app.add_typer(ingest_app, name="ingest")

console = Console()
log = get_logger(__name__)


def _bootstrap(verbose: bool) -> None:
    configure_logging("DEBUG" if verbose else "INFO")


@app.callback()
def main(
    verbose: Annotated[bool, typer.Option("--verbose", "-v", help="Log em nível DEBUG")] = False,
) -> None:
    """CLI do projeto dengue-forecast-br."""
    _bootstrap(verbose)


@app.command("version")
def version_cmd() -> None:
    """Mostra a versão do pacote."""
    console.print(f"dengue-forecast {__version__}")


@ingest_app.command("infodengue")
def ingest_infodengue_cmd(
    uf: Annotated[str, typer.Option(help="Sigla da UF (fase 1: MT)")] = "MT",
    start_year: Annotated[int, typer.Option(help="Ano inicial (SE)")] = 2019,
    end_year: Annotated[int, typer.Option(help="Ano final (SE)")] = 2025,
    sample_dir: Annotated[
        Path | None,
        typer.Option(help="Se definido, lê CSVs locais (offline / CI)"),
    ] = None,
    geocode: Annotated[
        list[int] | None,
        typer.Option(help="Filtra geocodes (repetível); default=todos MT"),
    ] = None,
) -> None:
    """Ingere casos semanais InfoDengue por município."""
    from dengue_forecast.ingest.infodengue import ingest_infodengue

    summary = ingest_infodengue(
        uf=uf,
        start_year=start_year,
        end_year=end_year,
        geocodes=geocode,
        sample_dir=sample_dir,
    )
    console.print(summary)


@ingest_app.command("inmet")
def ingest_inmet_cmd(
    year: Annotated[int, typer.Option(help="Ano do ZIP histórico INMET")],
    uf: Annotated[str, typer.Option(help="Sigla da UF (fase 1: MT)")] = "MT",
    sample_dir: Annotated[
        Path | None,
        typer.Option(help="Se definido, lê CSVs locais (offline / CI)"),
    ] = None,
    station: Annotated[
        list[str] | None,
        typer.Option(help="IDs de estação (ex. A901); default=estações MT conhecidas"),
    ] = None,
) -> None:
    """Ingere observações diárias INMET (ou sample offline)."""
    from dengue_forecast.ingest.inmet import ingest_inmet

    summary = ingest_inmet(
        year=year,
        uf=uf,
        station_ids=station,
        sample_dir=sample_dir,
    )
    console.print(summary)


@ingest_app.command("ibge")
def ingest_ibge_cmd(
    uf: Annotated[str, typer.Option(help="Sigla da UF")] = "MT",
    sample_dir: Annotated[
        Path | None,
        typer.Option(help="Se definido, lê JSON locais (offline / CI)"),
    ] = None,
) -> None:
    """Ingere municípios IBGE e população do Censo 2022."""
    from dengue_forecast.ingest.ibge import ingest_ibge

    summary = ingest_ibge(uf=uf, sample_dir=sample_dir)
    console.print(summary)


@ingest_app.command("sinan")
def ingest_sinan_cmd(
    year: Annotated[int, typer.Option(help="Ano das notificações SINAN")],
    uf: Annotated[str, typer.Option(help="Sigla da UF")] = "MT",
    sample_dir: Annotated[
        Path | None,
        typer.Option(help="Diretório sample (SINAN opcional / frequentemente ausente)"),
    ] = None,
) -> None:
    """Ingere SINAN via PySUS (opcional — FTP DATASUS pode falhar)."""
    from dengue_forecast.ingest.sinan import ingest_sinan

    summary = ingest_sinan(year=year, uf=uf, sample_dir=sample_dir)
    console.print(summary)


@ingest_app.command("sivep")
def ingest_sivep_cmd(
    uf: Annotated[str, typer.Option(help="Sigla da UF")] = "MT",
    year: Annotated[
        list[int] | None,
        typer.Option(help="Ano do arquivo SRAG (repetível). Default: ano atual e o anterior."),
    ] = None,
    sample_dir: Annotated[
        Path | None,
        typer.Option(help="Se definido, lê o agregado local e não baixa o OpenDataSUS"),
    ] = None,
) -> None:
    """Agrega SIVEP-Gripe por município e semana. Não grava linha nominal."""
    from dengue_forecast.ingest.sivep import ingest_sivep

    summary = ingest_sivep(
        uf=uf,
        years=tuple(year) if year else None,
        sample_dir=sample_dir,
    )
    console.print(summary)


@app.command("transform")
def transform_cmd() -> None:
    """Roda dbt build: bronze → silver/gold e testes de qualidade."""
    from dengue_forecast.transform import run_dbt_build

    run_dbt_build()
    console.print("[green]dbt build OK[/green] → schemas silver e gold")


@app.command("forecast")
def forecast_cmd() -> None:
    """Backtest e previsão 4 e 8 semanas à frente, a partir do gold."""
    from dengue_forecast.forecast import run_forecast

    summary = run_forecast()
    console.print(summary)
    console.print(f"[green]Previsão OK[/green] → {get_settings().forecast}")


@app.command("nowcast")
def nowcast_cmd(
    sample_dir: Annotated[
        Path | None,
        typer.Option(help="Prior de atraso, se ainda não houver SIVEP agregado"),
    ] = None,
) -> None:
    """Corrige as semanas recentes pelo atraso de notificação."""
    from dengue_forecast.nowcast import run_nowcast

    summary = run_nowcast(sample_dir=sample_dir)
    console.print(summary)
    console.print(f"[green]Nowcast OK[/green] → {summary['path']}")


@app.command("refresh")
def refresh_cmd(
    sample_dir: Annotated[
        Path | None,
        typer.Option(help="Ciclo offline com o sample. Sem isto, baixa MT ao vivo."),
    ] = None,
    backfill: Annotated[
        bool,
        typer.Option("--backfill", help="Pede o histórico desde 2019 mesmo se já houver bronze"),
    ] = False,
    serve: Annotated[
        bool,
        typer.Option("--serve", help="Sobe o flow Prefect: segunda às 08:00 em Cuiabá"),
    ] = False,
) -> None:
    """Ingestão, dbt, previsão e nowcast. Com --serve, agenda o ciclo."""
    if serve:
        from dengue_forecast.orchestrate.flow import serve_weekly

        console.print("Prefect no ar. O ciclo dispara segunda-feira às 08:00 (Cuiabá).")
        serve_weekly()
        return

    from dengue_forecast.orchestrate.weekly import run_weekly

    summary = run_weekly(sample_dir=sample_dir, force_backfill=backfill)
    console.print(summary)
    console.print("[green]Ciclo semanal OK[/green]")


@app.command("viz")
def viz_cmd(
    port: Annotated[int, typer.Option(help="Porta HTTP. Também lê a env PORT.")] = 8501,
) -> None:
    """Abre a tela Streamlit com histórico, previsão e alerta."""
    import os
    import subprocess
    import sys

    app_path = Path(__file__).resolve().parent / "viz" / "app.py"
    bind = os.environ.get("PORT", str(port))
    env = os.environ.copy()
    env["STREAMLIT_BROWSER_GATHER_USAGE_STATS"] = "false"
    subprocess.run(
        [
            sys.executable,
            "-m",
            "streamlit",
            "run",
            str(app_path),
            "--server.address",
            "0.0.0.0",
            "--server.port",
            bind,
            "--server.headless",
            "true",
        ],
        check=True,
        env=env,
    )


@app.command("demo")
def demo_cmd(
    sample_dir: Annotated[Path, typer.Option(help="Diretório com dados sample offline")] = Path(
        "data/sample"
    ),
    output_dir: Annotated[Path, typer.Option(help="Onde salvar o PNG e CSVs exploratórios")] = Path(
        "data/artifacts"
    ),
) -> None:
    """Roda demo offline: ingest sample + gráfico Cuiabá casos×chuva."""
    from dengue_forecast.demo.explore import run_demo

    settings = get_settings()
    path = run_demo(sample_dir=sample_dir, output_dir=output_dir, settings=settings)
    console.print(f"[green]Demo OK[/green] → {path}")


if __name__ == "__main__":
    app()
