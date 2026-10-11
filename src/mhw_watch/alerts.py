"""Alertes quand une AMP entre en vague de chaleur de catégorie II ou plus.

Relit les résultats de `mhw-watch analyze` (`outputs/<site>/daily.csv`), compare l'état de
chaque site à celui mémorisé lors du passage précédent (fichier JSON), et n'alerte que sur
une transition : entrée en catégorie II, ou aggravation (II → III, III → IV) au cours du
même épisode. Un épisode se termine quand le site sort de la vague de chaleur ; une nouvelle
entrée en catégorie II déclenche alors une nouvelle alerte.

Canaux, chacun actif seulement si ses réglages sont présents (variables MHW_WATCH_*) :
- e-mail (SMTP) : SMTP_HOST, ALERT_EMAIL_TO, et en général SMTP_USER / SMTP_PASSWORD ;
- Bluesky : BLUESKY_HANDLE, BLUESKY_APP_PASSWORD ;
- Mastodon : MASTODON_INSTANCE, MASTODON_TOKEN.

Commande : `mhw-watch alert --out outputs --state alerts/state.json [--dry-run]`
"""

from __future__ import annotations

import json
import smtplib
import ssl
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from email.message import EmailMessage
from pathlib import Path
from typing import Callable

import pandas as pd
import requests

from . import config, dashboard
from .detect import CATEGORIES
from .sites import SITES, Site

MIN_CATEGORY = 2  # II - Forte


@dataclass(frozen=True)
class Alert:
    status: dashboard.SiteStatus
    episode_start: pd.Timestamp | None

    @property
    def site(self) -> Site:
        return self.status.site

    @property
    def category_label(self) -> str:
        return CATEGORIES[self.status.category]

    def text(self, url: str = "") -> str:
        s = self.status
        lines = [
            f"Vague de chaleur marine, catégorie {self.category_label}, "
            f"{s.site.name} ({s.site.region}).",
            f"Au {s.date:%d/%m/%Y} : SST {s.sst:.1f} °C, anomalie {s.anom:+.1f} °C.",
        ]
        if self.episode_start is not None:
            lines.append(f"Épisode en cours depuis le {self.episode_start:%d/%m/%Y}.")
        if url:
            lines.append(url)
        return "\n".join(lines)


# --- État mémorisé entre deux passages ------------------------------------------------------


def load_state(path: Path) -> dict:
    path = Path(path)
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        print(f"État d'alerte illisible ({path}), on repart de zéro.", file=sys.stderr)
        return {}


def save_state(path: Path, state: dict) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def episode_start(daily: pd.DataFrame) -> pd.Timestamp | None:
    """Premier jour de la vague de chaleur en cours au dernier jour de la série."""
    flags = daily.dropna(subset=["sst"])["in_mhw"].astype(str).str.lower() == "true"
    if flags.empty or not flags.iloc[-1]:
        return None
    off = flags[~flags]
    return flags.index[0] if off.empty else flags[flags.index > off.index[-1]].index[0]


def evaluate(
    statuses: list[dashboard.SiteStatus], state: dict, starts: dict[str, pd.Timestamp | None] | None = None
) -> tuple[list[Alert], dict]:
    """Alertes à envoyer et nouvel état.

    `state[clé]` garde la catégorie du dernier jour (`category`), la plus haute catégorie déjà
    signalée pendant l'épisode en cours (`alerted`) et la date des données (`date`).
    Un site sans données garde son état précédent.
    """
    starts = starts or {}
    alerts: list[Alert] = []
    new_state = dict(state)
    for st in statuses:
        if not st.has_data:
            continue
        prev = state.get(st.site.key, {})
        alerted = int(prev.get("alerted", 0)) if st.category > 0 else 0
        if st.category >= MIN_CATEGORY and st.category > alerted:
            alerts.append(Alert(st, starts.get(st.site.key)))
            alerted = st.category
        new_state[st.site.key] = {
            "category": st.category,
            "alerted": alerted,
            "date": f"{st.date:%Y-%m-%d}",
        }
    return alerts, new_state


# --- Canaux -----------------------------------------------------------------------------------


def _timeout() -> tuple[int, int]:
    return config.get_int("CONNECT_TIMEOUT"), 60


def send_email(alerts: list[Alert], url: str) -> None:
    host, to = config.get("SMTP_HOST"), config.get_list("ALERT_EMAIL_TO")
    port = config.get_int("SMTP_PORT")
    user, password = config.get("SMTP_USER"), config.get("SMTP_PASSWORD")
    msg = EmailMessage()
    names = ", ".join(a.site.name for a in alerts)
    msg["Subject"] = f"[MHW Watch] Vague de chaleur marine catégorie II+ : {names}"
    msg["From"] = config.get("ALERT_EMAIL_FROM") or user
    msg["To"] = ", ".join(to)
    msg.set_content("\n\n".join(a.text() for a in alerts) + (f"\n\nTableau de bord : {url}\n" if url else "\n"))
    context = ssl.create_default_context()
    if port == 465:
        server = smtplib.SMTP_SSL(host, port, context=context, timeout=60)
    else:
        server = smtplib.SMTP(host, port, timeout=60)
    with server:
        if port != 465:
            server.starttls(context=context)
        if user:
            server.login(user, password)
        server.send_message(msg)


