select geocode, week_start
from {{ ref('municipio_semana') }}
group by 1, 2
having count(*) > 1
