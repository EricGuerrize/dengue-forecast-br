select geocode, station_id, distance_km
from {{ ref('municipio_semana') }}
where station_id is not null
  and (
      distance_km is null
      or distance_km > {{ var('max_station_distance_km') }}
  )
