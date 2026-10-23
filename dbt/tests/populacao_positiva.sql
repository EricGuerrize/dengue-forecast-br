select geocode, populacao_2022
from {{ ref('municipio_semana') }}
where populacao_2022 is null
   or populacao_2022 <= 0
