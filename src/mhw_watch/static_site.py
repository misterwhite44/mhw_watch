"""Export du tableau de bord en site statique (HTML), publiable sur GitHub Pages.

GitHub Pages ne sert que des fichiers : pas de serveur Streamlit. Cette version relit les
mêmes résultats que le tableau de bord (`outputs/<site>/`) et écrit dans un dossier :
- `index.html` : état de chaque AMP, graphiques et événements ;
- `map.html` : carte folium des AMP (affichée dans index.html) ;
- `<site>/` : graphiques PNG et CSV du site, téléchargeables.

Commande : `mhw-watch export-site --out outputs --dest site`
"""

from __future__ import annotations

import shutil
from datetime import datetime, timezone
from html import escape
from pathlib import Path

import folium
import pandas as pd

from . import dashboard
from .detect import CATEGORIES
from .plot import CAT_COLORS
from .sites import SITES, Site

FILES = ["recent.png", "yearly.png", "daily.csv", "events.csv", "yearly_summary.csv"]

CSS = """
:root { --bg: #f7f9fb; --card: #fff; --text: #1d2733; --muted: #5b6b7b; --border: #dde3ea; }
@media (prefers-color-scheme: dark) {
  :root { --bg: #11161c; --card: #1a2129; --text: #e6edf3; --muted: #9aa8b6; --border: #2c3640; }
}
* { box-sizing: border-box; }
body { margin: 0; font: 15px/1.5 system-ui, -apple-system, "Segoe UI", sans-serif;
       background: var(--bg); color: var(--text); }
main { max-width: 1100px; margin: 0 auto; padding: 24px 16px 48px; }
h1 { margin: 0 0 4px; font-size: 1.6em; }
h2 { margin: 0; font-size: 1.25em; }
.muted { color: var(--muted); font-size: 0.9em; }
.card { background: var(--card); border: 1px solid var(--border); border-radius: 10px;
        padding: 16px; margin-top: 20px; }
iframe.map { width: 100%; height: 460px; border: 0; border-radius: 8px; }
.legend span.dot { display: inline-block; width: 12px; height: 12px; border-radius: 50%;
                   margin-right: 4px; vertical-align: middle; }
.legend > span { white-space: nowrap; margin-right: 12px; font-size: 0.85em; }
table { border-collapse: collapse; width: 100%; font-size: 0.9em; }
th, td { text-align: left; padding: 6px 8px; border-bottom: 1px solid var(--border); }
.overview td:first-child a { color: inherit; font-weight: 600; }
.badge { display: inline-block; padding: 4px 10px; border-radius: 6px; font-weight: 600;
         color: #fff; font-size: 0.9em; }
.metrics { display: flex; gap: 24px; flex-wrap: wrap; margin: 12px 0; }
.metrics div b { display: block; font-size: 1.3em; }
img { max-width: 100%; height: auto; border-radius: 6px; background: #fff; }
.scroll { overflow-x: auto; }
a { color: #2b8cbe; }
"""


def _badge(status: dashboard.SiteStatus) -> str:
    color = "#222" if status.category == 1 else "#fff"
    return (f'<span class="badge" style="background:{status.color};color:{color}">'
            f"{escape(status.label)}</span>")


def _legend() -> str:
    items = [("Pas de données", dashboard.NO_DATA_COLOR), ("Pas de vague de chaleur", dashboard.NO_MHW_COLOR)]
    items += [(f"Catégorie {CATEGORIES[c]}", CAT_COLORS[c]) for c in CAT_COLORS]
    return '<div class="legend">' + "".join(
        f'<span><span class="dot" style="background:{color}"></span>{escape(label)}</span>'
        for label, color in items
    ) + "</div>"


def build_map(statuses: list[dashboard.SiteStatus]) -> folium.Map:
    """Carte des AMP ; un clic sur un marqueur mène à la fiche du site dans index.html."""
    m = folium.Map(location=[15, 0], zoom_start=2, min_zoom=1, tiles="OpenStreetMap")
    for st in statuses:
        s = st.site
        popup = (f'<b>{escape(s.name)}</b><br>{escape(st.label)}<br>'
                 f'<a href="index.html#{s.key}" target="_top">Voir l\'historique</a>')
        folium.CircleMarker(
            location=[s.lat, s.lon], radius=9, color="#333", weight=1, fill=True,
            fill_color=st.color, fill_opacity=0.9,
            tooltip=f"{s.name} : {st.label}", popup=folium.Popup(popup, max_width=260),
        ).add_to(m)
    return m


