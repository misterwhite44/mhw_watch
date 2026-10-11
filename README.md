# MHW Watch 🌊🔥

**Détection et suivi des vagues de chaleur marines dans les aires marines protégées (AMP), à partir de données satellites ouvertes.**

Les vagues de chaleur marines (*Marine Heatwaves*, MHW) sont l'une des menaces les plus directes pour les écosystèmes côtiers : mortalités massives de gorgonies et de posidonies en Méditerranée (2003, 2022), blanchissement de la Grande Barrière de corail, effondrement de forêts de kelp. Les gestionnaires d'AMP ont besoin de savoir *quand* et *à quel point* leur site est touché.

MHW Watch télécharge 40+ ans de température de surface de la mer (SST) mesurée par satellite, calcule la climatologie de chaque site, détecte les vagues de chaleur selon la **méthode scientifique de référence (Hobday et al., 2016 et 2018)** et produit des tableaux et des graphiques prêts à être partagés.

![SST récente et vagues de chaleur (données de démo)](docs/recent.png)

## Pourquoi ce projet

- **Données réelles et reconnues** : NOAA OISST v2.1, utilisée par Copernicus, Mercator Ocean, l'Ifremer et la communauté scientifique.
- **Méthode publiée** : la détection suit exactement la définition de Hobday, ce qui rend les résultats comparables à la littérature.
- **Compétences recherchées** dans le secteur (Mercator Ocean, CLS, Ifremer, Global Fishing Watch, OFB, start-ups « ocean tech ») : ingestion de données géospatiales, séries temporelles, Python scientifique, tests, visualisation.
- **Utilité concrète** : un indicateur que des gestionnaires d'AMP peuvent lire directement.
- **Évolutif** : le socle peut devenir un tableau de bord web, un système d'alertes, ou être croisé avec d'autres jeux de données (pêche, biodiversité).

## Installation

```bash
python -m venv .venv
source .venv/bin/activate          # Windows : .venv\Scripts\activate
pip install -e ".[dev]"
```

## Utilisation

```bash
# Lister les AMP préconfigurées, par région
mhw-watch sites

# Analyser une AMP (télécharge les données NOAA, mises en cache dans data/)
mhw-watch analyze --site port-cros

# Analyser toutes les AMP d'une région, avec un tableau récapitulatif
mhw-watch analyze --region mediterranee

# Analyser au point représentatif plutôt que sur le contour de l'AMP
mhw-watch analyze --site iroise --area point

# Analyser n'importe quel point du globe
mhw-watch analyze --lat 43.2 --lon 5.35 --name "Calanques"

# Essayer sans réseau, sur des données synthétiques
mhw-watch analyze --demo
```

Sans installation : `PYTHONPATH=src python -m mhw_watch analyze --demo`.

Le premier téléchargement d'un site (1982 → aujourd'hui) prend une à quelques minutes ; les suivants sont instantanés grâce au cache.

### Tableau de bord web

```bash
mhw-watch dashboard
```

La commande ouvre le navigateur sur http://localhost:8501 (Ctrl+C dans le terminal pour arrêter). On y trouve :

- une **carte des AMP** colorée selon leur état au dernier jour analysé : gris = pas de données, bleu = pas de vague de chaleur, jaune → bordeaux = vague de chaleur de catégorie I à IV ;
- en cliquant sur un site (ou en le choisissant dans la liste) : la **SST face à la climatologie et au seuil** (12 mois, 5 ans, tout, ou une année au choix), les **jours de vague de chaleur par an** et le **tableau des événements**.

Le tableau de bord relit les résultats déjà calculés dans `outputs/` : il ne télécharge rien au démarrage. Un site jamais analysé apparaît en « Pas de données », avec un bouton **Lancer l'analyse** (ou `mhw-watch analyze --site <clé>` dans un terminal). Le bouton **Mettre à jour les données de ce site** relance l'analyse pour récupérer les derniers jours.

Options : `--port 8502` pour changer de port, `--no-browser` pour ne pas ouvrir le navigateur. Sans la commande : `streamlit run src/mhw_watch/dashboard_app.py`.

### Version publiée en ligne (GitHub Pages)

Le workflow [`.github/workflows/pages.yml`](.github/workflows/pages.yml) tourne chaque jour à 06:30 UTC : il analyse toutes les AMP (`mhw-watch analyze --site all`), puis publie une **version HTML statique** du tableau de bord sur GitHub Pages (`mhw-watch export-site --dest site`). GitHub Pages ne sert que des fichiers, donc pas de Streamlit en ligne : la page contient la carte (folium), l'état de chaque site, les graphiques PNG, les événements les plus intenses et les CSV à télécharger.

