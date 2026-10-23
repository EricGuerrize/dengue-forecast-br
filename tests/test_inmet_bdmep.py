"""CSV horário do INMET vira uma linha por dia, com coordenada do próprio arquivo."""

from __future__ import annotations

import pytest

from dengue_forecast.ingest.inmet import _parse_bdmep_csv
from dengue_forecast.schemas.bronze import validate_inmet

_HEADER = ";".join(
    [
        "DATA (YYYY-MM-DD)",
        "HORA (UTC)",
        "PRECIPITAÇÃO TOTAL, HORÁRIO (mm)",
        "TEMPERATURA DO AR - BULBO SECO, HORARIA (°C)",
        "TEMPERATURA MÁXIMA NA HORA ANT. (AUT) (°C)",
        "TEMPERATURA MÍNIMA NA HORA ANT. (AUT) (°C)",
        "UMIDADE RELATIVA DO AR, HORARIA (%)",
    ]
)
_CSV = "\n".join(
    [
        "REGIAO:;CO",
        "UF:;MT",
        "ESTACAO:;TANGARA DA SERRA",
        "CODIGO (WMO):;A902",
        "LATITUDE:;-14.65",
        "LONGITUDE:;-57.43",
        "ALTITUDE:;321.00",
        "DATA DE FUNDACAO:;",
        _HEADER,
        "2019/01/01;0000 UTC;1.0;25.0;26.0;20.0;80",
        "2019/01/01;0100 UTC;2.0;27.0;28.0;21.0;70",
        "2019/01/02;0000 UTC;0.0;24.0;24.0;18.0;90",
        "",
    ]
)


def test_csv_horario_vira_um_dia_com_coordenada_do_arquivo() -> None:
    df = validate_inmet(_parse_bdmep_csv(_CSV, "A902", "MT"))
    assert len(df) == 2
    day = df[df["date"] == "2019-01-01"].iloc[0]
    assert day["precip_mm"] == pytest.approx(3.0)
    assert day["temp_mean_c"] == pytest.approx(26.0)
    assert day["temp_max_c"] == pytest.approx(28.0)
    assert day["temp_min_c"] == pytest.approx(20.0)
    assert day["humidity_mean_pct"] == pytest.approx(75.0)
    assert day["latitude"] == pytest.approx(-14.65)
    assert day["longitude"] == pytest.approx(-57.43)
    assert day["station_name"] == "TANGARA DA SERRA"
