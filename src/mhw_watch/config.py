"""Réglages des sources de données.

Chaque réglage se lit dans une variable d'environnement MHW_WATCH_<NOM>, qu'on peut mettre
dans un fichier `.env` à la racine du projet (voir `.env.example`). Une variable déjà
définie dans le terminal l'emporte sur le `.env` ; un réglage absent prend sa valeur par défaut.
"""

from __future__ import annotations

import os
from pathlib import Path

PREFIX = "MHW_WATCH_"

DEFAULTS = {
    # Ordre des sources essayées : "erddap" et/ou "psl", séparées par des virgules.
    "SOURCES": "erddap,psl",
    # Serveurs ERDDAP servant le jeu de données, essayés dans l'ordre.
    "ERDDAP_SERVERS": "https://coastwatch.pfeg.noaa.gov/erddap,https://upwell.pfeg.noaa.gov/erddap",
    "ERDDAP_DATASET": "ncdcOisst21Agg_LonPM180",
    # Serveur THREDDS/OPeNDAP de NOAA PSL (un fichier sst.day.mean.AAAA.nc par année).
    "PSL_URL": "https://psl.noaa.gov/thredds/dodsC/Datasets/noaa.oisst.v2.highres",
    "PSL_DAYS": "90",  # jours par requête : PSL coupe les requêtes au-delà d'environ 60 s
    "PSL_WORKERS": "2",  # années téléchargées en parallèle (PSL limite le débit au-delà)
    "CONNECT_TIMEOUT": "10",  # s : un serveur injoignable est vite abandonné
    "READ_TIMEOUT": "180",  # s : une grosse requête peut être longue à préparer côté serveur
    "RETRIES": "1",  # nouvelles tentatives par serveur après un échec réseau
    # Alertes (`mhw-watch alert`) : un canal vide reste désactivé.
    "SITE_URL": "https://misterwhite44.github.io/mhw_watch/",  # lien ajouté aux alertes
    "SMTP_HOST": "",
    "SMTP_PORT": "587",  # 587 = STARTTLS, 465 = SSL direct
    "SMTP_USER": "",
    "SMTP_PASSWORD": "",
    "ALERT_EMAIL_FROM": "",  # par défaut SMTP_USER
    "ALERT_EMAIL_TO": "",  # destinataires, séparés par des virgules
    "BLUESKY_SERVICE": "https://bsky.social",
    "BLUESKY_HANDLE": "",
    "BLUESKY_APP_PASSWORD": "",  # mot de passe d'application, pas celui du compte
    "MASTODON_INSTANCE": "",  # ex. https://mastodon.social
    "MASTODON_TOKEN": "",  # jeton d'application avec le droit write:statuses
}


def load_dotenv(path: Path = Path(".env")) -> None:
    """Charge un fichier .env (lignes CLE=valeur, # pour les commentaires) sans écraser l'existant."""
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip().removeprefix("export ").strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


def get(name: str) -> str:
    return os.environ.get(PREFIX + name, "").strip() or DEFAULTS[name]


def get_int(name: str) -> int:
    try:
        return int(get(name))
    except ValueError:
        raise ValueError(f"{PREFIX}{name} doit être un nombre entier (valeur : {get(name)!r})") from None


def get_list(name: str) -> list[str]:
    return [v.strip().rstrip("/") for v in get(name).split(",") if v.strip()]
