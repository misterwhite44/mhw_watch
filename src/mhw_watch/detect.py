"""Détection des vagues de chaleur marines (Marine Heatwaves, MHW).

Implémente la définition de référence :
- Hobday et al. (2016), "A hierarchical approach to defining marine heatwaves",
  Progress in Oceanography 141, 227-238.
- Hobday et al. (2018), "Categorizing and naming marine heatwaves",
  Oceanography 31(2) — catégories I à IV.

Une MHW est une période d'au moins 5 jours consécutifs où la SST dépasse le
90e percentile climatologique du jour de l'année ; deux événements séparés
par 2 jours ou moins sont fusionnés.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

CATEGORIES = {1: "I - Modérée", 2: "II - Forte", 3: "III - Sévère", 4: "IV - Extrême"}


def _doy366(index: pd.DatetimeIndex) -> np.ndarray:
    """Jour de l'année sur un calendrier de 366 jours (le 1er mars vaut toujours 61)."""
    doy = index.dayofyear.to_numpy().copy()
    shift = (~index.is_leap_year) & (doy >= 60)
    doy[shift] += 1
    return doy


def _smooth_circular(x: np.ndarray, width: int) -> np.ndarray:
    pad = width // 2
    xp = np.concatenate([x[-pad:], x, x[:pad]])
    return np.convolve(xp, np.ones(width) / width, mode="valid")


def climatology(
    sst: pd.Series,
    baseline: tuple[int, int] = (1991, 2020),
    window_half_width: int = 5,
    percentile: float = 90,
    smooth_width: int = 31,
) -> pd.DataFrame:
    """Climatologie journalière (moyenne `seas` et seuil `thresh`) indexée par jour 1..366."""
    base = sst[(sst.index.year >= baseline[0]) & (sst.index.year <= baseline[1])].dropna()
    if base.empty:
        raise ValueError(f"Aucune donnée sur la période de référence {baseline}")
    doy = _doy366(base.index)
    values = base.to_numpy()

    days = np.arange(1, 367)
    seas = np.empty(366)
    thresh = np.empty(366)
    for i, d in enumerate(days):
        dist = np.abs(doy - d)
        dist = np.minimum(dist, 366 - dist)  # fenêtre circulaire autour du 1er janvier
        sel = values[dist <= window_half_width]
        seas[i] = sel.mean()
        thresh[i] = np.percentile(sel, percentile)

    return pd.DataFrame(
        {
            "seas": _smooth_circular(seas, smooth_width),
            "thresh": _smooth_circular(thresh, smooth_width),
        },
        index=pd.Index(days, name="doy"),
    )


def attach_climatology(sst: pd.Series, clim: pd.DataFrame) -> pd.DataFrame:
    """Ajoute à chaque jour de la série sa moyenne et son seuil climatologiques."""
    doy = _doy366(sst.index)
    return pd.DataFrame(
        {
            "sst": sst.to_numpy(),
            "seas": clim["seas"].to_numpy()[doy - 1],
            "thresh": clim["thresh"].to_numpy()[doy - 1],
        },
        index=sst.index,
    )


def _runs(mask: np.ndarray) -> list[tuple[int, int]]:
    """Indices [début, fin] (inclus) des séquences de True."""
    padded = np.concatenate([[False], mask, [False]])
    diff = np.diff(padded.astype(int))
    starts = np.flatnonzero(diff == 1)
    ends = np.flatnonzero(diff == -1) - 1
    return list(zip(starts, ends))


def detect(
    sst: pd.Series,
    clim: pd.DataFrame | None = None,
    min_duration: int = 5,
    max_gap: int = 2,
    **clim_kwargs,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Détecte les MHW.

    Renvoie (events, daily) :
    - events : un événement par ligne (dates, durée, intensités, catégorie) ;
    - daily  : la série quotidienne avec climatologie, anomalie et catégorie du jour.
    """
    sst = sst.asfreq("D")
    if clim is None:
        clim = climatology(sst, **clim_kwargs)
    daily = attach_climatology(sst, clim)
    daily["anom"] = daily["sst"] - daily["seas"]
    # Catégorie du jour : multiple de l'écart (seuil - moyenne) dépassé.
    diff = (daily["thresh"] - daily["seas"]).to_numpy()
    ratio = np.floor_divide(daily["anom"].to_numpy(), diff)
    daily["category"] = np.clip(np.nan_to_num(ratio, nan=0), 0, 4).astype(int)

    above = (daily["sst"] > daily["thresh"]).to_numpy()
    runs = [r for r in _runs(above) if r[1] - r[0] + 1 >= min_duration]

    merged: list[list[int]] = []
    for s, e in runs:
        if merged and s - merged[-1][1] - 1 <= max_gap:
            merged[-1][1] = e
        else:
            merged.append([s, e])

    in_mhw = np.zeros(len(daily), dtype=bool)
    for s, e in merged:
        in_mhw[s : e + 1] = True
    daily["in_mhw"] = in_mhw

    rows = []
    for s, e in merged:
        ev = daily.iloc[s : e + 1]
        peak = ev["anom"].idxmax()
        cat = int(max(1, daily.loc[peak, "category"]))
        rows.append(
            {
                "start": ev.index[0].date(),
                "end": ev.index[-1].date(),
                "peak": peak.date(),
                "duration_days": len(ev),
                "intensity_max": round(ev["anom"].max(), 2),
                "intensity_mean": round(ev["anom"].mean(), 2),
                "intensity_cumulative": round(ev["anom"].sum(), 1),
                "sst_max": round(ev["sst"].max(), 2),
                "category": CATEGORIES[cat],
            }
        )

    events = pd.DataFrame(
        rows,
        columns=[
            "start", "end", "peak", "duration_days", "intensity_max",
            "intensity_mean", "intensity_cumulative", "sst_max", "category",
        ],
    )
    return events, daily


def yearly_summary(daily: pd.DataFrame) -> pd.DataFrame:
    """Nombre de jours de MHW et intensité cumulée par an (utile pour voir la tendance)."""
    in_mhw = daily["in_mhw"]
    anom_in = daily["anom"].where(in_mhw, 0)
    return pd.DataFrame(
        {
            "mhw_days": in_mhw.groupby(daily.index.year).sum(),
            "cumulative_intensity": anom_in.groupby(daily.index.year).sum().round(1),
            "mean_sst": daily["sst"].groupby(daily.index.year).mean().round(2),
        }
    ).rename_axis("year")
