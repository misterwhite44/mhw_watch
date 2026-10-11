"""Interface en ligne de commande.

Exemples :
    python -m mhw_watch sites
    python -m mhw_watch analyze --site port-cros
    python -m mhw_watch analyze --lat 43.2 --lon 5.3 --name "Calanques"
    python -m mhw_watch analyze --demo          # sans réseau, données synthétiques
    python -m mhw_watch dashboard               # tableau de bord web (navigateur)
    python -m mhw_watch analyze --site all      # tous les sites connus
    python -m mhw_watch export-site --dest site # tableau de bord en HTML statique (GitHub Pages)
    python -m mhw_watch alert --dry-run         # alertes catégorie II+ (sans rien envoyer)
"""

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

from . import config, detect, plot
from .sites import SITES, get_site


def cmd_sites(_: argparse.Namespace) -> None:
    for s in SITES.values():
        print(f"{s.key:20} {s.name:38} {s.lat:7.2f} {s.lon:8.2f}  {s.region}")


def cmd_analyze(args: argparse.Namespace) -> None:
    if args.site == "all" and not args.demo and args.lat is None:
        # Un site en échec n'empêche pas les autres ; code de sortie 1 seulement si tous échouent.
        failed = []
        for key in SITES:
            try:
                cmd_analyze(argparse.Namespace(**{**vars(args), "site": key}))
            except SystemExit as e:
                print(e, file=sys.stderr)
                failed.append(key)
        if failed:
            print(f"\nÉchec pour : {', '.join(failed)}", file=sys.stderr)
            if len(failed) == len(SITES):
                sys.exit(1)
        return
    if args.demo:
        from .synthetic import synthetic_sst

        key, name, sst = "demo", "Site de démonstration (données synthétiques)", synthetic_sst()
    else:
        from .data import DownloadError, fetch_sst

        if args.lat is not None and args.lon is not None:
            key, name, lat, lon = args.name.lower().replace(" ", "-"), args.name, args.lat, args.lon
        else:
            site = get_site(args.site)
            key, name, lat, lon = site.key, site.name, site.lat, site.lon
        print(f"Téléchargement NOAA OISST pour {name} ({lat}, {lon})…")
        try:
            sst = fetch_sst(lat, lon, start=date.fromisoformat(args.start), cache_dir=Path(args.data_dir))
        except DownloadError as e:
            sys.exit(f"\nErreur : {e}")

    events, daily = detect.detect(sst, baseline=(args.baseline_start, args.baseline_end))
    summary = detect.yearly_summary(daily)

    out = Path(args.out) / key
    out.mkdir(parents=True, exist_ok=True)
    events.to_csv(out / "events.csv", index=False)
    summary.to_csv(out / "yearly_summary.csv")
    daily.round(3).to_csv(out / "daily.csv")
    plot.plot_recent(daily, f"{name} : SST des 12 derniers mois", out / "recent.png")
    plot.plot_yearly(summary, f"{name} : jours de vague de chaleur marine par an", out / "yearly.png")

    last = daily.iloc[-1]
    status = "EN COURS" if last["sst"] > last["thresh"] else "aucune"
    print(f"\n{name}")
    print(f"  Période analysée : {daily.index[0].date()} → {daily.index[-1].date()}")
    print(f"  Événements détectés : {len(events)}")
    print(f"  Dernier jour : SST {last['sst']:.2f} °C, anomalie {last['anom']:+.2f} °C, MHW {status}")
    if not events.empty:
        top = events.sort_values("intensity_cumulative", ascending=False).head(5)
        print("\n  Top 5 des événements (intensité cumulée) :")
        print(top.to_string(index=False))
    print(f"\n  Résultats écrits dans {out}/")


def cmd_dashboard(args: argparse.Namespace) -> None:
    from .dashboard import launch

    sys.exit(launch(out_dir=args.out, data_dir=args.data_dir, port=args.port, open_browser=not args.no_browser))


def cmd_export_site(args: argparse.Namespace) -> None:
    from .static_site import build_site

    print(f"Site statique écrit : {build_site(args.out, args.dest)}")


def cmd_alert(args: argparse.Namespace) -> None:
    from .alerts import run

    sys.exit(run(Path(args.out), Path(args.state), dry_run=args.dry_run))


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(prog="mhw-watch", description="Vagues de chaleur marines dans les AMP")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("sites", help="Lister les aires marines protégées connues").set_defaults(func=cmd_sites)

    a = sub.add_parser("analyze", help="Détecter les vagues de chaleur sur un site")
    a.add_argument("--site", default="port-cros", help="Clé d'un site (voir `sites`), ou `all`")
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

    al = sub.add_parser("alert", help="Alerter (e-mail, Bluesky, Mastodon) si une AMP entre en catégorie II+")
    al.add_argument("--out", default="outputs", help="Dossier des résultats de `analyze`")
    al.add_argument("--state", default="alerts/state.json", help="Fichier où mémoriser les alertes déjà envoyées")
    al.add_argument("--dry-run", action="store_true", help="Afficher les alertes sans rien envoyer ni mémoriser")
    al.set_defaults(func=cmd_alert)

    args = p.parse_args(argv)
    config.load_dotenv()
    args.func(args)


if __name__ == "__main__":
    main()
