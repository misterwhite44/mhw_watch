"""Téléchargement de la température de surface de la mer (SST) NOAA OISST v2.1.

Source : NOAA Optimum Interpolation SST v2.1, grille 0,25°, quotidienne depuis 1981-09,
servie par le serveur ERDDAP de NOAA CoastWatch (aucune clé d'API nécessaire).
https://www.ncei.noaa.gov/products/optimum-interpolation-sst
"""

from __future__ import annotations

import io
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import requests

ERDDAP = "https://coastwatch.pfeg.noaa.gov/erddap/griddap"
DATASET = "ncdcOisst21Agg_LonPM180"
FIRST_DAY = date(1981, 9, 1)


def _query_url(lat: float, lon: float, start: date, end: date) -> str:
    sel = (
        f"sst[({start}T12:00:00Z):1:({end}T12:00:00Z)]"
        f"[(0.0)][({lat}):1:({lat})][({lon}):1:({lon})]"
    )
    return f"{ERDDAP}/{DATASET}.csv?" + requests.utils.quote(sel, safe="():,.-T")


def _fetch_chunk(lat: float, lon: float, start: date, end: date) -> pd.DataFrame:
    resp = requests.get(_query_url(lat, lon, start, end), timeout=120)
    resp.raise_for_status()
    # ERDDAP renvoie deux lignes d'en-tête : noms puis unités.
    df = pd.read_csv(io.StringIO(resp.text), skiprows=[1])
    df["time"] = pd.to_datetime(df["time"]).dt.tz_localize(None).dt.normalize()
    return df[["time", "sst"]]


def fetch_sst(
    lat: float,
    lon: float,
    start: date = date(1982, 1, 1),
    end: date | None = None,
    cache_dir: Path | None = Path("data"),
) -> pd.Series:
    """Série quotidienne de SST (°C) au point de grille le plus proche de (lat, lon).

    Le résultat est mis en cache en CSV dans `cache_dir` pour éviter de retélécharger.
    """
    # OISST est publié avec ~2 semaines de délai pour la version finale.
    end = end or (date.today() - timedelta(days=16))
    start = max(start, FIRST_DAY)

    cache = None
    if cache_dir is not None:
        cache_dir.mkdir(parents=True, exist_ok=True)
        cache = cache_dir / f"oisst_{lat:+.3f}_{lon:+.3f}_{start}_{end}.csv"
        if cache.exists():
            s = pd.read_csv(cache, index_col=0, parse_dates=True).iloc[:, 0]
            s.name = "sst"
            return s

    # Requêtes par tranches de 10 ans pour rester sous les limites du serveur.
    chunks, cur = [], start
    while cur <= end:
        stop = min(date(cur.year + 9, 12, 31), end)
        chunks.append(_fetch_chunk(lat, lon, cur, stop))
        cur = stop + timedelta(days=1)

    df = pd.concat(chunks).dropna().drop_duplicates("time")
    s = df.set_index("time")["sst"].asfreq("D").interpolate(limit=5)
    if cache is not None:
        s.to_csv(cache)
    return s
