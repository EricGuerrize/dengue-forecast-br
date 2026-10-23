"""População IBGE (agregado 4714) e tabela de referência de MT."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from dengue_forecast.ingest.ibge import ingest_ibge, parse_ibge_populacao
from dengue_forecast.ingest.ibge_codes import mt_geocodes
from dengue_forecast.warehouse import Warehouse

REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURE = REPO_ROOT / "tests" / "fixtures" / "ibge_populacao_4714.json"
REFERENCIA = REPO_ROOT / "data" / "reference" / "populacao_mt_2022.csv"


def test_parse_ibge_populacao_cuiaba() -> None:
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    df = parse_ibge_populacao(payload, uf="MT")
    assert list(df.columns) == ["codigo_ibge", "nome", "uf", "populacao_2022"]
    row = df.loc[df["codigo_ibge"] == 5103403].iloc[0]
    assert row["nome"] == "Cuiabá"
    assert row["uf"] == "MT"
    assert int(row["populacao_2022"]) == 650877


def test_referencia_censo_2022_cobre_mt() -> None:
    df = pd.read_csv(REFERENCIA)
    assert len(df) == 141
    assert set(df["codigo_ibge"]) == set(mt_geocodes())
    cuiaba = int(df.loc[df["codigo_ibge"] == 5103403, "populacao_2022"].iloc[0])
    assert cuiaba == 650877
    assert (df["populacao_2022"] > 0).all()


class _FakeClient:
    def __init__(self, pop_payload: object, *, fail_pop: bool = False) -> None:
        self.pop_payload = pop_payload
        self.fail_pop = fail_pop

    def get_json(self, url: str, **kwargs: object) -> object:
        if "agregados" in url:
            if self.fail_pop:
                raise RuntimeError("ibge down")
            return self.pop_payload
        if "municipios" in url:
            return [{"id": 5103403, "nome": "Cuiabá"}]
        raise AssertionError(url)

    def close(self) -> None:
        return None


def test_ingest_ibge_usa_api_de_populacao(tmp_settings) -> None:
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    with Warehouse(tmp_settings.warehouse) as wh:
        summary = ingest_ibge(
            uf="MT",
            settings=tmp_settings,
            warehouse=wh,
            client=_FakeClient(payload),
        )
    assert summary["populacao_rows"] == 1
    assert summary["municipios"] == 1


def test_ingest_ibge_cai_para_referencia(tmp_settings) -> None:
    with Warehouse(tmp_settings.warehouse) as wh:
        summary = ingest_ibge(
            uf="MT",
            settings=tmp_settings,
            warehouse=wh,
            client=_FakeClient(None, fail_pop=True),
        )
    assert summary["populacao_rows"] == 141
