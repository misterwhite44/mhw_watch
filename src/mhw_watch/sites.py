"""Aires marines protégées (AMP) suivies par défaut.

Les coordonnées sont un point représentatif en mer, pas le contour de l'AMP.
Ajoutez vos propres sites ici (ou passez --lat/--lon en ligne de commande).
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Site:
    key: str
    name: str
    lat: float
    lon: float  # -180..180
    region: str


SITES: dict[str, Site] = {
    s.key: s
    for s in [
        Site("port-cros", "Parc national de Port-Cros", 43.00, 6.40, "Méditerranée"),
        Site("scandola", "Réserve naturelle de Scandola", 42.37, 8.50, "Méditerranée"),
        Site("iroise", "Parc naturel marin d'Iroise", 48.30, -5.10, "Atlantique Nord-Est"),
        Site("great-barrier-reef", "Grande Barrière de corail", -18.30, 147.70, "Pacifique Sud-Ouest"),
        Site("galapagos", "Réserve marine des Galápagos", -0.60, -90.70, "Pacifique Est"),
        Site("papahanaumokuakea", "Papahānaumokuākea", 23.60, -164.70, "Pacifique Nord"),
    ]
}


def get_site(key: str) -> Site:
    try:
        return SITES[key]
    except KeyError:
        known = ", ".join(SITES)
        raise SystemExit(f"Site inconnu : {key!r}. Sites disponibles : {known}") from None
