"""Données de démonstration : SST réaliste générée, avec tendance de réchauffement
et une vague de chaleur injectée. Permet de tester sans accès réseau."""

from __future__ import annotations

import numpy as np
import pandas as pd


def synthetic_sst(
    start: str = "1982-01-01",
    end: str = "2025-12-31",
    mean: float = 18.0,
    amplitude: float = 5.0,
    trend_per_decade: float = 0.25,
    noise: float = 0.5,
    heatwave: tuple[str, int, float] | None = ("2025-07-01", 30, 3.5),
    seed: int = 42,
) -> pd.Series:
    """SST quotidienne type Méditerranée (°C).

    `heatwave` = (date de début, durée en jours, anomalie au pic en °C).
    """
    rng = np.random.default_rng(seed)
    idx = pd.date_range(start, end, freq="D")
    t = np.arange(len(idx))
    seasonal = mean - amplitude * np.cos(2 * np.pi * (idx.dayofyear - 30) / 365.25)
    trend = trend_per_decade * t / 3652.5

    # Bruit autocorrélé AR(1) : les anomalies de SST persistent plusieurs jours.
    eps = rng.normal(0, noise * np.sqrt(1 - 0.9**2), len(idx))
    ar = np.zeros(len(idx))
    for i in range(1, len(idx)):
        ar[i] = 0.9 * ar[i - 1] + eps[i]

    sst = pd.Series(seasonal + trend + ar, index=idx, name="sst")
    if heatwave:
        hw_start, days, peak = heatwave
        hw_idx = pd.date_range(hw_start, periods=days, freq="D")
        shape = np.sin(np.linspace(0, np.pi, days))
        sst.loc[hw_idx] += peak * shape
    return sst
