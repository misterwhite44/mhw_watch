"""Téléchargement de la température de surface de la mer (SST) NOAA OISST v2.1.

Source : NOAA Optimum Interpolation SST v2.1, grille 0,25°, quotidienne depuis 1981-09
(aucune clé d'API nécessaire).
https://www.ncei.noaa.gov/products/optimum-interpolation-sst

Deux accès au même jeu de données sont essayés dans l'ordre :
1. les serveurs ERDDAP de NOAA CoastWatch, rapides (on peut en imposer un autre avec la
   variable d'environnement MHW_WATCH_ERDDAP, URL se terminant par /erddap) ;
2. le serveur THREDDS/OPeNDAP de NOAA PSL, en secours : fiable mais lent (~0,3 s par jour
   demandé), donc interrogé par trimestres, en parallèle, avec un cache par année.
"""

from __future__ import annotations

import io
import math
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import requests

PSL = "https://psl.noaa.gov/thredds/dodsC/Datasets/noaa.oisst.v2.highres"
PSL_DAYS = 90  # jours par requête : PSL coupe les requêtes au-delà d'environ 60 s
PSL_WORKERS = 4  # années téléchargées en parallèle

# Serveurs ERDDAP servant le même jeu de données, essayés dans cet ordre.
ERDDAP_SERVERS = [
    "https://coastwatch.pfeg.noaa.gov/erddap",
    "https://upwell.pfeg.noaa.gov/erddap",
]
DATASET = "ncdcOisst21Agg_LonPM180"
FIRST_DAY = date(1981, 9, 1)

CONNECT_TIMEOUT = 10  # s : un serveur injoignable est vite abandonné
READ_TIMEOUT = 180  # s : une tranche de 10 ans peut être longue à préparer côté serveur
RETRIES = 1  # nouvelle tentative par serveur après un échec réseau


class DownloadError(RuntimeError):
    """Aucun serveur n'a pu fournir les données."""


def _request(url: str) -> str:
    """GET avec une nouvelle tentative sur les erreurs réseau et les erreurs 5xx."""
    for attempt in range(RETRIES + 1):
        try:
            resp = requests.get(url, timeout=(CONNECT_TIMEOUT, READ_TIMEOUT))
        except (requests.ConnectionError, requests.Timeout):
            if attempt == RETRIES:
                raise
        else:
            # 404 : jeu de données absent de ce serveur, inutile d'insister.
            if resp.status_code < 500 or attempt == RETRIES:
                resp.raise_for_status()
                return resp.text
        time.sleep(2 * (attempt + 1))
    raise AssertionError("inaccessible")


# --- NOAA PSL (OPeNDAP) -------------------------------------------------------------

def _psl_indices(lat: float, lon: float) -> tuple[int, int]:
    """Indices de la maille 0,25° la plus proche (lat -89.875..89.875, lon 0.125..359.875)."""
    i = math.floor((lat + 89.875) / 0.25 + 0.5)
    j = math.floor(((lon % 360) - 0.125) / 0.25 + 0.5) % 1440
    return min(max(i, 0), 719), j


def _psl_ndays(year: int) -> int:
    """Nombre de jours présents dans le fichier annuel (l'année en cours est incomplète)."""
    if year < date.today().year:
        return 366 if pd.Timestamp(year=year, month=12, day=31).dayofyear == 366 else 365
    dds = _request(f"{PSL}/sst.day.mean.{year}.nc.dds")
    m = re.search(r"time\s*=\s*(\d+)", dds)
    if not m:
        raise ValueError("réponse PSL inattendue")
    return int(m.group(1))


def _parse_psl_ascii(text: str) -> pd.DataFrame:
    """Lit la réponse OPeNDAP .ascii d'une grille sst[time][1][1]."""
    body = text.split("---------------------------------------------", 1)[-1]
    sst, times, block = [], [], None
    for line in body.splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith("sst.sst["):
            block = "sst"
        elif line.startswith("sst.time["):
            block = "time"
        elif line.startswith("sst."):
            block = None
        elif block == "sst":
            sst.append(float(line.rsplit(",", 1)[-1]))
        elif block == "time":
            times += [float(v) for v in line.split(",")]
    if not sst or len(sst) != len(times):
        raise ValueError("réponse PSL inattendue")
    df = pd.DataFrame({
        "time": pd.Timestamp("1800-01-01") + pd.to_timedelta(times, unit="D"),
        "sst": sst,
    })
    df.loc[(df["sst"] < -3) | (df["sst"] > 45), "sst"] = float("nan")  # terre / valeur manquante
    df["time"] = df["time"].dt.normalize()
    return df


def _psl_year(year: int, i: int, j: int, cache_dir: Path | None) -> pd.DataFrame:
    """Une année de PSL, par tranches de PSL_DAYS jours ; les années complètes sont mises en cache."""
    cache = cache_dir / f"psl_{i}_{j}_{year}.csv" if cache_dir is not None else None
    if cache is not None and cache.exists():
        return pd.read_csv(cache, parse_dates=["time"])
    n = _psl_ndays(year)
    parts = []
    for a in range(0, n, PSL_DAYS):
        b = min(a + PSL_DAYS, n) - 1
        url = f"{PSL}/sst.day.mean.{year}.nc.ascii?sst%5B{a}:1:{b}%5D%5B{i}%5D%5B{j}%5D"
        parts.append(_parse_psl_ascii(_request(url)))
    df = pd.concat(parts)
    if cache is not None and year < date.today().year:
        cache_dir.mkdir(parents=True, exist_ok=True)
        df.to_csv(cache, index=False)
    return df