Pour l'activer (une seule fois) : **Settings > Pages > Source : GitHub Actions**, puis onglet **Actions > Mise à jour quotidienne > Run workflow** pour une première publication sans attendre le lendemain. Le site est alors sur https://misterwhite44.github.io/mhw_watch/. Note : GitHub suspend les tâches planifiées d'un dépôt public sans activité pendant 60 jours (un clic sur « Enable workflow » les relance).

### Analyse sur le contour des AMP (WDPA)

Par défaut, une AMP n'est plus réduite à un point : MHW Watch récupère son **contour officiel** dans la *World Database on Protected Areas* (WDPA, UNEP-WCMC / IUCN, [protectedplanet.net](https://www.protectedplanet.net)) et calcule chaque jour la **moyenne de la SST sur les mailles océan dont le centre tombe dans le contour** (pondérée par le cosinus de la latitude ; les mailles « terre » sont écartées).

- **Accès aux contours** : service cartographique public d'UNEP-WCMC (ArcGIS REST, GeoJSON), **sans clé d'API ni secret GitHub**. Chaque contour est gardé dans `data/wdpa/<site_id>.geojson` (et dans le cache du workflow quotidien). L'API Protected Planet v3 demande, elle, un jeton délivré sur demande : elle n'est donc pas utilisée.
- **Contour personnalisé** : déposer un GeoJSON (export protectedplanet.net ou tracé à la main) sous `data/wdpa/<site_id>.geojson` ; il est utilisé tel quel, sans réseau.
- **Petites AMP** (moins de 4 centres de maille dans le contour, ex. Port-Cros, Scandola, Cerbère-Banyuls) : on prend les mailles qui touchent leur rectangle englobant, élargi d'une maille si besoin, car une ou deux mailles côtières peuvent être entièrement « terre ».
- **Grandes AMP** (Grande Barrière, Galápagos, Papahānaumokuākea) : au-delà de `MHW_WATCH_MAX_CELLS` mailles (40 par défaut), sous-échantillonnage régulier (une maille sur *n* dans chaque direction) pour garder des téléchargements raisonnables. Les contours qui traversent l'antiméridien sont gérés.
- **Repli** : si le service WDPA ne répond pas et qu'aucun contour n'est en cache, l'analyse se fait au point représentatif du site, avec un message.
- Données WDPA : usage non commercial, à citer « UNEP-WCMC and IUCN, Protected Planet » ([conditions](https://www.protectedplanet.net/en/legal)).

**Régions** : chaque AMP appartient à une région (`mhw-watch sites` les liste). `--region <clé>` analyse toutes les AMP d'une région et écrit un récapitulatif dans `outputs/regions/<région>.csv` (état au dernier jour, SST, anomalie, nombre d'événements). `MHW_WATCH_REGION` dans `.env` limite `--site all` (et donc le workflow quotidien) à une région.

### Résultats (dans `outputs/<site>/`)

| Fichier | Contenu |
|---|---|
| `events.csv` | Un événement par ligne : début, fin, pic, durée, intensités max/moyenne/cumulée, catégorie |
| `yearly_summary.csv` | Jours de MHW et intensité cumulée par année (tendance) |
| `daily.csv` | Série quotidienne : SST, moyenne climatologique, seuil, anomalie, catégorie |
| `recent.png` | Les 12 derniers mois, vagues de chaleur colorées par catégorie |
| `yearly.png` | Nombre de jours de vague de chaleur par an |
| `zone.json` | Zone analysée : contour WDPA (mailles moyennées) ou point |

Une analyse par région ajoute `outputs/regions/<région>.csv`, une ligne par AMP.

![Jours de MHW par an (données de démo)](docs/yearly.png)

## Méthode

1. **Climatologie** (période de référence 1991-2020 par défaut, conforme à l'OMM) : pour chaque jour de l'année, moyenne et 90ᵉ percentile des SST dans une fenêtre de ±5 jours, puis lissage sur 31 jours.
2. **Détection** : une MHW est une période d'au moins **5 jours** où la SST dépasse le seuil du 90ᵉ percentile ; deux événements séparés de **2 jours ou moins** sont fusionnés.
3. **Catégories** (Hobday et al., 2018) selon le multiple de l'écart (seuil − moyenne) atteint au pic : I Modérée, II Forte, III Sévère, IV Extrême.

Références :
- Hobday A.J. et al. (2016). *A hierarchical approach to defining marine heatwaves.* Progress in Oceanography, 141, 227-238.
- Hobday A.J. et al. (2018). *Categorizing and naming marine heatwaves.* Oceanography, 31(2), 162-173.
- Huang B. et al. (2021). *Improvements of the Daily Optimum Interpolation Sea Surface Temperature (DOISST) Version 2.1.* Journal of Climate, 34, 2923-2939.

## Données

- **NOAA OISST v2.1** : SST quotidienne, grille 0,25°, depuis septembre 1981, combinant satellites (AVHRR), navires et bouées.
- Accès sans clé d'API, par deux chemins essayés dans l'ordre :
  1. les serveurs **ERDDAP** de NOAA CoastWatch (`ncdcOisst21Agg_LonPM180` sur `coastwatch.pfeg.noaa.gov` puis `upwell.pfeg.noaa.gov`), rapides ;
  2. en secours, le serveur THREDDS/OPeNDAP de **NOAA PSL** (`noaa.oisst.v2.highres`). Il est lent (~0,3 s par jour demandé, soit de l'ordre de 20 minutes pour 1982 → aujourd'hui) ; chaque année téléchargée est gardée dans `data/psl/`, donc une interruption reprend là où elle s'est arrêtée.
- **Réglages dans `.env`** : serveurs ERDDAP, ordre des sources (`erddap,psl`), adresse PSL, taille des requêtes, parallélisme, délais et nouvelles tentatives. Copie `.env.example` en `.env` (PowerShell : `Copy-Item .env.example .env`) et modifie ce dont tu as besoin ; un réglage absent garde sa valeur par défaut, et une variable définie dans le terminal l'emporte sur le `.env`. Le `.env` n'est pas versionné.
- Si aucun serveur ne répond (réseau filtré, panne NOAA), la commande s'arrête avec un message explicatif ; `--demo` fonctionne toujours hors ligne.
- Limite connue : une résolution de 0,25° (~25 km) lisse les phénomènes très côtiers ; pour les petites AMP, la moyenne porte sur les mailles voisines. Voir la feuille de route pour passer à des produits plus fins.

## Structure

```
mhw-watch/
├── src/mhw_watch/
│   ├── cli.py         # ligne de commande (sites, analyze, dashboard, export-site)
│   ├── dashboard.py   # logique du tableau de bord (état des sites, lecture des résultats)
│   ├── dashboard_app.py  # interface web Streamlit (carte + historique)
│   ├── static_site.py # export HTML statique du tableau de bord (GitHub Pages)
│   ├── config.py      # réglages des sources (variables MHW_WATCH_*, fichier .env)
│   ├── data.py        # téléchargement NOAA OISST (ERDDAP, PSL en secours) + cache
│   ├── detect.py      # climatologie, détection et catégories (Hobday)
│   ├── plot.py        # graphiques
│   ├── sites.py       # AMP préconfigurées (identifiant WDPA, région)
│   ├── wdpa.py        # contours WDPA et choix des mailles à moyenner
│   └── synthetic.py   # données de démo hors ligne
├── tests/             # pytest
├── data/              # cache des téléchargements (ignoré par git)
└── docs/              # images du README
```

Tests : `pytest`

## Feuille de route

Idées pour faire grandir le projet, dans un ordre raisonnable :

1. **Carte multi-AMP** : analyser toutes les AMP d'une région (contours depuis la base mondiale [WDPA / Protected Planet](https://www.protectedplanet.net/)) et moyenner la SST sur le polygone plutôt qu'en un point.
3. ~~**Mise à jour automatique**~~ : fait (workflow quotidien + GitHub Pages, voir plus haut).
4. **Alertes** : notification (e-mail, Mastodon/Bluesky) quand une AMP entre en catégorie II ou plus.
5. **Données plus fines** : Copernicus Marine (SST Méditerranée haute résolution, produits `SST_MED_*`) via le paquet `copernicusmarine`.
6. **Impacts biologiques** : *Degree Heating Weeks* pour les coraux (NOAA Coral Reef Watch), croisement avec les observations de mortalité (base T-MEDNet en Méditerranée).
7. **Pression de pêche** : croiser avec l'effort de pêche de [Global Fishing Watch](https://globalfishingwatch.org/our-apis/) (API gratuite avec inscription) pour étudier stress thermique et pression humaine ensemble.

## Licence

MIT. Données NOAA OISST : domaine public.
