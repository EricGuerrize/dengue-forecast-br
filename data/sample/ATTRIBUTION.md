# Atribuição dos dados em `data/sample/`

Amostra **agregada** (sem microdados individuais) para CI e `make demo` offline.

| Pasta | Conteúdo | Fonte | Observação |
|-------|----------|-------|------------|
| `infodengue/` | Casos semanais 2022–2024, 5 municípios MT (incl. Cuiabá `5103403`) | [InfoDengue API](https://info.dengue.mat.br/services/api) | Dados reais da API |
| `inmet/` | Série diária estação **A901 (Cuiabá)** 2022–2024 (chuva, temp., umidade) | Schema alinhado ao BDMEP/INMET; precip/temp nas coordenadas A901 via [Open-Meteo Archive](https://open-meteo.com/) | Portal INMET (`dadoshistoricos`) frequentemente indisponível em CI; o comando `dfc ingest inmet` usa o ZIP oficial quando a rede permite |
| `ibge/` | 141 municípios de MT + população 2022 do subset sample | Códigos IBGE oficiais; população Censo/estimativas públicas | Lista estática versionada no pacote como fallback |

## Ética

- Apenas contagens / indicadores agregados por município e semana.
- Nenhum registro individual (SINAN nominais, CPF, endereço, etc.) entra no repositório.
