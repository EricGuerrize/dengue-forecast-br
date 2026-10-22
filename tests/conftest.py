"""Fixtures compartilhadas — sempre offline."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from dengue_forecast.config import Settings

REPO_ROOT = Path(__file__).resolve().parents[1]
SAMPLE_DIR = REPO_ROOT / "data" / "sample"


@pytest.fixture
def repo_root() -> Path:
    return REPO_ROOT


@pytest.fixture
def sample_dir() -> Path:
    assert SAMPLE_DIR.exists(), "data/sample deve estar commitado"
    return SAMPLE_DIR


@pytest.fixture
def tmp_settings(tmp_path: Path) -> Settings:
    data = tmp_path / "data"
    data.mkdir()
    return Settings(
        repo_root=REPO_ROOT,
        data_dir=data,
        warehouse_path=data / "warehouse.duckdb",
    )


@pytest.fixture
def tiny_infodengue_df() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "geocode": [5103403, 5103403],
            "municipio_nome": ["Cuiabá", "Cuiabá"],
            "data_ini_se": pd.to_datetime(["2023-01-01", "2023-01-08"]),
            "se": [202301, 202302],
            "casos": [9.0, 19.0],
            "casos_est": [9.0, 19.0],
            "p_inc100k": [1.4, 3.0],
            "nivel": [1, 2],
            "pop": [618124.0, 618124.0],
            "tempmed": [26.0, 26.3],
            "umidmed": [78.0, 77.0],
            "uf": ["MT", "MT"],
        }
    )
