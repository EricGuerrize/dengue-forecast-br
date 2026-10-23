"""Validação Pandera bronze."""

from __future__ import annotations

import pandas as pd
import pytest
from pandera.errors import SchemaErrors

from dengue_forecast.schemas.bronze import validate_ibge_municipios, validate_infodengue


def test_infodengue_schema_ok(tiny_infodengue_df: pd.DataFrame) -> None:
    out = validate_infodengue(tiny_infodengue_df)
    assert len(out) == 2


def test_infodengue_schema_rejects_negative_cases(tiny_infodengue_df: pd.DataFrame) -> None:
    bad = tiny_infodengue_df.copy()
    bad.loc[0, "casos"] = -1
    with pytest.raises(SchemaErrors):
        validate_infodengue(bad)


def test_ibge_municipios_schema() -> None:
    df = pd.DataFrame(
        {"codigo_ibge": [5103403], "nome": ["Cuiabá"], "uf": ["MT"]},
    )
    assert len(validate_ibge_municipios(df)) == 1
