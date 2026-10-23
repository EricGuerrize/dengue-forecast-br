# Previsão de dengue: o que a fase 3 faz

Este texto descreve o que foi acrescentado em cima do gold, por que cada peça existe, e os números obtidos com o sample offline de Mato Grosso.

## Como ver

No macOS o LightGBM precisa da biblioteca OpenMP:

```bash
brew install libomp
```

Depois, com o ambiente do repositório (Python 3.11 ou mais novo):

```bash
source .venv/bin/activate
make demo
make transform
make forecast
make viz
```

A tela abre em [http://localhost:8501](http://localhost:8501). `make demo` grava o bronze a partir de `data/sample/`. `make transform` monta `gold.municipio_semana` no DuckDB. `make forecast` lê essa tabela e grava os parquets em `data/forecast/`. A tela só lê esses parquets. Ela não treina de novo a cada clique.

## De onde vêm os números

O gold desta máquina tem 5 municípios e 156 semanas, de 2 de janeiro de 2022 a 22 de dezembro de 2024. Os municípios são Cuiabá, Várzea Grande, Rondonópolis, Sinop e Barra do Garças. Casos e população vêm do sample InfoDengue e do recorte de população que a fase 1 gravou (Cuiabá com 650.912 habitantes nesse recorte).

Chuva e temperatura só aparecem quando o centróide do município fica a até 100 km de uma estação presente no bronze. No sample a única estação é a A901, em Cuiabá. Por isso Cuiabá e Várzea Grande têm clima em todas as 156 semanas. Rondonópolis, Sinop e Barra do Garças ficam com chuva e temperatura vazias. O modelo ainda roda nessas três cidades, usando só a trajetória de casos e o calendário.

## O que o modelo enxerga em cada semana

Cada linha é um município numa semana `t`. O alvo é o número de casos em `t+4` ou em `t+8`. As colunas de entrada usam a semana `t` e as anteriores. O caso da semana alvo não entra.

| Coluna | O que é | Por que está aí |
| --- | --- | --- |
| `casos_atual`, `casos_lag_1`, `casos_lag_2`, `casos_lag_4`, `casos_lag_8` | Casos da semana corrente e de 1, 2, 4 e 8 semanas atrás | Um surto não começa e acaba na mesma semana. A subida recente é o melhor sinal de curto prazo. |
| `casos_lag_52` | Casos de 52 semanas atrás | Dengue em MT acompanha a estação chuvosa. A mesma época do ano anterior é uma âncora. |
| `incidencia_*` | Os mesmos atrasos, em casos por 100 mil | Municípios de tamanhos diferentes não são comparáveis em contagem bruta. Sinop e Cuiabá dividem o mesmo modelo. |
| `precip_*` e `temp_*` | Chuva e temperatura média da semana corrente e de algumas semanas atrás | O ciclo do *Aedes* leva semanas. Chuva de agora entra na conta dos casos de daqui a um mês. Onde não há estação, o campo fica vazio e o LightGBM segue sem ele. |
| `humidity_lag_1` | Umidade da semana anterior | Mesma lógica do clima, com um atraso curto. |
| `epiweek` e `month` | Número da semana ISO e o mês | Marcam a época do ano mesmo quando o lag de 52 semanas ainda não existe no começo da série. |

O código está em `src/dengue_forecast/forecast/features.py`.

## Três previsões, cada uma com um papel

O comando grava as três na mesma tabela de backtest.

O modelo sazonal copia os casos de 52 semanas antes da semana alvo. Para prever a semana de 19 de janeiro de 2025 com horizonte 4, ele lê a semana equivalente de 2024. Não usa clima e não estima parâmetro nenhum. Serve de piso: se um modelo mais complicado não errar menos do que isso, ele não está pagando a complexidade.

O SARIMA é um modelo de série temporal por município: um termo autorregressivo e uma diferença sazonal de 52 semanas (`order=(1,0,0)`, `seasonal_order=(0,1,0,52)`). Ele só olha a sequência de casos daquele município. Ajustar isso em toda origem do backtest deixaria o comando lento, então o backtest guarda o SARIMA só nas últimas origens: 3 pontos no horizonte de 4 semanas e 2 no de 8. A previsão para a frente, a partir da última semana, é ajustada de novo na série inteira.

O LightGBM é uma árvore de boosting. Há um modelo por horizonte, treinado com todas as cidades juntas. Cidade sem clima ainda contribui com os lags de casos. Cidade com clima deixa o modelo usar chuva e temperatura. São 80 árvores, taxa de aprendizado 0,08, no máximo 15 folhas, semente 7. A previsão de casos é cortada em zero.

## Como o backtest fica honesto

A origem é uma semana já fechada. O treino só inclui linhas cujo alvo também já aconteceu até essa origem. A linha prevista é a da própria origem, e o alvo dela está 4 ou 8 semanas à frente, fora do treino.

O teste `test_split_origin_nao_treina_com_alvo_futuro` trava essa regra. O passo entre origens é de 4 semanas, para não retreinar 150 vezes a mesma coisa. A primeira origem só aparece depois de 52 semanas de história, porque o lag anual e o SARIMA precisam de um ciclo.

No sample isso dá 25 pontos de backtest no horizonte de 4 semanas e 24 no de 8, para o LightGBM e para o sazonal. O SARIMA não entra nessa contagem.

## Erro medido neste sample

MAE é a média do erro absoluto. "Por 100 mil" divide o erro de casos pela população do sample e multiplica por 100.000.

Horizonte de 4 semanas, LightGBM e sazonal nos mesmos 25 pontos:

| Município | MAE LightGBM (casos) | MAE sazonal (casos) | MAE LightGBM por 100 mil |
| --- | ---: | ---: | ---: |
| Cuiabá | 17,3 | 20,5 | 2,66 |
| Várzea Grande | 24,4 | 27,6 | 8,14 |
| Rondonópolis | 27,3 | 47,2 | 11,1 |
| Sinop | 52,2 | 90,5 | 26,6 |
| Barra do Garças | 12,8 | 13,0 | 10,5 |

Em Cuiabá, Várzea Grande, Rondonópolis e Sinop o LightGBM erra menos do que repetir o ano anterior. Em Barra do Garças a diferença é de 0,2 caso, dentro do ruído de uma série baixa.

O SARIMA em Cuiabá, nessas 3 origens finais do horizonte 4, teve MAE de 13,7 casos. O LightGBM, nas 25 origens, teve 17,3. São amostras diferentes. Em Sinop, nas mesmas 3 origens, o SARIMA errou 99 casos e o LightGBM, no conjunto longo, 52. O SARIMA não substitui o backtest longo.

No horizonte de 8 semanas o erro sobe. Em Cuiabá o LightGBM vai a 27,1 casos (4,17 por 100 mil) e o sazonal fica em 20,6. O piso sazonal ganha. Oito semanas à frente, neste sample, a árvore não supera repetir o ano passado na capital.

## O que a tela mostra para a frente

A última semana observada é 22 de dezembro de 2024. A previsão de 4 semanas cai em 19 de janeiro de 2025. Casos na última semana, previsão LightGBM e alerta:

| Município | Casos em 22/12/2024 | Previsão 19/01/2025 | Alerta |
| --- | ---: | ---: | --- |
| Cuiabá | 51 | 78 | amarelo |
| Várzea Grande | 128 | 272 | vermelho |
| Rondonópolis | 81 | 102 | amarelo |
| Sinop | 309 | 320 | vermelho |
| Barra do Garças | 3 | 24 | amarelo |

O alerta compara a incidência prevista com o histórico daquele município, não com um corte da SES. Abaixo da mediana semanal, verde. Da mediana até o percentil 90, amarelo. Acima do percentil 90, vermelho. Em Cuiabá a mediana é 3,1 casos por 100 mil por semana e o p90 é 15,4. A previsão de 12,0 por 100 mil fica no amarelo.

Várzea Grande sobe de 128 casos observados para 272 previstos. O MAE de 4 semanas nessa cidade é 24 casos, então 272 é uma extrapolação da subida de dezembro, com uma folga grande. Sinop já estava em 309 e a previsão fica em 320. O vermelho ali descreve uma incidência que já era alta (157 por 100 mil na última semana, p90 histórico de 133).

O gráfico desenha a previsão na semana alvo, não na semana em que o modelo rodou. Um ponto de backtest com origem em 1º de dezembro aparece em cima de 29 de dezembro, ao lado do caso que de fato ocorreu.

## Arquivos

- `src/dengue_forecast/forecast/features.py` monta os lags.
- `src/dengue_forecast/forecast/backtest.py` faz o walk-forward, o sazonal, o SARIMA e o LightGBM.
- `src/dengue_forecast/forecast/alerts.py` classifica verde, amarelo e vermelho.
- `src/dengue_forecast/forecast/run.py` lê o gold e grava `history`, `features`, `backtest`, `forward`, `metrics` e `alerts` em `data/forecast/`.
- `src/dengue_forecast/viz/app.py` é a tela. `viz/frames.py` junta as séries do gráfico e pode ser testado sem subir o Streamlit.

Os testes estão em `tests/test_forecast.py`. Eles cobrem o lag que não atravessa município, o alvo 4 semanas à frente, a leitura sazonal, o corte do treino, a regra do alerta e a gravação dos parquets.

## Limites deste sample

A série é o sample de cinco cidades, não o estado inteiro. Clima de Rondonópolis, Sinop e Barra do Garças não entrou. O alerta não é o nível do InfoDengue nem um boletim da SES. InfoDengue revisa os casos depois, então um número de dezembro pode mudar. A tela não atualiza sozinha: para uma semana nova é preciso ingerir, rodar o `transform` e o `forecast` de novo. O agendamento semanal com Prefect continua fora deste passo.
