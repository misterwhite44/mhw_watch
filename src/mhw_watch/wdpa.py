"""Contours des AMP (WDPA) et choix des mailles OISST à moyenner.

Source des contours : World Database on Protected Areas (UNEP-WCMC / IUCN), interrogée via
le service cartographique public d'UNEP-WCMC (ArcGIS REST, GeoJSON, sans clé d'API).
Chaque contour est gardé dans `data/wdpa/<site_id>.geojson`. Pour utiliser un contour
téléchargé à la main sur protectedplanet.net (ou tracé soi-même), il suffit de déposer le
fichier GeoJSON sous ce nom : il est alors utilisé tel quel, sans accès réseau.

Conditions d'utilisation des données WDPA : https://www.protectedplanet.net/en/legal
(usage non commercial, citer « UNEP-WCMC and IUCN, Protected Planet »).
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlencode

import numpy as np

from . import config

RES = 0.25  # pas de la grille OISST, en degrés
NLAT, NLON = 720, 1440
# En dessous de ce nombre de centres de maille dans le contour, on prend toutes les mailles qui
# touchent le rectangle englobant : une ou deux mailles côtières peuvent être toutes « terre ».
MIN_INSIDE = 4


@dataclass(frozen=True)
class Area:
    """Mailles OISST retenues pour une AMP.

    i : indice de latitude (lat = -89.875 + 0.25 i) ; j : indice de longitude dans le repère
    0-360° E (lon = 0.125 + 0.25 j). `stride` est le pas de sous-échantillonnage appliqué
    dans les deux directions quand le contour couvre plus de MHW_WATCH_MAX_CELLS mailles.
    """

    cells: tuple[tuple[int, int], ...]
    stride: int = 1
    inside: bool = True  # False : petite AMP, mailles touchant son rectangle englobant

    @property
    def key(self) -> str:
        """Empreinte courte de la sélection, pour nommer les fichiers de cache."""
        raw = f"{self.stride}:" + ";".join(f"{i},{j}" for i, j in self.cells)
        return hashlib.md5(raw.encode()).hexdigest()[:10]

    def describe(self) -> str:
        n = len(self.cells)
        if not self.inside:
            return f"{n} maille(s) 0,25° autour de l'AMP (trop petite pour la grille)"
        sub = f", une sur {self.stride} dans chaque direction" if self.stride > 1 else ""
        return f"{n} maille(s) 0,25° dans le contour{sub}"


def lat_of(i):
    return -89.875 + RES * np.asarray(i)


def cell_index(lat, lon):
    """Indices (i, j) de la maille contenant (lat, lon) ; lon dans n'importe quel repère."""
    i = np.clip(np.floor((np.asarray(lat) + 90) / RES).astype(int), 0, NLAT - 1)
    j = np.floor((np.asarray(lon) % 360) / RES).astype(int) % NLON
    return i, j


# --- Contours -----------------------------------------------------------------------

def _query_url(site_id: int) -> str:
    params = {
        "where": f"site_id={int(site_id)}",
        "outFields": "site_id,name",
        "outSR": "4326",
        "maxAllowableOffset": "0.01",  # simplification ~1 km : bien en dessous de la maille 0,25°
        "geometryPrecision": "4",
        "f": "geojson",
    }
    return f"{config.get('WDPA_URL').rstrip('/')}/query?{urlencode(params)}"


def fetch_geometry(site_id: int, cache_dir: Path | None = Path("data")) -> dict:
    """GeoJSON (FeatureCollection) du contour WDPA `site_id`, depuis le cache ou le réseau."""
    from .data import _request  # import local : data.py importe ce module

    cache = cache_dir / "wdpa" / f"{site_id}.geojson" if cache_dir is not None else None
    if cache is not None and cache.is_file():
        return json.loads(cache.read_text(encoding="utf-8"))
    gj = json.loads(_request(_query_url(site_id)))
    if "error" in gj:
        raise ValueError(f"service WDPA : {gj['error'].get('message', gj['error'])}")
    if not polygons(gj):
        raise ValueError(f"aucun contour WDPA pour site_id={site_id}")
    if cache is not None:
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps(gj), encoding="utf-8")
    return gj


def polygons(geojson: dict) -> list[list[np.ndarray]]:
    """Liste de polygones, chacun une liste d'anneaux (N, 2) lon/lat (extérieur puis trous).

    Accepte FeatureCollection, Feature ou géométrie (Polygon / MultiPolygon). Un contour qui
    traverse l'antiméridien (étendue > 180°) est déplié en longitudes 0-360 pour rester d'un
    seul tenant.
    """
    if geojson.get("type") == "FeatureCollection":
        geoms = [f.get("geometry") for f in geojson.get("features", [])]
    elif geojson.get("type") == "Feature":
        geoms = [geojson.get("geometry")]
    else:
        geoms = [geojson]
    polys = []
    for g in geoms:
        if not g:
            continue
        if g["type"] == "Polygon":
            parts = [g["coordinates"]]
        elif g["type"] == "MultiPolygon":
            parts = g["coordinates"]
        else:
            continue
        for rings in parts:
            polys.append([np.asarray(r, dtype=float)[:, :2] for r in rings if len(r) >= 3])
    polys = [p for p in polys if p]
    if polys:
        lons = np.concatenate([r[:, 0] for p in polys for r in p])
        if lons.max() - lons.min() > 180:
            for p in polys:
                for r in p:
                    r[:, 0] = np.where(r[:, 0] < 0, r[:, 0] + 360, r[:, 0])
    return polys


