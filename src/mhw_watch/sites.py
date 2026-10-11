"""Aires marines protégées (AMP) suivies par défaut, regroupées par région.

Chaque site a un identifiant WDPA (World Database on Protected Areas, protectedplanet.net) :
l'analyse moyenne alors la SST sur les mailles océan situées dans le contour officiel de
l'AMP (voir wdpa.py). Les coordonnées lat/lon sont un point représentatif en mer, utilisé
pour la carte et comme repli si le contour est indisponible (ou avec --area point).
Ajoutez vos propres sites ici (ou passez --lat/--lon en ligne de commande).
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass


def slugify(text: str) -> str:
    """« Atlantique Nord-Est » → « atlantique-nord-est »."""
    ascii_ = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return "-".join(ascii_.lower().replace("-", " ").split())


@dataclass(frozen=True)
class Site:
    key: str
    name: str
    lat: float
    lon: float  # -180..180
    region: str
    wdpa_id: int | None = None  # site_id WDPA ; None = analyse au point seulement

    @property
    def region_key(self) -> str:
        return slugify(self.region)


SITES: dict[str, Site] = {
    s.key: s
    for s in [
        Site("port-cros", "Parc national de Port-Cros", 43.00, 6.40, "Méditerranée", 663),
        Site("scandola", "Réserve naturelle de Scandola", 42.37, 8.50, "Méditerranée", 7168),
        Site("calanques", "Parc national des Calanques", 43.18, 5.45, "Méditerranée", 555559618),
        Site("bouches-de-bonifacio", "Réserve naturelle des Bouches de Bonifacio", 41.40, 9.20,
             "Méditerranée", 178271),
        Site("cerbere-banyuls", "Réserve naturelle marine de Cerbère-Banyuls", 42.47, 3.17,
             "Méditerranée", 4044),
        Site("iroise", "Parc naturel marin d'Iroise", 48.30, -5.10, "Atlantique Nord-Est", 388659),
        Site("great-barrier-reef", "Grande Barrière de corail", -18.30, 147.70, "Pacifique Sud-Ouest", 2628),
        Site("galapagos", "Réserve marine des Galápagos", -0.60, -90.70, "Pacifique Est", 11753),
        Site("papahanaumokuakea", "Papahānaumokuākea", 23.60, -164.70, "Pacifique Nord", 220201),
    ]
}


def regions(sites: dict[str, Site] = SITES) -> dict[str, list[Site]]:
    """Sites groupés par clé de région, dans l'ordre de SITES."""
    out: dict[str, list[Site]] = {}
    for s in sites.values():
        out.setdefault(s.region_key, []).append(s)
    return out


def sites_in_region(region: str, sites: dict[str, Site] = SITES) -> dict[str, Site]:
    """Sites d'une région (clé ou nom, sans tenir compte des accents) ; « all » = tous."""
    if not region or region == "all":
        return dict(sites)
    by_region = regions(sites)
    key = slugify(region)
    if key not in by_region:
        known = ", ".join(by_region)
        raise SystemExit(f"Région inconnue : {region!r}. Régions disponibles : {known}")
    return {s.key: s for s in by_region[key]}


def get_site(key: str) -> Site:
    try:
        return SITES[key]
    except KeyError:
        known = ", ".join(SITES)
        raise SystemExit(f"Site inconnu : {key!r}. Sites disponibles : {known}") from None
