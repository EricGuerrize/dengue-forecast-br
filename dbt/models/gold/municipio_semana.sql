select
    c.geocode,
    c.municipio_nome,
    c.uf,
    c.week_start,
    c.se,
    c.casos,
    c.casos_est,
    p.populacao_2022,
    c.casos / p.populacao_2022 * 100000 as incidencia_100k,
    c.p_inc100k as incidencia_infodengue,
    c.nivel,
    e.station_id,
    e.distance_km,
    w.precip_mm,
    w.temp_mean_c,
    w.humidity_mean_pct
from {{ ref('infodengue') }} as c
inner join {{ ref('populacao') }} as p
    on c.geocode = p.codigo_ibge
left join {{ ref('estacao_municipio') }} as e
    on c.geocode = e.codigo_ibge
left join {{ ref('inmet_weekly') }} as w
    on w.station_id = e.station_id
    and w.week_start = c.week_start
