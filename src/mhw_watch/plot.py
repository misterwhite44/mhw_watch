"""Graphiques : SST récente face à la climatologie, et tendance annuelle."""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402

CAT_COLORS = {1: "#f7c948", 2: "#f08c2e", 3: "#d6452b", 4: "#7a1020"}


def plot_recent(daily: pd.DataFrame, title: str, out: Path, days: int = 365) -> Path:
    d = daily.iloc[-days:]
    fig, ax = plt.subplots(figsize=(11, 4.5))
    ax.plot(d.index, d["seas"], color="#555", lw=1, label="Moyenne climatologique")
    ax.plot(d.index, d["thresh"], color="#555", lw=1, ls="--", label="Seuil 90e percentile")
    ax.plot(d.index, d["sst"], color="#0b5394", lw=1.4, label="SST observée")

    above = d["in_mhw"]
    for cat, color in CAT_COLORS.items():
        mask = above & (d["category"].clip(lower=1) == cat)
        if mask.any():
            ax.fill_between(d.index, d["thresh"], d["sst"], where=mask, color=color,
                            alpha=0.8, lw=0, label=f"MHW catégorie {'I' * cat if cat < 4 else 'IV'}")

    ax.set_title(title)
    ax.set_ylabel("Température de surface (°C)")
    ax.legend(loc="upper left", fontsize=8, ncol=2)
    ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(out, dpi=150)
    plt.close(fig)
    return out


def plot_yearly(summary: pd.DataFrame, title: str, out: Path) -> Path:
    fig, ax = plt.subplots(figsize=(11, 4))
    ax.bar(summary.index, summary["mhw_days"], color="#d6452b")
    ax.set_ylabel("Jours de vague de chaleur marine")
    ax.set_title(title)
    ax.grid(axis="y", alpha=0.3)
    fig.tight_layout()
    fig.savefig(out, dpi=150)
    plt.close(fig)
    return out
