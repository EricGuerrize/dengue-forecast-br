select
    cast(codigo_ibge as bigint) as codigo_ibge,
    nome,
    cast(latitude as double) as latitude,
    cast(longitude as double) as longitude
from read_csv_auto('{{ env_var("DFC_CENTROIDE_CSV") }}', header = true)
