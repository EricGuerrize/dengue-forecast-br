"""SIVEP-Gripe entra só como contagem município × semana. Sem linha nominal."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd

from dengue_forecast.ingest.sivep import (
    aggregate_line_list,
    ingest_sivep,
    ingest_sivep_file,
    latest_direct_url,
    municipio_geocode7,
    pick_srag_resource,
)


def _nominal() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "NM_PACIENT": ["Ana", "Bia", "Caio", "Davi"],
            "DT_SIN_PRI": ["2024-01-02", "2024-01-03", "2024-01-10", "2024-01-03"],
            "DT_NOTIFIC": ["2024-01-05", "2024-01-04", "2024-01-20", "2024-01-09"],
            "CO_MUN_RES": [5103403, 5103403, 5103403, 5103403],
            "CLASSI_FIN": [5, 5, 1, 2],
            "PCR_VSR": [pd.NA, pd.NA, pd.NA, 1],
            "SG_UF_NOT": ["MT", "MT", "MT", "MT"],
        }
    )


def test_lista_nominal_vira_contagem_sem_pessoa() -> None:
    casos, atraso = aggregate_line_list(_nominal())
    assert "NM_PACIENT" not in casos.columns
    assert set(casos.columns) <= {
        "geocode",
        "municipio_nome",
        "week_start",
        "virus",
        "casos",
        "uf",
    }
    semana = pd.Timestamp("2023-12-31")
    covid = casos[(casos["virus"] == "covid") & (casos["week_start"] == semana)]
    assert int(covid["casos"].iloc[0]) == 2
    flu = casos[casos["virus"] == "influenza"]
    assert pd.Timestamp(flu["week_start"].iloc[0]) == pd.Timestamp("2024-01-07")
    assert int(flu["casos"].iloc[0]) == 1
    vsr = casos[casos["virus"] == "vsr"]
    assert int(vsr["casos"].iloc[0]) == 1
    assert int(atraso.loc[atraso["delay_weeks"] == 0, "n"].iloc[0]) == 3
    assert int(atraso.loc[atraso["delay_weeks"] == 1, "n"].iloc[0]) == 1


def test_csv_nominal_nao_vaza_para_o_parquet(tmp_path: Path, tmp_settings) -> None:
    csv_path = tmp_path / "srag.csv"
    csv_path.write_text(
        "NM_PACIENT;DT_SIN_PRI;DT_NOTIFIC;CO_MUN_RES;CLASSI_FIN;SG_UF_NOT\n"
        "Ana;2024-01-02;2024-01-05;5103403;5;MT\n"
        "Bia;2024-01-02;2024-01-05;1100205;5;RO\n",
        encoding="utf-8",
    )
    summary = ingest_sivep_file(csv_path, settings=tmp_settings, uf="MT")
    assert summary["rows"] == 1
    casos = pd.read_parquet(tmp_settings.bronze / "srag" / "uf=MT" / "data.parquet")
    assert "NM_PACIENT" not in casos.columns
    assert list(casos["geocode"]) == [5103403]
    assert list(casos["virus"]) == ["covid"]


def test_sample_offline_grava_agregado(tmp_settings, sample_dir: Path) -> None:
    summary = ingest_sivep(settings=tmp_settings, sample_dir=sample_dir, uf="MT")
    assert summary["status"] == "ok"
    assert summary["rows"] > 0
    casos = pd.read_parquet(tmp_settings.bronze / "srag" / "uf=MT" / "data.parquet")
    assert {"geocode", "week_start", "virus", "casos", "uf"} <= set(casos.columns)
    assert "NM_PACIENT" not in casos.columns


def test_codigo_de_seis_digitos_ganha_o_digito_de_cuiaba() -> None:
    assert municipio_geocode7(510340) == 5103403
    assert municipio_geocode7(5103403) == 5103403
    assert municipio_geocode7("241120") != 5103403


def test_data_iso_com_hora_e_codigo_curto() -> None:
    raw = pd.DataFrame(
        {
            "DT_SIN_PRI": ["2025-07-19T00:00:00.000Z"],
            "DT_NOTIFIC": ["2025-07-23T00:00:00.000Z"],
            "CO_MUN_RES": [510340],
            "CLASSI_FIN": [5],
            "SG_UF_NOT": ["MT"],
        }
    )
    casos, atraso = aggregate_line_list(raw)
    assert int(casos["geocode"].iloc[0]) == 5103403
    assert pd.Timestamp(casos["week_start"].iloc[0]) == pd.Timestamp("2025-07-13")
    assert int(atraso.loc[atraso["delay_weeks"] == 0, "n"].iloc[0]) == 1


def test_residencia_fora_de_mt_nao_entra_na_contagem() -> None:
    raw = pd.DataFrame(
        {
            "DT_SIN_PRI": ["2025-07-19"],
            "DT_NOTIFIC": ["2025-07-23"],
            "CO_MUN_RES": [110020],
            "CLASSI_FIN": [5],
            "SG_UF_NOT": ["MT"],
        }
    )
    casos, _atraso = aggregate_line_list(raw)
    assert casos.empty
    assert municipio_geocode7(110020) == 1100205


def test_url_direta_usa_o_arquivo_mais_novo_que_existe() -> None:
    today = date(2026, 10, 23)
    known = "https://s3.sa-east-1.amazonaws.com/ckan.saude.gov.br/SRAG/2025/INFLUD25-19-10-2026.csv"

    def exists(url: str) -> bool:
        return url == known

    assert latest_direct_url(2025, today=today, exists=exists, window_days=10) == known


def test_escolhe_csv_do_ano_mais_recente() -> None:
    resources = [
        {
            "name": "INFLUD23-01-01-2024.csv",
            "url": "https://exemplo/a.csv",
            "metadata_modified": "2024-02-01T00:00:00",
        },
        {
            "name": "INFLUD24-15-01-2025.csv",
            "url": "https://exemplo/b.csv",
            "metadata_modified": "2025-01-15T00:00:00",
        },
        {
            "name": "dicionario-srag.pdf",
            "url": "https://exemplo/d.pdf",
            "metadata_modified": "2025-03-01T00:00:00",
        },
    ]
    assert pick_srag_resource(resources, year=2024) == "https://exemplo/b.csv"
