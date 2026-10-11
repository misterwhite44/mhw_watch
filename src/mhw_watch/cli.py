"""Interface en ligne de commande.

Exemples :
    python -m mhw_watch sites
    python -m mhw_watch analyze --site port-cros
    python -m mhw_watch analyze --lat 43.2 --lon 5.3 --name "Calanques"
    python -m mhw_watch analyze --demo          # sans réseau, données synthétiques
    python -m mhw_watch dashboard               # tableau de bord web (navigateur)
    python -m mhw_watch analyze --site all      # tous les sites connus
    python -m mhw_watch analyze --region mediterranee       # toutes les AMP d'une région
    python -m mhw_watch analyze --site iroise --area point  # point représentatif, pas le contour
    python -m mhw_watch export-site --dest site # tableau de bord en HTML statique (GitHub Pages)
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

import pandas as pd

from . import config, detect, plot
from .sites import Site, get_site, regions, sites_in_region, slugify


def cmd_sites(args: argparse.Namespace) -> None:
    for region, sites in regions(sites_in_region(args.region)).items():
        print(f"{region}  ({sites[0].region})")
        for s in sites:
            wdpa_id = f"WDPA {s.wdpa_id}" if s.wdpa_id else "point seul"
            print(f"  {s.key:22} {s.name:44} {s.lat:7.2f} {s.lon:8.2f}  {wdpa_id}")


def _selected_sites(args: argparse.Namespace) -> dict[str, Site] | None:
    """Sites à analyser en lot (--region, ou --site all filtré par MHW_WATCH_REGION), sinon None."""
    if args.demo or args.lat is not None:
        return None
    if args.region:
        return sites_in_region(args.region)
    if args.site == "all":
        return sites_in_region(config.get("REGION"))
    return None


def cmd_analyze(args: argparse.Namespace) -> None:
    batch = _selected_sites(args)
    if batch is not None:
        # Un site en échec n'empêche pas les autres ; code de sortie 1 seulement si tous échouent.
        failed = []
        for key in batch:
            try:
                cmd_analyze(argparse.Namespace(**{**vars(args), "site": key, "region": None}))
            except SystemExit as e:
                print(e, file=sys.stderr)
                failed.append(key)
        write_region_summary(batch, Path(args.out), args.region or config.get("REGION"))
        if failed:
            print(f"\nÉchec pour : {', '.join(failed)}", file=sys.stderr)
            if len(failed) == len(batch):
                sys.exit(1)
        return
    zone = None
    if args.demo:
        from .synthetic import synthetic_sst

        key, name, sst = "demo", "Site de démonstration (données synthétiques)", synthetic_sst()
    else:
        from .data import DownloadError, fetch_sst, fetch_sst_area

        site = None
        if args.lat is not None and args.lon is not None:
            key, name, lat, lon = args.name.lower().replace(" ", "-"), args.name, args.lat, args.lon
        else:
            site = get_site(args.site)
            key, name, lat, lon = site.key, site.name, site.lat, site.lon
        area = _site_area(site, args) if site is not None else None
        start = date.fromisoformat(args.start)
        try:
            if area is not None:
                print(f"Téléchargement NOAA OISST pour {name} : {area.describe()}…")
                sst = fetch_sst_area(area, start=start, cache_dir=Path(args.data_dir))
                zone = {"mode": "polygon", "wdpa_id": site.wdpa_id, "description": area.describe(),
                        "stride": area.stride, "cells": [list(c) for c in area.cells]}
            else:
                print(f"Téléchargement NOAA OISST pour {name} ({lat}, {lon})…")
                sst = fetch_sst(lat, lon, start=start, cache_dir=Path(args.data_dir))
                zone = {"mode": "point", "lat": lat, "lon": lon, "description": f"maille au point {lat}, {lon}"}
        except DownloadError as e:
            sys.exit(f"\nErreur : {e}")

    events, daily = detect.detect(sst, baseline=(args.baseline_start, args.baseline_end))
    summary = detect.yearly_summary(daily)

    out = Path(args.out) / key
    out.mkdir(parents=True, exist_ok=True)
    if zone is not None:
        (out / "zone.json").write_text(json.dumps(zone, ensure_ascii=False), encoding="utf-8")
    events.to_csv(out / "events.csv", index=False)
    summary.to_csv(out / "yearly_summary.csv")
    daily.round(3).to_csv(out / "daily.csv")
    plot.plot_recent(daily, f"{name} : SST des 12 derniers mois", out / "recent.png")
    plot.plot_yearly(summary, f"{name} : jours de vague de chaleur marine par an", out / "yearly.png")

    last = daily.iloc[-1]
    status = "EN COURS" if last["sst"] > last["thresh"] else "aucune"
    print(f"\n{name}")
    if zone is not None:
        print(f"  Zone : {zone['description']}")
    print(f"  Période analysée : {daily.index[0].date()} → {daily.index[-1].date()}")
    print(f"  Événements détectés : {len(events)}")
    print(f"  Dernier jour : SST {last['sst']:.2f} °C, anomalie {last['anom']:+.2f} °C, MHW {status}")
    if not events.empty:
        top = events.sort_values("intensity_cumulative", ascending=False).head(5)
        print("\n  Top 5 des événements (intensité cumulée) :")
        print(top.to_string(index=False))
    print(f"\n  Résultats écrits dans {out}/")


def _site_area(site: Site, args: argparse.Namespace):
    """Mailles du contour WDPA du site, ou None pour une analyse au point (--area point,
    site sans identifiant WDPA, ou contour indisponible : on se replie alors sur le point)."""
    if args.area != "polygon" or site.wdpa_id is None:
        return None
    import requests

    from .wdpa import area_for_site

    try:
        return area_for_site(site.wdpa_id, cache_dir=Path(args.data_dir))
    except (requests.RequestException, ValueError) as e:
        print(f"  Contour WDPA {site.wdpa_id} indisponible ({e}) : analyse au point représentatif.")
        return None


def write_region_summary(sites: dict[str, Site], out_dir: Path, region: str) -> Path:
    """Tableau récapitulatif d'une région : état de chaque AMP au dernier jour analysé."""
    from .dashboard import read_daily, read_events, status_from_daily

    rows = []
    for s in sites.values():
        st = status_from_daily(s, read_daily(out_dir, s.key))
        zone_file = out_dir / s.key / "zone.json"
        zone = json.loads(zone_file.read_text(encoding="utf-8")) if zone_file.is_file() else {}
        rows.append({
            "site": s.key, "name": s.name, "region": s.region, "wdpa_id": s.wdpa_id,
            "zone": zone.get("description", ""),
            "date": st.date.date() if st.date is not None else None,
            "sst": None if st.sst is None else round(st.sst, 2),
            "anom": None if st.anom is None else round(st.anom, 2),
            "status": st.label, "events": len(read_events(out_dir, s.key)),
        })
    table = pd.DataFrame(rows)
    path = out_dir / "regions" / f"{slugify(region) or 'all'}.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    table.to_csv(path, index=False)
    print(f"\nRécapitulatif de la région « {region} » ({path}) :")
    print(table[["name", "date", "sst", "anom", "status", "events"]].to_string(index=False))
    return path


