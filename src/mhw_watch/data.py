"""Téléchargement de la température de surface de la mer (SST) NOAA OISST v2.1.

Source : NOAA Optimum Interpolation SST v2.1, grille 0,25°, quotidienne depuis 1981-09
(aucune clé d'API nécessaire).
https://www.ncei.noaa.gov/products/optimum-interpolation-sst

Deux accès au même jeu de données sont essayés dans l'ordre :
1. les serveurs ERDDAP de NOAA CoastWatch, rapides ;
2. le serveur THREDDS/OPeNDAP de NOAA PSL, en secours : fiable mais lent (~0,3 s par jour
   demandé), donc interrogé par tranches, en parallèle, avec un cache par année.
Les serveurs, l'ordre des sources et les délais se règlent dans `.env` (voir config.py).
"""

from __future__ import annotations

import io
import math
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import requests

from . import config
from .wdpa import NLON, RES, Area, cell_index, lat_of, lon_runs

FIRST_DAY = date(1981, 9, 1)
THROTTLE_WAITS = (15, 30, 60, 120)  # s d'attente successives après une réponse 429


class DownloadError(RuntimeError):
    """Aucun serveur n'a pu fournir les données."""


def _request(url: str) -> str:
    """GET avec nouvelles tentatives sur les erreurs réseau, 5xx et 429 (trop de requêtes)."""
    retries = config.get_int("RETRIES")
    timeout = (config.get_int("CONNECT_TIMEOUT"), config.get_int("READ_TIMEOUT"))
    attempt = throttled = 0
    while True:
        try:
            resp = requests.get(url, timeout=timeout)
        except (requests.ConnectionError, requests.Timeout):
            if attempt == retries:
                raise
            attempt += 1
            time.sleep(2 * attempt)
            continue
        if resp.status_code == 429 and throttled < len(THROTTLE_WAITS):
            # Le serveur demande de ralentir : on attend (Retry-After si fourni) puis on reprend.
            wait = resp.headers.get("Retry-After", "")
            time.sleep(int(wait) if wait.isdigit() else THROTTLE_WAITS[throttled])
            throttled += 1
            continue
        if resp.status_code >= 500 and attempt < retries:
            attempt += 1
            time.sleep(2 * attempt)
            continue
        # 404 : jeu de données absent de ce serveur, inutile d'insister.
        resp.raise_for_status()
        return resp.text


# --- NOAA PSL (OPeNDAP) -------------------------------------------------------------

def _psl_indices(lat: float, lon: float) -> tuple[int, int]:
    """Indices de la maille 0,25° la plus proche (lat -89.875..89.875, lon 0.125..359.875)."""
    i = math.floor((lat + 89.875) / 0.25 + 0.5)
    j = math.floor(((lon % 360) - 0.125) / 0.25 + 0.5) % 1440
    return min(max(i, 0), 719), j


def _psl_ocean_cell(i: int, j: int, radius: int = 2) -> tuple[int, int]:
    """Maille océan la plus proche de (i, j) : la côte peut tomber dans une maille « terre »."""
    i0, i1 = max(i - radius, 0), min(i + radius, 719)
    j0, j1 = max(j - radius, 0), min(j + radius, 1439)
    url = (f"{config.get('PSL_URL')}/sst.day.mean.2000.nc.ascii?"
           f"sst%5B0:1:0%5D%5B{i0}:1:{i1}%5D%5B{j0}:1:{j1}%5D")
    body = _request(url).split("---------------------------------------------", 1)[-1]
    rows = re.findall(r"^\s*\[0\]\[(\d+)\],(.*)$", body, flags=re.MULTILINE)
    best = None
    for k, values in rows:
        for m, v in enumerate(values.split(",")):
            if -3 <= float(v) <= 45:
                ci, cj = i0 + int(k), j0 + m
                d = (ci - i) ** 2 + (cj - j) ** 2
                if best is None or d < best[0]:
                    best = (d, ci, cj)
    if best is None:
        raise ValueError("aucune maille océan à proximité du point demandé")
    return best[1], best[2]


