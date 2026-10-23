# Ciclo semanal, SRAG e nowcast

A fase 3 deixou a previsão e a tela prontas em cima do sample. Faltava repetir isso toda semana, ler o SIVEP-Gripe sem guardar ficha de paciente, e corrigir as semanas em que a notificação ainda não fechou.

## Como rodar

Offline, com o sample de cinco municípios:

```bash
source .venv/bin/activate
make refresh
make viz
```

`make refresh` chama `dfc refresh --sample-dir data/sample`. A tela abre em [http://localhost:8501](http://localhost:8501).

Para Mato Grosso inteiro, na rede:

```bash
dfc refresh --backfill
```

Isso pede InfoDengue de 2019 até o ano corrente, os ZIPs do INMET desses anos e o SRAG dos dois anos mais recentes. Uma segunda rodada, já com bronze no warehouse, revisa só o ano corrente e o anterior:

```bash
dfc refresh
```

O sample de cinco cidades também deixa marca no manifesto. Numa máquina que já rodou `make demo`, `dfc refresh` sem `--backfill` trataria esse recorte como histórico completo e pediria só dois anos. A carga inicial do estado usa `--backfill`.

## O que o ciclo faz, nesta ordem

1. IBGE. Municípios e população. No sample são as populações do recorte. Ao vivo entra o Censo 2022 dos 141 municípios (Cuiabá com 650.877 na tabela de referência).
2. InfoDengue, um pedido por município. Se um município não responde, o resumo conta `failed` e o ciclo segue para o próximo.
3. INMET, um ZIP por ano, estações A901, A902, A904 e A917. O nome e a coordenada saem do CSV (no arquivo de 2019, A902 é Tangará da Serra e A904 é Sorriso). A observação original é horária. O bronze guarda um dia: chuva somada, temperatura e umidade médias. Se o portal cair num ano, esse ano vai para `failed_years` e os outros continuam. No sample a única estação no arquivo é a A901.
4. SIVEP-Gripe, agregado. Detalhe abaixo.
5. `dbt build`, silver e gold, com os mesmos testes da fase 2.
6. Previsão. O mesmo backtest da fase 3: sazonal, SARIMA e LightGBM, horizontes de 4 e 8 semanas.
7. Nowcast, escrito em `data/forecast/nowcast.parquet`.

A tela lê os parquets. Ela não treina de novo.

## Por que a semana seguinte não repete o histórico inteiro

O InfoDengue reescreve as últimas semanas quando chega notificação atrasada. O passado distante quase não muda. Por isso `refresh_years` devolve 2019…ano corrente só quando o manifesto ainda não tem InfoDengue. Com histórico, devolve o ano corrente e o anterior. O cron é `0 12 * * 1`: segunda-feira às 12:00 UTC, que é 08:00 em Cuiabá. Cuiabá fica em UTC−4 o ano inteiro.

`dfc refresh` roda uma vez e termina. `dfc refresh --serve` sobe um processo Prefect com esse cron. O extra é separado, porque o Prefect puxa bastante dependência:

```bash
pip install -e '.[orchestrate]'
dfc refresh --serve
```

O processo precisa ficar ligado. Sem o extra, o mesmo comando cabe num cron do sistema, na mesma expressão `0 12 * * 1`.

## SIVEP-Gripe

O CSV nacional do OpenDataSUS é uma lista de pessoas. O código baixa o arquivo para um diretório temporário, lê em blocos de 100 mil linhas e fica só com data do sintoma, data da notificação, município de residência, UF, `CLASSI_FIN` e `PCR_VSR`. Soma por município, semana e vírus. Apaga o CSV. O parquet que fica tem `geocode`, `week_start`, `virus`, `casos`, `uf` e `fonte`. Nome de paciente não entra nas colunas lidas.

A classificação segue a ficha de SRAG: `CLASSI_FIN` 5 é covid, 1 é influenza, 2 com `PCR_VSR` igual a 1 é VSR. O restante fica `outros`.

A semana é a mesma do resto do projeto, de domingo a sábado. No teste, sintoma em 2 de janeiro de 2024 (terça) cai na semana que começa em 31 de dezembro de 2023. Dois casos de covid nessa semana, em Cuiabá, viram uma linha com `casos = 2`.

O catálogo é o pacote CKAN `srag-2019-a-2026`, na API `https://dadosabertos.saude.gov.br/api/3/action/package_show`. Em 23 de outubro de 2026 essa API respondeu `Server disconnected without sending a response`. O endereço antigo `opendatasus.saude.gov.br` devolve HTTP 302 para `dadosabertos.saude.gov.br`. Quando o catálogo cai, o código procura o CSV direto no S3, do dia de hoje para trás, no formato `INFLUD{aa}-{dd}-{mm}-{aaaa}.csv`. O objeto ausente responde 403. O que existe responde 200. O ciclo pede só os dois últimos anos. O arquivo é nacional e grande. O nowcast precisa da distribuição recente de atraso, e a tela precisa da contagem municipal dessa janela. Os anos anteriores de SRAG não alimentam o LightGBM.

O CSV traz o município com 6 dígitos. A dengue do projeto usa 7. O sétimo dígito é o módulo 10 do IBGE: 510340 vira 5103403, Cuiabá. A contagem municipal fica com residência em MT (código 51). Notificação em MT com residência em outro estado sai da tabela de casos.

Se o catálogo e o S3 falharem, o passo devolve `status: skipped` e a previsão de dengue segue.

`data/sample/srag/casos.csv` tem 8 linhas ilustrativas, com `fonte = sample`. Não é extrato do OpenDataSUS. A tela diz isso embaixo da tabela de SRAG. `dfc ingest sivep` sem `--sample-dir` substitui o arquivo.

## Nowcast

A pergunta é outra. Dos casos com sintoma numa semana, que fração já tinha sido notificada depois de `d` semanas?

O prior do sample, em 100 casos, é 40 na semana do sintoma, 30 na seguinte, 15 duas semanas depois, 10 na terceira e 5 na quarta. A fração acumulada fica 0,40, 0,70, 0,85, 0,95 e 1,00. A contagem da semana é dividida por essa fração. Semana com quatro ou mais de atraso fica como está, porque a fração chega a 1.

Há um piso de 0,25. Uma semana com 5% já notificado seria multiplicada por 20. O piso limita a correção a 4 vezes. Com este prior o piso não entra: 0,40 já está acima.

Exemplo, se a data de referência for o próprio domingo da semana. Cuiabá, semana de 22 de dezembro de 2024, 51 casos notificados. 51 / 0,40 = 127,5. A semana de 15 de dezembro, 50 casos, está a uma semana de distância: 50 / 0,70 = 71,4. A de 8 de dezembro, 37 casos, está a duas: 37 / 0,85 = 43,5.

A data de referência padrão é o dia em que o comando roda, não a última semana do arquivo. Este sample termina em 22 de dezembro de 2024. Visto em 22 de outubro de 2026, essa semana está dezenas de atrasos além do prior, a fração é 1 e o nowcast continua 51. A linha laranja só aparece quando a correção passa de 1%, o que acontece na cauda de uma série ao vivo, dentro dessas quatro semanas.

Quando existe `data/forecast/srag_atraso.parquet` vindo do OpenDataSUS, o nowcast usa essa contagem de atrasos no lugar do prior. O prior permanece para o sample e para o caso em que o catálogo falha.

A previsão de 4 e 8 semanas continua treinando com o caso notificado, como na fase 3. O nowcast fica fora do treino. A correção ainda muda quando as notificações atrasadas chegam, e misturá-la no histórico mudaria o backtest.

## Docker

A imagem instala dbt, LightGBM e Streamlit, e a `libgomp1` que o LightGBM usa no Linux. O processo escuta `0.0.0.0` na porta `PORT`, padrão 8501. Se o volume ainda não tem `data/forecast/alerts.parquet`, o entrypoint roda o demo, o dbt, a previsão, o SIVEP do sample e o nowcast, e então abre a tela. `docker compose up --build` publica essa porta em [http://localhost:8501](http://localhost:8501). O Prefect fica de fora da imagem. Quem quiser o agendamento instala o extra na máquina que fica ligada.

## A carga de 22 de outubro de 2026

`dfc refresh --backfill` rodou daqui. InfoDengue devolveu os 141 municípios, 405 semanas, de 6 de janeiro de 2019 a 4 de outubro de 2026, 57.105 linhas, nenhuma falha. A população veio do agregado 4714: 141 municípios. A API de localidades listou 142. O gold fica com os 141 que têm população. Cuiabá entra com 650.877 habitantes. A incidência da semana de 4 de outubro é 4 / 650.877 × 100.000 = 0,61.

O INMET entregou A901 Cuiabá, A902 Tangará da Serra, A904 Sorriso e A917 Sinop, um dia por estação. 2019 a 2025 fecham o ano (365 ou 366 dias). O ZIP de 2026 traz dois recortes da mesma estação. O mais longo vai até 30 de setembro, 273 dias, e é o que fica. Por isso a semana de 4 de outubro de 2026, em Cuiabá, tem 4 casos e chuva vazia: a estação ainda não cobre esses dias. Com o raio de 100 km, 34 municípios recebem clima. Os outros 107 seguem só com a trajetória de casos.

O catálogo do OpenDataSUS (`srag-2021-a-2024` e `srag-2021-e-2024`) derrubou a conexão. O passo de SRAG voltou `skipped` e o ciclo seguiu. O nowcast usou o prior do sample. Na semana de 4 de outubro, duas semanas depois do domingo, a fração do prior é 0,85 e 4 casos viram 4,7. A de 27 de setembro, três semanas depois, fica 2 / 0,95 = 2,1. Da semana de 20 de setembro para trás a fração é 1.

O LightGBM, a partir da semana de 4 de outubro, aponta 4,9 casos em Cuiabá para 1 de novembro e 4,8 para 29 de novembro. Os dois alertas saem verdes: a incidência prevista fica em 0,75 e 0,73 por 100 mil, abaixo da mediana histórica do município. O backtest tem 74.025 linhas. São 846 alertas, os 141 municípios nos dois horizontes e nos três modelos.

## O SRAG de 23 de outubro de 2026

`dfc ingest sivep --uf MT --year 2025 --year 2026` baixou os dois CSVs que o S3 publicou em 19 de outubro de 2026: `INFLUD25-19-10-2026.csv` (382.096.742 bytes) e `INFLUD26-19-10-2026.csv` (260.956.354 bytes). O catálogo CKAN caiu de novo com `Server disconnected without sending a response`. Os arquivos temporários foram apagados. O parquet não tem nome de paciente.

A tabela municipal tem 2.850 linhas, 134 municípios e 8.467 casos, com `fonte = opendatasus`. Por vírus: 5.204 outros, 2.161 influenza, 740 VSR, 362 covid. Cuiabá soma 2.656 casos de SRAG nesse recorte, da semana de 29 de dezembro de 2024 à de 11 de outubro de 2026. Setenta notificações com UF MT tinham residência fora do estado e saíram da tabela de casos.

O atraso veio de 8.537 notificações com UF MT, incluindo essas 70. Na semana do sintoma já estavam notificados 71,6%. Em uma semana, 90,3%. Em duas, 95,1%. Em três, 96,7%. Com essa curva, a semana de dengue de 4 de outubro de 2026 em Cuiabá (4 casos, duas semanas decorridas) vai a 4,20. A de 27 de setembro (2 casos, três semanas) vai a 2,07. O prior do sample, que levava esses mesmos pontos a 4,7 e 2,1, deixa de valer quando `srag_atraso.parquet` existe.

`import prefect` carrega a versão 3.9.0. `dfc refresh --serve` não foi executado.

A imagem `dengue-forecast-br:local` foi construída em 23 de outubro de 2026, depois de abrir o Docker Desktop. O `docker compose up` não foi disparado, para o volume `./data` não misturar o sample da imagem com o warehouse ao vivo.

## Limites

O alerta verde, amarelo e vermelho continua o percentil do próprio município. O texto da fase 3 descreve o corte. O prior de cinco números do sample só entra quando não há `srag_atraso.parquet`. SINAN segue opcional. O join de clima continua em 100 km. Município longe das estações que o ZIP realmente trouxe fica sem chuva e temperatura.
