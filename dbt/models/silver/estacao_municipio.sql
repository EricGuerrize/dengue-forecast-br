with stations as (
    select distinct
        station_id,
        cast(latitude as double) as latitude,
        cast(longitude as double) as longitude
    from {{ source('bronze', 'bronze_inmet') }}
    where latitude is not null
      and longitude is not null
),

dist as (
    select
        m.codigo_ibge,
        s.station_id,
        2 * 6371 * asin(sqrt(
            pow(sin(radians(s.latitude - m.latitude) / 2), 2)
            + cos(radians(m.latitude)) * cos(radians(s.latitude))
            * pow(sin(radians(s.longitude - m.longitude) / 2), 2)
        )) as distance_km
    from {{ ref('municipios') }} as m
    cross join stations as s
    where m.latitude is not null
      and m.longitude is not null
),

ranked as (
    select
        codigo_ibge,
        station_id,
        distance_km,
        row_number() over (
            partition by codigo_ibge
            order by distance_km
        ) as rn
    from dist
)

select
    codigo_ibge,
    station_id,
    distance_km
from ranked
where rn = 1
  and distance_km <= {{ var('max_station_distance_km') }}