def cmd_dashboard(args: argparse.Namespace) -> None:
    from .dashboard import launch

    sys.exit(launch(out_dir=args.out, data_dir=args.data_dir, port=args.port, open_browser=not args.no_browser))


def cmd_export_site(args: argparse.Namespace) -> None:
    from .static_site import build_site

    print(f"Site statique écrit : {build_site(args.out, args.dest)}")


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(prog="mhw-watch", description="Vagues de chaleur marines dans les AMP")
    sub = p.add_subparsers(dest="cmd", required=True)

    ls = sub.add_parser("sites", help="Lister les aires marines protégées connues, par région")
    ls.add_argument("--region", default="all", help="Clé d'une région (ex. mediterranee), ou all")
    ls.set_defaults(func=cmd_sites)

    a = sub.add_parser("analyze", help="Détecter les vagues de chaleur sur un site")
    a.add_argument("--site", default="port-cros",
                   help="Clé d'un site (voir `sites`), ou `all` (limité à MHW_WATCH_REGION si définie)")
    a.add_argument("--region", help="Analyser toutes les AMP d'une région (ex. mediterranee), ou all")
    a.add_argument("--area", choices=["polygon", "point"],
                   help="Zone analysée : moyenne sur le contour WDPA (défaut) ou point représentatif")
    a.add_argument("--lat", type=float, help="Latitude d'un point libre")
    a.add_argument("--lon", type=float, help="Longitude d'un point libre (-180..180)")
    a.add_argument("--name", default="Point personnalisé", help="Nom affiché avec --lat/--lon")
    a.add_argument("--start", default="1982-01-01", help="Début de la série (AAAA-MM-JJ)")
    a.add_argument("--baseline-start", type=int, default=1991)
    a.add_argument("--baseline-end", type=int, default=2020)
    a.add_argument("--demo", action="store_true", help="Utiliser des données synthétiques (hors ligne)")
    a.add_argument("--data-dir", default="data", help="Dossier de cache des données")
    a.add_argument("--out", default="outputs", help="Dossier des résultats")
    a.set_defaults(func=cmd_analyze)

    d = sub.add_parser("dashboard", help="Ouvrir le tableau de bord web (carte des AMP)")
    d.add_argument("--data-dir", default="data", help="Dossier de cache des données")
    d.add_argument("--out", default="outputs", help="Dossier des résultats")
    d.add_argument("--port", type=int, help="Port du serveur web (8501 par défaut)")
    d.add_argument("--no-browser", action="store_true", help="Ne pas ouvrir le navigateur automatiquement")
    d.set_defaults(func=cmd_dashboard)

    e = sub.add_parser("export-site", help="Exporter le tableau de bord en HTML statique (GitHub Pages)")
    e.add_argument("--out", default="outputs", help="Dossier des résultats de `analyze`")
    e.add_argument("--dest", default="site", help="Dossier où écrire le site")
    e.set_defaults(func=cmd_export_site)

    args = p.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")  # console Windows : noms avec accents rares (ā)
    config.load_dotenv()
    if getattr(args, "area", "") is None:
        args.area = config.get("AREA")
    args.func(args)


if __name__ == "__main__":
    main()