def _events_table(events: pd.DataFrame, n: int = 10) -> str:
    if events.empty:
        return '<p class="muted">Aucun événement détecté.</p>'
    top = events.sort_values("intensity_cumulative", ascending=False).head(n)
    rows = "".join(
        f"<tr><td>{e.start:%d/%m/%Y}</td><td>{e.end:%d/%m/%Y}</td><td>{int(e.duration_days)} j</td>"
        f"<td>{e.intensity_max:+.2f} °C</td><td>{e.intensity_cumulative:.1f} °C·j</td>"
        f"<td>{escape(str(e.category))}</td></tr>"
        for e in top.itertuples()
    )
    return (f'<div class="scroll"><table><thead><tr><th>Début</th><th>Fin</th><th>Durée</th>'
            f"<th>Intensité max</th><th>Intensité cumulée</th><th>Catégorie</th></tr></thead>"
            f"<tbody>{rows}</tbody></table></div>")


def _site_section(status: dashboard.SiteStatus, out_dir: Path) -> str:
    s = status.site
    head = (f'<section class="card" id="{s.key}"><h2>{escape(s.name)}</h2>'
            f'<p class="muted">{escape(s.region)} · {s.lat:.2f}, {s.lon:.2f}</p>{_badge(status)}')
    zone = dashboard.zone_label(out_dir, s.key)
    if zone:
        head += f'<p class="muted">Zone analysée : {escape(zone)}</p>'
    if not status.has_data:
        return head + '<p class="muted">Pas encore de données pour ce site.</p></section>'
    events = dashboard.read_events(out_dir, s.key)
    files = [f for f in FILES if (out_dir / s.key / f).is_file()]
    imgs = "".join(
        f'<p><img src="{s.key}/{f}" alt="{alt}" loading="lazy"></p>'
        for f, alt in [("recent.png", "SST des 12 derniers mois"), ("yearly.png", "Jours de vague de chaleur par an")]
        if f in files
    )
    downloads = " · ".join(f'<a href="{s.key}/{f}">{f}</a>' for f in files if f.endswith(".csv"))
    return (
        head
        + f'<div class="metrics"><div><span class="muted">Dernier jour analysé</span>'
          f"<b>{status.date:%d/%m/%Y}</b></div>"
          f'<div><span class="muted">SST</span><b>{status.sst:.2f} °C</b></div>'
          f'<div><span class="muted">Anomalie</span><b>{status.anom:+.2f} °C</b></div>'
          f'<div><span class="muted">Événements depuis 1982</span><b>{len(events)}</b></div></div>'
        + imgs
        + "<h3>Événements les plus intenses</h3>"
        + _events_table(events)
        + (f'<p class="muted">Données : {downloads}</p>' if downloads else "")
        + "</section>"
    )


def build_site(out_dir: Path | str, dest: Path | str, sites: dict[str, Site] = SITES) -> Path:
    """Écrit le site statique dans `dest` et renvoie le chemin d'index.html."""
    out_dir, dest = Path(out_dir), Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    statuses = dashboard.all_statuses(out_dir, sites)

    build_map(statuses).save(str(dest / "map.html"))
    for st in statuses:
        if st.has_data:
            (dest / st.site.key).mkdir(exist_ok=True)
            for f in FILES:
                if (out_dir / st.site.key / f).is_file():
                    shutil.copy2(out_dir / st.site.key / f, dest / st.site.key / f)

    overview = "".join(
        f'<tr><td><a href="#{st.site.key}">{escape(st.site.name)}</a></td><td>{_badge(st)}</td>'
        f"<td>{f'{st.anom:+.2f} °C' if st.has_data else '–'}</td>"
        f"<td>{f'{st.date:%d/%m/%Y}' if st.has_data else '–'}</td></tr>"
        for st in statuses
    )
    generated = datetime.now(timezone.utc).strftime("%d/%m/%Y à %H:%M UTC")
    html = f"""<!doctype html>
<html lang="fr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>MHW Watch</title>
<style>{CSS}</style>
</head>
<body>
<main>
<h1>MHW Watch : vagues de chaleur marines dans les AMP</h1>
<p class="muted">Température de surface NOAA OISST v2.1, méthode Hobday et al. (2016), climatologie 1991-2020.
Mis à jour le {generated}. Les données NOAA sont publiées avec environ deux semaines de retard.</p>
<div class="card">
<iframe class="map" src="map.html" title="Carte des aires marines protégées"></iframe>
{_legend()}
</div>
<div class="card scroll">
<table class="overview"><thead><tr><th>Site</th><th>État au dernier jour</th><th>Anomalie</th><th>Date</th></tr></thead>
<tbody>{overview}</tbody></table>
</div>
{"".join(_site_section(st, out_dir) for st in statuses)}
<p class="muted">Code source : <a href="https://github.com/misterwhite44/mhw_watch">github.com/misterwhite44/mhw_watch</a></p>
</main>
</body>
</html>
"""
    index = dest / "index.html"
    index.write_text(html, encoding="utf-8")
    return index
