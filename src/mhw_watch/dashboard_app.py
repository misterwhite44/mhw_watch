"""Tableau de bord web (Streamlit) : carte des AMP et historique de chaque site.

Lancement : `mhw-watch dashboard` (ou `streamlit run src/mhw_watch/dashboard_app.py`).
La logique testable est dans `dashboard.py` ; ce fichier ne fait que l'affichage.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import altair as alt
import folium
import pandas as pd
import streamlit as st
from streamlit_folium import st_folium

from mhw_watch import cli, config, dashboard
from mhw_watch.detect import CATEGORIES
from mhw_watch.plot import CAT_COLORS
from mhw_watch.sites import SITES


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--out", default="outputs")
    p.add_argument("--data-dir", default="data")
    return p.parse_known_args(sys.argv[1:])[0]


def build_map(statuses: list[dashboard.SiteStatus], selected: str) -> folium.Map:
    m = folium.Map(location=[20, 0], zoom_start=1, tiles="OpenStreetMap")
    for st_ in statuses:
        s = st_.site
        folium.CircleMarker(
            location=[s.lat, s.lon],
            radius=12 if s.key == selected else 8,
            color="#000" if s.key == selected else "#333",
            weight=3 if s.key == selected else 1,
            fill=True,
            fill_color=st_.color,
            fill_opacity=0.9,
            tooltip=f"{s.name} : {st_.label}",
        ).add_to(m)
    m.fit_bounds([[min(s.site.lat for s in statuses), min(s.site.lon for s in statuses)],
                  [max(s.site.lat for s in statuses), max(s.site.lon for s in statuses)]], padding=(20, 20))
    return m


def legend() -> None:
    items = [("Pas de données", dashboard.NO_DATA_COLOR), ("Pas de vague de chaleur", dashboard.NO_MHW_COLOR)]
    items += [(f"Catégorie {CATEGORIES[c]}", CAT_COLORS[c]) for c in CAT_COLORS]
    html = " ".join(
        f'<span style="white-space:nowrap;margin-right:12px">'
        f'<span style="display:inline-block;width:12px;height:12px;border-radius:50%;'
        f'background:{color};margin-right:4px;vertical-align:middle"></span>{label}</span>'
        for label, color in items
    )
    st.markdown(f'<div style="font-size:0.85em">{html}</div>', unsafe_allow_html=True)


def sst_chart(d: pd.DataFrame) -> alt.Chart:
    d = d.rename_axis("date").reset_index()
    lines = d.melt(id_vars="date", value_vars=["sst", "seas", "thresh"], var_name="série", value_name="°C")
    lines["série"] = lines["série"].map(
        {"sst": "SST observée", "seas": "Moyenne climatologique", "thresh": "Seuil 90e percentile"}
    )
    layers = []
    # Zones de vague de chaleur, colorées par catégorie (entre le seuil et la SST).
    cat = d["category"].clip(lower=1)
    for c, color in CAT_COLORS.items():
        mask = d["in_mhw"].astype(bool) & (cat == c)
        if mask.any():
            area = d.assign(top=d["sst"].where(mask, d["thresh"]))
            layers.append(
                alt.Chart(area).mark_area(color=color, opacity=0.8).encode(x="date:T", y="thresh:Q", y2="top:Q")
            )
    layers.append(
        alt.Chart(lines)
        .mark_line(strokeWidth=1.3)
        .encode(
            x=alt.X("date:T", title=None),
            y=alt.Y("°C:Q", scale=alt.Scale(zero=False), title="Température de surface (°C)"),
            color=alt.Color(
                "série:N",
                scale=alt.Scale(
                    domain=["SST observée", "Moyenne climatologique", "Seuil 90e percentile"],
                    range=["#0b5394", "#777777", "#bbbbbb"],
                ),
                legend=alt.Legend(orient="top", title=None),
            ),
            tooltip=[alt.Tooltip("date:T", format="%d/%m/%Y"), "série:N", alt.Tooltip("°C:Q", format=".2f")],
        )
    )
    return alt.layer(*layers).properties(height=320).interactive(bind_y=False)


def run_analysis(key: str, out: str, data_dir: str) -> None:
    with st.spinner("Téléchargement des données NOAA et analyse… (une à quelques minutes la première fois)"):
        try:
            cli.main(["analyze", "--site", key, "--out", out, "--data-dir", data_dir])
        except SystemExit as e:
            st.error(f"L'analyse a échoué : {e}")
            return
    st.rerun()


def site_details(status: dashboard.SiteStatus, out: str, data_dir: str) -> None:
    s = status.site
    st.subheader(s.name)
    st.caption(f"{s.region} · {s.lat:.2f}, {s.lon:.2f}")

    if not status.has_data:
        st.info(
            "Pas de données pour ce site : il n'a pas encore été analysé. "
            f"Lance l'analyse avec le bouton ci-dessous, ou dans un terminal : `mhw-watch analyze --site {s.key}`"
        )
        if st.button("Lancer l'analyse", type="primary"):
            run_analysis(s.key, out, data_dir)
        return

    st.markdown(
        f'<div style="padding:8px 12px;border-radius:6px;background:{status.color};'
        f'color:{"#222" if status.category in (1,) else "white"};'
        f'font-weight:600;display:inline-block">{status.label}</div>',
        unsafe_allow_html=True,
    )
    c1, c2, c3 = st.columns(3)
    c1.metric("Dernier jour analysé", status.date.strftime("%d/%m/%Y"))
    c2.metric("SST", f"{status.sst:.2f} °C")
    c3.metric("Anomalie", f"{status.anom:+.2f} °C")

    daily = dashboard.read_daily(Path(out), s.key)
    years = sorted(daily.index.year.unique(), reverse=True)
    period = st.selectbox("Période", ["12 mois", "5 ans", "Tout"] + [str(y) for y in years])
    st.altair_chart(sst_chart(dashboard.history_window(daily, period)), use_container_width=True)

    yearly = dashboard.read_yearly(Path(out), s.key)
    if not yearly.empty:
        st.markdown("**Jours de vague de chaleur par an**")
        st.bar_chart(yearly["mhw_days"], color="#d6452b", height=220)

    events = dashboard.read_events(Path(out), s.key)
    st.markdown(f"**Événements détectés : {len(events)}**")
    if not events.empty:
        table = events.sort_values("start", ascending=False).rename(
            columns={
                "start": "Début", "end": "Fin", "peak": "Pic", "duration_days": "Durée (j)",
                "intensity_max": "Intensité max (°C)", "intensity_mean": "Intensité moy. (°C)",
                "intensity_cumulative": "Intensité cumulée (°C·j)", "sst_max": "SST max (°C)",
                "category": "Catégorie",
            }
        )
        for col in ("Début", "Fin", "Pic"):
            table[col] = table[col].dt.strftime("%d/%m/%Y")
        st.dataframe(table, hide_index=True, use_container_width=True)

    if st.button("Mettre à jour les données de ce site"):
        run_analysis(s.key, out, data_dir)


def main() -> None:
    args = parse_args()
    config.load_dotenv()
    st.set_page_config(page_title="MHW Watch", page_icon="🌊", layout="wide")
    st.title("MHW Watch : vagues de chaleur marines dans les AMP")

    statuses = dashboard.all_statuses(Path(args.out))
    by_key = {s.site.key: s for s in statuses}
    if "site" not in st.session_state:
        st.session_state.site = next((s.site.key for s in statuses if s.has_data), next(iter(SITES)))

    left, right = st.columns([1, 1], gap="large")
    with left:
        st.caption("Couleur = état au dernier jour analysé. Clique sur un site pour voir son historique.")
        clicked = st_folium(
            build_map(statuses, st.session_state.site),
            height=460,
            use_container_width=True,
            returned_objects=["last_object_clicked"],
            key="map",
        )
        click = (clicked or {}).get("last_object_clicked")
        if click and click != st.session_state.get("last_click"):
            st.session_state.last_click = click
            site = dashboard.site_at(click["lat"], click["lng"])
            if site and site.key != st.session_state.site:
                st.session_state.site = site.key
                st.rerun()
        legend()

    with right:
        keys = list(SITES)
        choice = st.selectbox(
            "Site",
            keys,
            index=keys.index(st.session_state.site),
            format_func=lambda k: f"{SITES[k].name} ({by_key[k].label.lower()})",
        )
        if choice != st.session_state.site:
            st.session_state.site = choice
            st.rerun()
        site_details(by_key[st.session_state.site], args.out, args.data_dir)


main()
