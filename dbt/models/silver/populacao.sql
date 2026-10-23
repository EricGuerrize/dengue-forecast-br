select
    cast(codigo_ibge as bigint) as codigo_ibge,
    nome,
    uf,
    cast(populacao_2022 as bigint) as populacao_2022
from {{ source('bronze', 'bronze_ibge_populacao') }}
where populacao_2022 > 0
qualify row_number() over (
    partition by cast(codigo_ibge as bigint)
    order by populacao_2022 desc
) = 1
