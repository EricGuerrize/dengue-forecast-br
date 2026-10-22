"""Validação Pandera dos DataFrames bronze."""

from __future__ import annotations

import pandas as pd
import pandera.pandas as pa
from pandera.typing import Series


class InfodengueBronzeSchema(pa.DataFrameModel):
    geocode: Series[int] = pa.Field(ge=1100000, le=5300108)
    municipio_nome: Series[str]
    data_ini_se: Series[pd.Timestamp]
    se: Series[int] = pa.Field(ge=200001, le=210053)
    casos: Series[float] = pa.Field(ge=0, nullable=True)
    casos_est: Series[float] = pa.Field(ge=0, nullable=True)
    p_inc100k: Series[float] = pa.Field(ge=0, nullable=True)
    nivel: Series[int] = pa.Field(ge=1, le=4, nullable=True)
    pop: Series[float] = pa.Field(ge=0, nullable=True)
    tempmed: Series[float] = pa.Field(nullable=True)
    umidmed: Series[float] = pa.Field(nullable=True)
    uf: Series[str] = pa.Field(isin=["MT"])

    class Config:
        coerce = True
        strict = False


class InmetDailySchema(pa.DataFrameModel):
    station_id: Series[str]
    station_name: Series[str] = pa.Field(nullable=True)
    uf: Series[str]
    latitude: Series[float] = pa.Field(nullable=True)
    longitude: Series[float] = pa.Field(nullable=True)
    date: Series[pd.Timestamp]
    precip_mm: Series[float] = pa.Field(ge=0, nullable=True)
    temp_mean_c: Series[float] = pa.Field(nullable=True)
    temp_max_c: Series[float] = pa.Field(nullable=True)
    temp_min_c: Series[float] = pa.Field(nullable=True)
    humidity_mean_pct: Series[float] = pa.Field(ge=0, le=100, nullable=True)

    class Config:
        coerce = True
        strict = False


class IbgeMunicipioSchema(pa.DataFrameModel):
    codigo_ibge: Series[int] = pa.Field(ge=1100000, le=5300108)
    nome: Series[str]
    uf: Series[str]

    class Config:
        coerce = True


class IbgePopulacaoSchema(pa.DataFrameModel):
    codigo_ibge: Series[int] = pa.Field(ge=1100000, le=5300108)
    nome: Series[str]
    uf: Series[str]
    populacao_2022: Series[int] = pa.Field(ge=0)

    class Config:
        coerce = True


def validate_infodengue(df: pd.DataFrame) -> pd.DataFrame:
    return InfodengueBronzeSchema.validate(df, lazy=True)


def validate_inmet(df: pd.DataFrame) -> pd.DataFrame:
    return InmetDailySchema.validate(df, lazy=True)


def validate_ibge_municipios(df: pd.DataFrame) -> pd.DataFrame:
    return IbgeMunicipioSchema.validate(df, lazy=True)


def validate_ibge_populacao(df: pd.DataFrame) -> pd.DataFrame:
    return IbgePopulacaoSchema.validate(df, lazy=True)
