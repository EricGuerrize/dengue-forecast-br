"""Ingestão IBGE — lista de municípios e população."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from dengue_forecast.config import Settings, get_settings
from dengue_forecast.ingest.http import HttpClient
from dengue_forecast.ingest.ibge_codes import (
    SAMPLE_POPULACAO,
    mt_municipios_records,
)
from dengue_forecast.ingest.io_utils import write_bronze_parquet
from dengue_forecast.logging_setup import get_logger
from dengue_forecast.schemas.bronze import validate_ibge_municipios, validate_ibge_populacao
from dengue_forecast.warehouse import Warehouse

log = get_logger(__name__)

IBGE_MUNICIPIOS_UF = "https://servicodados.ibge.gov.br/api/v1/localidades/estados/{uf}/municipios"
# Censo 2022, variável 93 (população residente), municípios da UF.
IBGE_POPULACAO_URL = (
    "https://servicodados.ibge.gov.br/api/v3/agregados/4714/periodos/2022/"
    "variaveis/93?localidades=N6[N3[{code}]]"
)
_UF_IBGE = {"MT": 51}


def _municipios_from_api(client: HttpClient, uf: str) -> pd.DataFrame:
    data = client.get_json(IBGE_MUNICIPIOS_UF.format(uf=uf))
    assert isinstance(data, list)
    rows = [{"codigo_ibge": int(m["id"]), "nome": m["nome"], "uf": uf} for m in data]
    return pd.DataFrame(rows)


def _municipios_fallback(uf: str) -> pd.DataFrame:
    if uf != "MT":
        raise ValueError(f"Fallback estático só para MT (pedido: {uf})")
    return pd.DataFrame(mt_municipios_records())


def parse_ibge_populacao(payload: object, *, uf: str) -> pd.DataFrame:
    """Converte o JSON do agregado 4714 em linhas de população municipal."""
    if not isinstance(payload, list) or not payload:
        raise ValueError("Resposta IBGE de população vazia ou inesperada")
    resultados = payload[0].get("resultados") if isinstance(payload[0], dict) else None
    if not resultados:
        raise ValueError("Agregado IBGE sem resultados")
    series = resultados[0].get("series") or []
    suffix = f" - {uf}"
    rows: list[dict[str, str | int]] = []
    for item in series:
        localidade = item["localidade"]
        nome = str(localidade["nome"])
        if nome.endswith(suffix):
            nome = nome[: -len(suffix)]
        valor = item["serie"]["2022"]
        rows.append(
            {
                "codigo_ibge": int(localidade["id"]),
                "nome": nome,
                "uf": uf,
                "populacao_2022": int(valor),
            }
        )
    if not rows:
        raise ValueError("Agregado IBGE sem municípios")
    return pd.DataFrame(rows)


def _populacao_from_api(client: HttpClient, uf: str) -> pd.DataFrame:
    code = _UF_IBGE.get(uf)
    if code is None:
        raise ValueError(f"População IBGE ainda não mapeada para a UF {uf}")
    payload = client.get_json(IBGE_POPULACAO_URL.format(code=code))
    return parse_ibge_populacao(payload, uf=uf)


def _populacao_from_reference(settings: Settings, uf: str) -> pd.DataFrame:
    if uf != "MT":
        raise ValueError(f"Referência de população só cobre MT (pedido: {uf})")
    path = settings.root / "data" / "reference" / "populacao_mt_2022.csv"
    if not path.exists():
        raise FileNotFoundError(f"Referência de população ausente: {path}")
    return pd.read_csv(path)


def _populacao_from_sample(sample_dir: Path) -> pd.DataFrame:
    path = sample_dir / "ibge" / "populacao_sample.json"
    if path.exists():
        return pd.DataFrame(json.loads(path.read_text(encoding="utf-8")))
    rows = [
        {
            "codigo_ibge": code,
            "nome": next(r["nome"] for r in mt_municipios_records() if r["codigo_ibge"] == code),
            "uf": "MT",
            "populacao_2022": pop,
        }
        for code, pop in SAMPLE_POPULACAO.items()
    ]
    return pd.DataFrame(rows)


def ingest_ibge(
    *,
    uf: str = "MT",
    settings: Settings | None = None,
    client: HttpClient | None = None,
    warehouse: Warehouse | None = None,
    sample_dir: Path | None = None,
) -> dict[str, int]:
    """Ingere municípios e população (Censo 2022) para a UF."""
    settings = settings or get_settings()
    uf = uf.upper()
    owns_wh = warehouse is None
    owns_client = client is None and sample_dir is None
    warehouse = warehouse or Warehouse(settings.warehouse)
    client = client or (None if sample_dir else HttpClient(settings))

    try:
        if sample_dir is not None:
            mun_path = Path(sample_dir) / "ibge" / "municipios_mt.json"
            if mun_path.exists():
                municipios = pd.DataFrame(json.loads(mun_path.read_text(encoding="utf-8")))
            else:
                municipios = _municipios_fallback(uf)
            populacao = _populacao_from_sample(Path(sample_dir))
        else:
            assert client is not None
            try:
                municipios = _municipios_from_api(client, uf)
            except Exception as exc:  # noqa: BLE001
                log.warning("ibge_api_failed_using_fallback", error=str(exc))
                municipios = _municipios_fallback(uf)
            try:
                populacao = _populacao_from_api(client, uf)
            except Exception as exc:  # noqa: BLE001
                log.warning("ibge_populacao_api_failed_using_reference", error=str(exc))
                populacao = _populacao_from_reference(settings, uf)

        municipios = validate_ibge_municipios(municipios)
        populacao = validate_ibge_populacao(populacao)

        _, w1 = write_bronze_parquet(
            municipios,
            warehouse=warehouse,
            source="ibge",
            partition_key=f"municipios/{uf}",
            bronze_root=settings.bronze,
            partition_cols={"dataset": "municipios", "uf": uf},
        )
        _, w2 = write_bronze_parquet(
            populacao,
            warehouse=warehouse,
            source="ibge",
            partition_key=f"populacao/{uf}",
            bronze_root=settings.bronze,
            partition_cols={"dataset": "populacao", "uf": uf},
        )

        warehouse.register_parquet_view(
            "bronze_ibge_municipios",
            settings.bronze / "ibge" / "dataset=municipios" / "**" / "data.parquet",
        )
        warehouse.register_parquet_view(
            "bronze_ibge_populacao",
            settings.bronze / "ibge" / "dataset=populacao" / "**" / "data.parquet",
        )

        summary = {
            "municipios": len(municipios),
            "populacao_rows": len(populacao),
            "wrote": int(w1) + int(w2),
        }
        log.info("ibge_done", **summary)
        return summary
    finally:
        if owns_client and client is not None:
            client.close()
        if owns_wh:
            warehouse.close()
