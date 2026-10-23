"""Nowcast simples a partir da fração de casos já notificada por semana de atraso.

A série publicada numa data ainda não contém os casos das semanas recentes que
vão chegar depois. Se, no histórico, só uma fração `f` dos casos de uma semana
já foi notificada quando se passaram `d` semanas, a contagem daquela semana
sobe para `casos / f`. Semanas antigas, com `f = 1`, ficam como estão.
"""

from __future__ import annotations

import pandas as pd


def empirical_cdf(counts: pd.DataFrame) -> pd.Series:
    """Fração acumulada de notificações até cada atraso, em semanas."""
    frame = counts.loc[counts["n"] > 0, ["delay_weeks", "n"]].copy()
    if frame.empty:
        raise ValueError("Distribuição de atraso vazia.")
    frame["delay_weeks"] = frame["delay_weeks"].astype(int)
    frame["n"] = frame["n"].astype(float)
    grouped = frame.groupby("delay_weeks", as_index=False)["n"].sum().sort_values("delay_weeks")
    cdf = grouped["n"].cumsum() / grouped["n"].sum()
    return pd.Series(cdf.to_numpy(), index=grouped["delay_weeks"].to_numpy())


def reported_fraction(cdf: pd.Series, elapsed_weeks: int) -> float:
    """Parcela já notificada depois de `elapsed_weeks` semanas desde o início da semana."""
    if elapsed_weeks < 0:
        return 1.0
    capped = min(int(elapsed_weeks), int(cdf.index.max()))
    eligible = cdf.loc[cdf.index <= capped]
    return float(eligible.iloc[-1])


def nowcast_cases(
    weekly: pd.DataFrame,
    cdf: pd.Series,
    *,
    as_of: pd.Timestamp,
    min_fraction: float = 0.25,
) -> pd.DataFrame:
    """Devolve a tabela com `casos_nowcast` e a fração usada em cada semana.

    `min_fraction` impede que uma semana recém-aberta, com quase nada notificado,
    seja multiplicada por um número enorme. 0,25 limita a correção a 4 vezes.
    """
    if not 0 < min_fraction <= 1:
        raise ValueError("min_fraction precisa estar entre 0 e 1.")

    out = weekly.copy()
    out["week_start"] = pd.to_datetime(out["week_start"])
    as_of = pd.Timestamp(as_of)
    elapsed = ((as_of - out["week_start"]).dt.days // 7).astype(int)
    fraction = [reported_fraction(cdf, int(weeks)) for weeks in elapsed]
    out["semanas_decorridas"] = elapsed.to_numpy()
    out["fracao_notificada"] = fraction
    applied = out["fracao_notificada"].clip(lower=min_fraction)
    out["casos_nowcast"] = (out["casos"].astype(float) / applied).astype(float)
    return out