def _fetch_psl(lat: float, lon: float, start: date, end: date, cache_dir: Path | None) -> pd.DataFrame:
    i, j = _psl_indices(lat, lon)
    years = range(start.year, end.year + 1)
    print(f"  {len(years)} années à télécharger (plusieurs minutes la première fois ; "
          "une interruption reprend là où elle s'est arrêtée).")
    chunks = []
    with ThreadPoolExecutor(PSL_WORKERS) as pool:
        futures = [pool.submit(_psl_year, y, i, j, cache_dir) for y in years]
        try:
            for k, fut in enumerate(as_completed(futures), 1):
                chunks.append(fut.result())
                print(f"  … {k}/{len(years)} années", end="\r", flush=True)
        except BaseException:
            pool.shutdown(cancel_futures=True)
            raise
        finally:
            print()
    df = pd.concat(chunks).sort_values("time")
    return df[(df["time"] >= pd.Timestamp(start)) & (df["time"] <= pd.Timestamp(end))]


# --- ERDDAP (CoastWatch) ------------------------------------------------------------

def _servers() -> list[str]:
    custom = os.environ.get("MHW_WATCH_ERDDAP")
    servers = [custom.rstrip("/")] if custom else []
    return servers + [s for s in ERDDAP_SERVERS if s not in servers]


def _query_url(server: str, lat: float, lon: float, start: date, end: date) -> str:
    sel = (
        f"sst[({start}T12:00:00Z):1:({end}T12:00:00Z)]"
        f"[(0.0)][({lat}):1:({lat})][({lon}):1:({lon})]"
    )
    return f"{server}/griddap/{DATASET}.csv?" + requests.utils.quote(sel, safe="():,.-T")


def _fetch_chunk(lat: float, lon: float, start: date, end: date, server: str) -> pd.DataFrame:
    text = _request(_query_url(server, lat, lon, start, end))
    # ERDDAP renvoie deux lignes d'en-tête : noms puis unités.
    df = pd.read_csv(io.StringIO(text), skiprows=[1])
    df["time"] = pd.to_datetime(df["time"]).dt.tz_localize(None).dt.normalize()
    return df[["time", "sst"]]


def _fetch_erddap(lat: float, lon: float, start: date, end: date, server: str) -> pd.DataFrame:
    # Requêtes par tranches de 10 ans pour rester sous les limites du serveur.
    chunks, cur = [], start
    while cur <= end:
        stop = min(date(cur.year + 9, 12, 31), end)
        print(f"  … {cur.year}-{stop.year}")
        chunks.append(_fetch_chunk(lat, lon, cur, stop, server))
        cur = stop + timedelta(days=1)
    return pd.concat(chunks)


def _short_reason(e: Exception) -> str:
    if isinstance(e, requests.ConnectTimeout):
        return "délai de connexion dépassé"
    if isinstance(e, requests.Timeout):
        return "réponse trop lente"
    if isinstance(e, requests.ConnectionError):
        return "connexion impossible"
    if isinstance(e, requests.HTTPError) and e.response is not None:
        code = e.response.status_code
        return "jeu de données absent (404)" if code == 404 else f"erreur HTTP {code}"
    if isinstance(e, ValueError):
        return "réponse illisible"
    return type(e).__name__


def _download(
    lat: float, lon: float, start: date, end: date, cache_dir: Path | None
) -> pd.DataFrame:
    """Essaie chaque source dans l'ordre et renvoie la première qui fournit les données."""
    sources = [
        (server.split("/")[2], lambda s=server: _fetch_erddap(lat, lon, start, end, s))
        for server in _servers()
    ]
    psl_cache = cache_dir / "psl" if cache_dir is not None else None
    sources.append(("psl.noaa.gov", lambda: _fetch_psl(lat, lon, start, end, psl_cache)))

    errors = []
    for host, fetch in sources:
        print(f"  Source : {host}")
        try:
            return fetch()
        except (requests.RequestException, ValueError) as e:
            errors.append(f"  - {host} : {_short_reason(e)}")
            print(f"  {host} indisponible ({_short_reason(e)}).")
    raise DownloadError(
        "Impossible de télécharger les données NOAA OISST. Aucun serveur n'a répondu :\n"
        + "\n".join(errors)
        + "\n\nPistes :\n"
        "  - vérifie ta connexion ; un réseau d'école, d'entreprise ou un VPN bloque parfois ces serveurs ;\n"
        "  - réessaie plus tard (les serveurs NOAA ont des interruptions) ;\n"
        "  - indique un autre serveur ERDDAP avec la variable d'environnement MHW_WATCH_ERDDAP ;\n"
        "  - en attendant, lance `mhw-watch analyze --demo` (données synthétiques, hors ligne)."
    )


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

    df = _download(lat, lon, start, end, cache_dir).dropna().drop_duplicates("time")
    s = df.set_index("time")["sst"].asfreq("D").interpolate(limit=5)
    if cache is not None:
        s.to_csv(cache)
    return s
