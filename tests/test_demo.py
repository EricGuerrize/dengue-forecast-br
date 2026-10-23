"""Demo offline gera artefato PNG."""

from __future__ import annotations

from pathlib import Path

from dengue_forecast.demo.explore import run_demo


def test_run_demo_creates_chart(tmp_settings, sample_dir, tmp_path: Path) -> None:
    out = tmp_path / "artifacts"
    png = run_demo(sample_dir=sample_dir, output_dir=out, settings=tmp_settings)
    assert png.exists()
    assert png.stat().st_size > 10_000
    assert (out / "cuiaba_lag_correlation.csv").exists()
