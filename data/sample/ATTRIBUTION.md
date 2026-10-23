# Atribuição dos dados em `data/sample/`

Amostra **agregada** (sem microdados individuais) para CI e `make demo` offline.

| Pasta | Conteúdo | Fonte | Observação |
|-------|----------|-------|------------|
| `infodengue/` | Casos semanais 2022–2024, 5 municípios MT (incl. Cuiabá `5103403`) | [InfoDengue API](https://info.dengue.mat.br/services/api) | Dados reais da API |
| `inmet/` | Série diária estação **A901 (Cuiabá)** 2022–2024 (chuva, temp., umidade) | Schema alinhado ao BDMEP/INMET; precip/temp nas coordenadas A901 via [Open-Meteo Archive](https://open-meteo.com/) | Portal INMET (`dadoshistoricos`) frequentemente indisponível em CI; o comando `dfc ingest inmet` usa o ZIP oficial quando a rede permite |
| `ibge/` | 141 municípios de MT + população 2022 de 5 municípios | Códigos IBGE oficiais | O subset (Cuiabá 650.912) é o recorte do sample. A tabela completa do Censo 2022 está em `data/reference/populacao_mt_2022.csv` |

## `data/reference/`

| Arquivo | Conteúdo | Fonte |
|---------|----------|-------|
| `populacao_mt_2022.csv` | População residente dos 141 municípios de MT | [IBGE agregado 4714](https://servicodados.ibge.gov.br/api/v3/agregados/4714/periodos/2022/variaveis/93?localidades=N6[N3[51]]), variável 93, ano 2022. Cuiabá = 650.877 |
| `municipio_centroide_mt.csv` | Latitude/longitude do centróide municipal | [Municipios-Brasileiros](https://github.com/kelvins/Municipios-Brasileiros) (código IBGE, filtrado para os 141 municípios do Censo) |

| `srag/` | Contagens ilustrativas de SRAG (covid, influenza, VSR) e um prior de atraso de notificação | Prior, não extrato do OpenDataSUS | `casos.csv` serve para a tela offline. `atraso.csv` diz que 40% dos casos aparecem na semana do sintoma, 70% até a semana seguinte, 85% em duas, 95% em três e 100% em quatro. `dfc ingest sivep` sem `--sample-dir` substitui os dois pelo agregado do [OpenDataSUS](https://opendatasus.saude.gov.br/dataset/srag-2021-a-2024). A lista nominal não é gravada. |

## Ética

- Apenas contagens / indicadores agregados por município e semana.
- Nenhum registro individual (SINAN nominais, CPF, endereço, etc.) entra no repositório.