def _post_bluesky(text: str, url: str) -> None:
    base = config.get("BLUESKY_SERVICE").rstrip("/")
    session = requests.post(
        f"{base}/xrpc/com.atproto.server.createSession",
        json={"identifier": config.get("BLUESKY_HANDLE"), "password": config.get("BLUESKY_APP_PASSWORD")},
        timeout=_timeout(),
    )
    session.raise_for_status()
    auth = session.json()
    record = {
        "$type": "app.bsky.feed.post",
        "text": text,
        "createdAt": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
        "langs": ["fr"],
    }
    if url and url in text:
        # Bluesky ne rend pas les liens cliquables tout seul : il faut une « facet » (octets UTF-8).
        start = len(text[: text.index(url)].encode("utf-8"))
        record["facets"] = [{
            "index": {"byteStart": start, "byteEnd": start + len(url.encode("utf-8"))},
            "features": [{"$type": "app.bsky.richtext.facet#link", "uri": url}],
        }]
    r = requests.post(
        f"{base}/xrpc/com.atproto.repo.createRecord",
        headers={"Authorization": f"Bearer {auth['accessJwt']}"},
        json={"repo": auth["did"], "collection": "app.bsky.feed.post", "record": record},
        timeout=_timeout(),
    )
    r.raise_for_status()


def send_bluesky(alerts: list[Alert], url: str) -> None:
    for a in alerts:
        text = a.text(url)
        if len(text) > 300:  # limite Bluesky (en graphèmes ; les caractères suffisent ici)
            text = a.text()
        _post_bluesky(text, url)


def send_mastodon(alerts: list[Alert], url: str) -> None:
    base = config.get("MASTODON_INSTANCE").rstrip("/")
    if not base.startswith("http"):
        base = "https://" + base
    for a in alerts:
        r = requests.post(
            f"{base}/api/v1/statuses",
            headers={"Authorization": f"Bearer {config.get('MASTODON_TOKEN')}"},
            data={"status": a.text(url), "language": "fr"},
            timeout=_timeout(),
        )
        r.raise_for_status()


def channels() -> dict[str, Callable[[list[Alert], str], None]]:
    """Canaux configurés (ceux dont les réglages obligatoires sont présents)."""
    out = {}
    if config.get("SMTP_HOST") and config.get("ALERT_EMAIL_TO"):
        out["e-mail"] = send_email
    if config.get("BLUESKY_HANDLE") and config.get("BLUESKY_APP_PASSWORD"):
        out["Bluesky"] = send_bluesky
    if config.get("MASTODON_INSTANCE") and config.get("MASTODON_TOKEN"):
        out["Mastodon"] = send_mastodon
    return out


# --- Point d'entrée ---------------------------------------------------------------------------


def run(out_dir: Path, state_path: Path, dry_run: bool = False, sites: dict[str, Site] = SITES) -> int:
    """Évalue, envoie et mémorise. Code de retour 1 si un canal a échoué."""
    statuses, starts = [], {}
    for s in sites.values():
        daily = dashboard.read_daily(out_dir, s.key)
        statuses.append(dashboard.status_from_daily(s, daily))
        starts[s.key] = episode_start(daily) if daily is not None else None

    state = load_state(state_path)
    alerts, new_state = evaluate(statuses, state, starts)
    url = config.get("SITE_URL")

    if not alerts:
        print("Aucune nouvelle alerte (pas d'entrée en catégorie II ou plus).")
    for a in alerts:
        print(f"\n--- Alerte : {a.site.name} ---\n{a.text(url)}")

    if dry_run:
        print("\n(--dry-run : rien n'est envoyé ni mémorisé)")
        return 0

    available = channels()
    if alerts and not available:
        print("\nAucun canal configuré (voir README, section Alertes) : alertes affichées seulement.")
    failed = []
    for name, send in available.items() if alerts else []:
        try:
            send(alerts, url)
            print(f"Envoyé par {name}.")
        except Exception as e:  # un canal en panne n'empêche pas les autres
            print(f"Échec de l'envoi par {name} : {e}", file=sys.stderr)
            failed.append(name)

    if available and alerts and len(failed) == len(available):
        # Rien n'est parti : on ne mémorise pas, pour réessayer au prochain passage.
        print("Aucun envoi réussi : état non mis à jour.", file=sys.stderr)
        return 1
    save_state(state_path, new_state)
    return 1 if failed else 0
