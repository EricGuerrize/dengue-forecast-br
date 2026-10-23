with src as (
    select
        cast(geocode as bigint) as geocode,
        municipio_nome,
        uf,
        cast(data_ini_se as date) as data_ini_se,
        cast(se as integer) as se,
        cast(casos as double) as casos,
        cast(casos_est as double) as casos_est,
        cast(p_inc100k as double) as p_inc100k,
        cast(nivel as integer) as nivel
    from {{ source('bronze', 'bronze_infodengue') }}
    where geocode is not null
      and data_ini_se is not null
),

norm as (
    select
        geocode,
        municipio_nome,
        uf,
        -- Semana epidemiológica InfoDengue começa no domingo (pandas W-SAT).
        cast(
            date_trunc('week', data_ini_se + interval 1 day) - interval 1 day
            as date
        ) as week_start,
        se,
        casos,
        casos_est,
        p_inc100k,
        nivel
    from src
)

select
    geocode,
    municipio_nome,
    uf,
    week_start,
    se,
    casos,
    casos_est,
    p_inc100k,
    nivel
from norm
qualify row_number() over (
    partition by geocode, week_start
    order by se desc
) = 1
