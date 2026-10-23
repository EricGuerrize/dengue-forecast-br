select
    station_id,
    cast(
        date_trunc('week', cast(date as date) + interval 1 day) - interval 1 day
        as date
    ) as week_start,
    sum(precip_mm) as precip_mm,
    avg(temp_mean_c) as temp_mean_c,
    avg(temp_max_c) as temp_max_c,
    avg(temp_min_c) as temp_min_c,
    avg(humidity_mean_pct) as humidity_mean_pct
from {{ source('bronze', 'bronze_inmet') }}
where date is not null
  and station_id is not null
group by 1, 2
