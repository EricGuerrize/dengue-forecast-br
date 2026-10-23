with ordered as (
    select
        geocode,
        week_start,
        lag(week_start) over (
            partition by geocode
            order by week_start
        ) as prev_week
    from {{ ref('municipio_semana') }}
)

select geocode, prev_week, week_start
from ordered
where prev_week is not null
  and date_diff('day', prev_week, week_start) <> 7