def _psl_ndays(year: int) -> int:
    """Nombre de jours présents dans le fichier annuel (l'année en cours est incomplète)."""
    if year < date.today().year:
        return 366 if pd.Timestamp(year=year, month=12, day=31).dayofyear == 366 else 365
    dds = _request(f"{config.get('PSL_URL')}/sst.day.mean.{year}.nc.dds")
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
    psl, step = config.get("PSL_URL"), config.get_int("PSL_DAYS")
    cache = cache_dir / f"psl_{i}_{j}_{year}.csv" if cache_dir is not None else None
    if cache is not None and cache.exists():
        return pd.read_csv(cache, parse_dates=["time"])
    n = _psl_ndays(year)
    parts = []
    for a in range(0, n, step):
        b = min(a + step, n) - 1
        url = f"{psl}/sst.day.mean.{year}.nc.ascii?sst%5B{a}:1:{b}%5D%5B{i}%5D%5B{j}%5D"
        parts.append(_parse_psl_ascii(_request(url)))
    df = pd.concat(parts)
    if cache is not None and year < date.today().year and df["sst"].notna().any():
        cache_dir.mkdir(parents=True, exist_ok=True)
        df.to_csv(cache, index=False)
    return df


def _fetch_psl(lat: float, lon: float, start: date, end: date, cache_dir: Path | None) -> pd.DataFrame:
    i, j = _psl_ocean_cell(*_psl_indices(lat, lon))
    print(f"  Maille océan utilisée : {-89.875 + 0.25 * i:.3f}, {0.125 + 0.25 * j:.3f} (0-360°E)")
    years = range(start.year, end.year + 1)
    print(f"  {len(years)} années à télécharger (plusieurs minutes la première fois ; "
          "une interruption reprend là où elle s'est arrêtée).")
    chunks = []
    with ThreadPoolExecutor(config.get_int("PSL_WORKERS")) as pool:
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

def _query_url(server: str, lat: float, lon: float, start: date, end: date) -> str:
    sel = (
        f"sst[({start}T12:00:00Z):1:({end}T12:00:00Z)]"
        f"[(0.0)][({lat}):1:({lat})][({lon}):1:({lon})]"
    )
    return f"{server}/griddap/{config.get('ERDDAP_DATASET')}.csv?" + requests.utils.quote(sel, safe="():,.-T")


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
    df = pd.concat(chunks)
    if df["sst"].isna().all():
        # ERDDAP prend la maille la plus proche, qui peut être une maille « terre ».
        raise ValueError("maille terre, aucune SST")
    return df


# --- Moyenne sur une zone (contour WDPA) --------------------------------------------

def _area_mean(df: pd.DataFrame, area: Area) -> pd.DataFrame:
    """Moyenne quotidienne, pondérée par cos(latitude), des mailles de `area` ayant une valeur.

    `df` a les colonnes time, lat, lon, sst ; les mailles hors sélection (le rectangle demandé
    au serveur déborde du contour) et les mailles « terre » (NaN) sont écartées.
    """
    i, j = cell_index(df["lat"].to_numpy(), df["lon"].to_numpy())
    wanted = set(area.cells)
    df = df[[c in wanted for c in zip(i.tolist(), j.tolist())]]
    df = df[(df["sst"] >= -3) & (df["sst"] <= 45)]
    w = np.cos(np.radians(df["lat"]))
    num = (df["sst"] * w).groupby(df["time"]).sum()
    den = w.groupby(df["time"]).sum()
    return (num / den).rename("sst").rename_axis("time").reset_index()


def _lat_range(area: Area) -> tuple[int, int]:
    rows = [i for i, _ in area.cells]
    return min(rows), max(rows)


