select geocode, week_start, incidencia_100k, casos, populacao_2022
from {{ ref('municipio_semana') }}
where abs(incidencia_100k - casos / populacao_2022 * 100000) > 0.001
