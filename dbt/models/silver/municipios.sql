select
    cast(m.codigo_ibge as bigint) as codigo_ibge,
    m.nome,
    m.uf,
    c.latitude,
    c.longitude
from {{ source('bronze', 'bronze_ibge_municipios') }} as m
left join {{ ref('municipio_centroide') }} as c
    on cast(m.codigo_ibge as bigint) = c.codigo_ibge
