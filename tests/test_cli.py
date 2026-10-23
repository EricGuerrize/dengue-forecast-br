"""Smoke tests da CLI."""

from __future__ import annotations

from typer.testing import CliRunner

from dengue_forecast.cli import app

runner = CliRunner()


def test_version() -> None:
    result = runner.invoke(app, ["version"])
    assert result.exit_code == 0
    assert "0.1.0" in result.stdout


def test_ingest_help() -> None:
    result = runner.invoke(app, ["ingest", "--help"])
    assert result.exit_code == 0
    assert "infodengue" in result.stdout
    assert "inmet" in result.stdout
    assert "ibge" in result.stdout
    assert "sinan" in result.stdout
    assert "sivep" in result.stdout


def test_refresh_help() -> None:
    result = runner.invoke(app, ["refresh", "--help"])
    assert result.exit_code == 0
    assert "backfill" in result.stdout
    assert "serve" in result.stdout