def contains(polys: list[list[np.ndarray]], lon, lat) -> np.ndarray:
    """Points (lon, lat) à l'intérieur d'au moins un polygone (règle pair-impair, trous inclus)."""
    lon, lat = np.asarray(lon, dtype=float), np.asarray(lat, dtype=float)
    result = np.zeros(lon.shape, dtype=bool)
    for rings in polys:
        inside = np.zeros(lon.shape, dtype=bool)
        for r in rings:
            ax, ay = r[:, 0], r[:, 1]
            bx, by = np.roll(ax, -1), np.roll(ay, -1)
            for x0, y0, x1, y1 in zip(ax, ay, bx, by):
                if y0 == y1:
                    continue
                crosses = (y0 > lat) != (y1 > lat)
                xint = x0 + (lat - y0) * (x1 - x0) / (y1 - y0)
                inside ^= crosses & (lon < xint)
        result |= inside
    return result


def bounds(polys: list[list[np.ndarray]]) -> tuple[float, float, float, float]:
    pts = np.concatenate([r for p in polys for r in p])
    return pts[:, 0].min(), pts[:, 1].min(), pts[:, 0].max(), pts[:, 1].max()


def _grid(lon0, lat0, lon1, lat1, pad: int = 0) -> tuple[np.ndarray, np.ndarray]:
    """Indices (i, k) des mailles couvrant le rectangle ; k est l'indice de longitude dans le
    repère (éventuellement déplié au-delà de 180°) du contour : lon = 0.125 + 0.25 k."""
    i0 = max(int(cell_index(lat0, 0)[0]) - pad, 0)
    i1 = min(int(cell_index(lat1, 0)[0]) + pad, NLAT - 1)
    k0, k1 = math.floor(lon0 / RES) - pad, math.floor(lon1 / RES) + pad
    return np.meshgrid(np.arange(i0, i1 + 1), np.arange(k0, k1 + 1), indexing="ij")


def select_cells(polys: list[list[np.ndarray]], max_cells: int | None = None) -> Area:
    """Mailles OISST dont le centre tombe dans le contour, sous-échantillonnées si besoin.

    Les mailles « terre » ne sont pas connues ici : elles reviennent sans valeur (NaN) du
    serveur et sont ignorées dans la moyenne. Une petite AMP (moins de MIN_INSIDE centres
    dedans) prend toutes les mailles qui touchent son rectangle englobant, élargi d'une maille
    de chaque côté si ce rectangle en compte moins de MIN_INSIDE.
    """
    max_cells = max_cells or config.get_int("MAX_CELLS")
    ii, kk = _grid(*bounds(polys))
    mask = contains(polys, kk * RES + RES / 2, lat_of(ii))
    inside = int(mask.sum()) >= MIN_INSIDE
    if not inside:
        if ii.size < MIN_INSIDE:
            ii, kk = _grid(*bounds(polys), pad=1)
        mask = np.ones(ii.shape, dtype=bool)
    stride = 1
    while mask[::stride, ::stride].sum() > max_cells:
        stride += 1
    sub = mask[::stride, ::stride]
    cells = tuple(sorted(
        (int(i), int(k % NLON)) for i, k in zip(ii[::stride, ::stride][sub], kk[::stride, ::stride][sub])
    ))
    return Area(cells=cells, stride=stride, inside=inside)


def area_for_site(site_id: int, cache_dir: Path | None = Path("data")) -> Area:
    return select_cells(polygons(fetch_geometry(site_id, cache_dir)))


def lon_runs(js, stride: int, offset: int = 0) -> list[tuple[int, int]]:
    """Plages [a, b] (au pas `stride`) couvrant les indices de longitude serveur (j + offset) % 1440.

    Une seule plage d'ordinaire ; une AMP à cheval sur le bord du repère du serveur (0° pour
    PSL, 180° pour ERDDAP en -180..180) en donne deux, donc deux requêtes.
    """
    ks = sorted({(j + offset) % NLON for j in js})
    runs, start = [], ks[0]
    for prev, k in zip(ks, ks[1:]):
        if k - prev > NLON // 2:
            runs.append((start, prev))
            start = k
    runs.append((start, ks[-1]))
    return runs