def _erddap_area_chunk(area: Area, start: date, end: date, server: str) -> pd.DataFrame:
    i0, i1 = _lat_range(area)
    s = area.stride
    parts = []
    # Repère ERDDAP -180..180 : indice serveur k = (j + 720) % 1440, lon = -179.875 + 0.25 k.
    for k0, k1 in lon_runs([j for _, j in area.cells], s, offset=NLON // 2):
        sel = (
            f"sst[({start}T12:00:00Z):1:({end}T12:00:00Z)][(0.0)]"
            f"[({lat_of(i0):.3f}):{s}:({lat_of(i1):.3f})]"
            f"[({-179.875 + RES * k0:.3f}):{s}:({-179.875 + RES * k1:.3f})]"
        )
        url = f"{server}/griddap/{config.get('ERDDAP_DATASET')}.csv?" + requests.utils.quote(sel, safe="():,.-T")
        df = pd.read_csv(io.StringIO(_request(url)), skiprows=[1])
        df["time"] = pd.to_datetime(df["time"]).dt.tz_localize(None).dt.normalize()
        parts.append(df.rename(columns={"latitude": "lat", "longitude": "lon"})[["time", "lat", "lon", "sst"]])
    return pd.concat(parts)


def _years_per_request(area: Area) -> int:
    """Années par requête ERDDAP pour rester vers 400 000 valeurs (~20 Mo de CSV) au plus."""
    i0, i1 = _lat_range(area)
    nlon = sum((b - a) // area.stride + 1 for a, b in lon_runs([j for _, j in area.cells], area.stride))
    ncells = ((i1 - i0) // area.stride + 1) * nlon
    return max(1, min(10, 400_000 // (ncells * 366)))


def _fetch_erddap_area(area: Area, start: date, end: date, server: str) -> pd.DataFrame:
    chunks, cur, step = [], start, _years_per_request(area)
    while cur <= end:
        stop = min(date(cur.year + step - 1, 12, 31), end)
        print(f"  … {cur.year}-{stop.year}" if stop.year > cur.year else f"  … {cur.year}")
        chunks.append(_area_mean(_erddap_area_chunk(area, cur, stop, server), area))
        cur = stop + timedelta(days=1)
    df = pd.concat(chunks)
    if df.empty or df["sst"].isna().all():
        raise ValueError("aucune maille océan dans la zone")
    return df


def _parse_psl_grid(text: str) -> pd.DataFrame:
    """Lit la réponse OPeNDAP .ascii d'une grille sst[time][lat][lon] en table time, lat, lon, sst."""
    body = text.split("---------------------------------------------", 1)[-1]
    rows, arrays, block = [], {"time": [], "lat": [], "lon": []}, None
    for line in body.splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith("sst."):
            name = line[4:].split("[", 1)[0]
            block = name if name in ("sst", "time", "lat", "lon") else None
        elif block == "sst":
            idx, values = line.split(",", 1)
            t, a = (int(x) for x in re.findall(r"\d+", idx))
            rows += [(t, a, b, float(v)) for b, v in enumerate(values.split(","))]
        elif block in arrays:
            arrays[block] += [float(v) for v in line.split(",")]
    if not rows or not all(arrays.values()):
        raise ValueError("réponse PSL inattendue")
    t, a, b, v = map(np.array, zip(*rows))
    times = pd.Timestamp("1800-01-01") + pd.to_timedelta(np.array(arrays["time"])[t], unit="D")
    return pd.DataFrame({
        "time": times.normalize(),
        "lat": np.array(arrays["lat"])[a],
        "lon": np.array(arrays["lon"])[b],
        "sst": v,
    })


def _psl_area_year(year: int, area: Area, cache_dir: Path | None) -> pd.DataFrame:
    """Moyenne sur la zone pour une année de PSL ; les années complètes sont mises en cache."""
    psl, step, s = config.get("PSL_URL"), config.get_int("PSL_DAYS"), area.stride
    cache = cache_dir / f"psl_area_{area.key}_{year}.csv" if cache_dir is not None else None
    if cache is not None and cache.exists():
        return pd.read_csv(cache, parse_dates=["time"])
    i0, i1 = _lat_range(area)
    n = _psl_ndays(year)
    parts = []
    for a in range(0, n, step):
        b = min(a + step, n) - 1
        for k0, k1 in lon_runs([j for _, j in area.cells], s):  # repère PSL 0..360 : k = j
            url = (f"{psl}/sst.day.mean.{year}.nc.ascii?"
                   f"sst%5B{a}:1:{b}%5D%5B{i0}:{s}:{i1}%5D%5B{k0}:{s}:{k1}%5D")
            parts.append(_parse_psl_grid(_request(url)))
    df = _area_mean(pd.concat(parts), area)
    if cache is not None and year < date.today().year and df["sst"].notna().any():
        cache_dir.mkdir(parents=True, exist_ok=True)
        df.to_csv(cache, index=False)
    return df


def _fetch_psl_area(area: Area, start: date, end: date, cache_dir: Path | None) -> pd.DataFrame:
    years = range(start.year, end.year + 1)
    print(f"  {len(years)} années à télécharger (plusieurs minutes la première fois ; "
          "une interruption reprend là où elle s'est arrêtée).")
    chunks = []
    with ThreadPoolExecutor(config.get_int("PSL_WORKERS")) as pool:
        futures = [pool.submit(_psl_area_year, y, area, cache_dir) for y in years]
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
    if df["sst"].isna().all():
        raise ValueError("aucune maille océan dans la zone")
    return df[(df["time"] >= pd.Timestamp(start)) & (df["time"] <= pd.Timestamp(end))]


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
        return str(e) or "réponse illisible"
    return type(e).__name__


def _download(
    lat: float, lon: float, start: date, end: date, cache_dir: Path | None
) -> pd.DataFrame:
    return _try_sources(
        lambda server: _fetch_erddap(lat, lon, start, end, server),
        lambda psl_cache: _fetch_psl(lat, lon, start, end, psl_cache),
        cache_dir,
    )


def _try_sources(erddap, psl, cache_dir: Path | None) -> pd.DataFrame:
    """Essaie chaque source dans l'ordre et renvoie la première qui fournit les données.

    `erddap(server)` et `psl(cache_dir)` téléchargent auprès d'une source donnée.
    """
    psl_cache = cache_dir / "psl" if cache_dir is not None else None
    sources = []
    for kind in config.get_list("SOURCES"):
        if kind == "erddap":
            sources += [
                (server.split("/")[2], lambda s=server: erddap(s))
                for server in config.get_list("ERDDAP_SERVERS")
            ]
        elif kind == "psl":
            host = config.get("PSL_URL").split("/")[2]
            sources.append((host, lambda: psl(psl_cache)))
        else:
            raise DownloadError(f"Source inconnue dans MHW_WATCH_SOURCES : {kind!r} (attendu : erddap, psl)")

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
        "  - change les serveurs ou l'ordre des sources dans le fichier .env ;\n"
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
            if s.notna().any():
                return s

    df = _download(lat, lon, start, end, cache_dir).dropna().drop_duplicates("time")
    if df.empty:
        raise DownloadError(f"Aucune SST valide pour ({lat}, {lon}) : le point est-il bien en mer ?")
    s = df.set_index("time")["sst"].asfreq("D").interpolate(limit=5)
    if cache is not None:
        s.to_csv(cache)
    return s


def fetch_sst_area(
    area: Area,
    start: date = date(1982, 1, 1),
    end: date | None = None,
    cache_dir: Path | None = Path("data"),
) -> pd.Series:
    """Série quotidienne de SST (°C) moyennée sur les mailles océan d'une zone (voir wdpa.py).

    Même cache CSV que `fetch_sst`, nommé d'après l'empreinte de la sélection de mailles.
    """
    end = end or (date.today() - timedelta(days=16))
    start = max(start, FIRST_DAY)

    cache = None
    if cache_dir is not None:
        cache_dir.mkdir(parents=True, exist_ok=True)
        cache = cache_dir / f"oisst_area_{area.key}_{start}_{end}.csv"
        if cache.exists():
            s = pd.read_csv(cache, index_col=0, parse_dates=True).iloc[:, 0]
            s.name = "sst"
            if s.notna().any():
                return s

    df = _try_sources(
        lambda server: _fetch_erddap_area(area, start, end, server),
        lambda psl_cache: _fetch_psl_area(area, start, end, psl_cache),
        cache_dir,
    ).dropna().drop_duplicates("time")
    if df.empty:
        raise DownloadError("Aucune SST valide dans la zone : le contour touche-t-il bien la mer ?")
    s = df.set_index("time")["sst"].asfreq("D").interpolate(limit=5)
    if cache is not None:
        s.to_csv(cache)
    return s
