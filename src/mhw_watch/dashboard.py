"""Logique du tableau de bord web, sans Streamlit (donc testable avec pytest).

Le tableau de bord ne télécharge rien lui-même : il relit les résultats écrits par
`mhw-watch analyze` dans `outputs/<site>/`. L'interface est dans `dashboard_app.py`.
"""

from __future__ import annotations

import json
import subprocess
import sys
import threading
import webbrowser
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from .detect import CATEGORIES
from .plot import CAT_COLORS
from .sites import SITES, Site

NO_DATA_COLOR = "#9e9e9e"
NO_MHW_COLOR = "#2b8cbe"
APP_PATH = Path(__file__).with_name("dashboard_app.py")


@dataclass(frozen=True)
class SiteStatus:
    site: Site
    has_data: bool
    category: int = 0  # 0 = pas de vague de chaleur, 1..4 = catégorie I..IV
    date: pd.Timestamp | None = None
    sst: float | None = None
    anom: float | None = None

    @property
    def label(self) -> str:
        if not self.has_data:
            return "Pas de données"
        if self.category == 0:
            return "Pas de vague de chaleur"
        return f"Vague de chaleur, catégorie {CATEGORIES[self.category]}"

    @property
    def color(self) -> str:
        if not self.has_data:
            return NO_DATA_COLOR
        return CAT_COLORS.get(self.category, NO_MHW_COLOR)


def read_daily(out_dir: Path, key: str) -> pd.DataFrame | None:
    """Série quotidienne écrite par `analyze`, ou None si le site n'a jamais été analysé."""
    path = Path(out_dir) / key / "daily.csv"
    if not path.is_file():
        return None
    daily = pd.read_csv(path, index_col=0, parse_dates=True)
    return daily if not daily.empty else None


def read_events(out_dir: Path, key: str) -> pd.DataFrame:
    path = Path(out_dir) / key / "events.csv"
    if not path.is_file():
        return pd.DataFrame()
    return pd.read_csv(path, parse_dates=["start", "end", "peak"])


def read_yearly(out_dir: Path, key: str) -> pd.DataFrame:
    path = Path(out_dir) / key / "yearly_summary.csv"
    if not path.is_file():
        return pd.DataFrame()
    return pd.read_csv(path, index_col="year")


def zone_label(out_dir: Path, key: str) -> str:
    """Zone analysée (contour WDPA ou point), d'après `zone.json` écrit par `analyze`."""
    path = Path(out_dir) / key / "zone.json"
    if not path.is_file():
        return ""
    zone = json.loads(path.read_text(encoding="utf-8"))
    if zone.get("mode") == "polygon":
        return f"Contour WDPA {zone.get('wdpa_id')} : {zone.get('description', '')}"
    return "Point représentatif (une maille 0,25°)"


def status_from_daily(site: Site, daily: pd.DataFrame | None) -> SiteStatus:
    """État du site au dernier jour disponible.

    Un jour ne compte comme vague de chaleur que s'il appartient à un événement détecté
    (au moins 5 jours au-dessus du seuil) ; la catégorie est alors au moins I.
    """
    if daily is None or daily.empty:
        return SiteStatus(site, has_data=False)
    last = daily.dropna(subset=["sst"]).iloc[-1]
    in_mhw = str(last["in_mhw"]).lower() == "true"
    category = int(min(max(int(last["category"]), 1), 4)) if in_mhw else 0
    return SiteStatus(
        site,
        has_data=True,
        category=category,
        date=last.name,
        sst=float(last["sst"]),
        anom=float(last["anom"]),
    )


def all_statuses(out_dir: Path, sites: dict[str, Site] = SITES) -> list[SiteStatus]:
    return [status_from_daily(s, read_daily(out_dir, s.key)) for s in sites.values()]


def site_at(lat: float, lon: float, sites: dict[str, Site] = SITES, tol: float = 1e-4) -> Site | None:
    """Site dont le marqueur est en (lat, lon) : sert à retrouver le site cliqué sur la carte."""
    for s in sites.values():
        if abs(s.lat - lat) < tol and abs(s.lon - lon) < tol:
            return s
    return None


def history_window(daily: pd.DataFrame, period: str) -> pd.DataFrame:
    """Sous-série à tracer : "12 mois", "5 ans", "Tout" ou une année ("2022")."""
    if period == "Tout":
        return daily
    if period == "12 mois":
        return daily.iloc[-365:]
    if period == "5 ans":
        return daily[daily.index > daily.index[-1] - pd.DateOffset(years=5)]
    return daily[daily.index.year == int(period)]


def launch(
    out_dir: str = "outputs", data_dir: str = "data", port: int | None = None, open_browser: bool = True
) -> int:
    """Démarre le serveur Streamlit (commande `mhw-watch dashboard`) et ouvre le navigateur."""
    port = port or 8501
    # Mode "headless" : évite la question (e-mail) que Streamlit pose au tout premier lancement.
    cmd = [sys.executable, "-m", "streamlit", "run", str(APP_PATH),
           "--server.headless", "true", "--server.port", str(port),
           "--", "--out", out_dir, "--data-dir", data_dir]
    url = f"http://localhost:{port}"
    print(f"Tableau de bord sur {url} (Ctrl+C pour arrêter)")
    if open_browser:
        threading.Timer(3, webbrowser.open, args=[url]).start()
    try:
        return subprocess.call(cmd)
    except KeyboardInterrupt:
        return 0
