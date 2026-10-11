# Comprendre MHW Watch (sans être océanographe)

## Le projet en 4 phrases

1. Des satellites mesurent chaque jour la **température de la surface de la mer** partout sur le globe, depuis 1981.
2. Pour un endroit donné (une aire marine protégée), le programme calcule ce qui est « normal » pour chaque jour de l'année, à partir de 30 ans de mesures.
3. Quand la mer reste **anormalement chaude au moins 5 jours d'affilée**, il déclare une **vague de chaleur marine** (une « canicule marine ») et lui donne une note de gravité, de I à IV.
4. Il produit des tableaux et des graphiques, un tableau de bord et des alertes, pour qu'un gestionnaire d'aire protégée voie d'un coup d'œil si son site souffre.

Pourquoi c'est important : quand l'eau reste trop chaude trop longtemps, des espèces fixées qui ne peuvent pas fuir meurent en masse (gorgones et herbiers de posidonie en Méditerranée en 2003 et 2022, coraux qui blanchissent, forêts de kelp qui disparaissent).

## Les notions clés, une par une

### SST (Sea Surface Temperature)
La température de la mer en surface, en °C. Le projet utilise **NOAA OISST v2.1** : une carte du monde par jour, découpée en cases de 0,25° (environ 25 km de côté). Les valeurs combinent satellites, bateaux et bouées. Conséquence pratique : une case de 25 km « lisse » ce qui se passe tout près de la côte, et si un point tombe sur une case de terre (c'est le cas de Port-Cros), le programme prend la case de mer la plus proche.

### Climatologie
Ce n'est pas la météo, c'est le **« normal » statistique**. Pour chaque jour de l'année (le 15 août, par exemple), on regarde toutes les températures mesurées autour de cette date (±5 jours) entre **1991 et 2020** (la période de référence officielle de l'Organisation météorologique mondiale). On en tire deux courbes :
- la **moyenne** (« seas » dans le code) : la température typique ce jour-là ;
- le **seuil** (« thresh ») : voir ci-dessous.

Les deux courbes sont ensuite lissées sur 31 jours pour éviter les à-coups.

### Le seuil du 90e percentile
Le 90e percentile, c'est la valeur que **seuls 10 % des jours dépassent**. Si le seuil du 15 août vaut 25,8 °C, cela veut dire que sur 30 ans, 9 fois sur 10 il faisait moins de 25,8 °C ce jour-là. Dépasser le seuil, c'est donc être dans les 10 % les plus chauds pour la saison. Un dépassement isolé ne suffit pas : il faut **au moins 5 jours consécutifs**, et deux épisodes séparés de 2 jours ou moins sont comptés comme un seul.

Point important : le seuil dépend de la saison. 24 °C peut être une canicule en juin et une journée normale en août.

### Les catégories I à IV (Hobday et al., 2018)
On mesure l'écart **D = seuil − moyenne** (la « marge » normale entre un jour ordinaire et un jour chaud). Au jour le plus chaud de l'épisode, on regarde de combien la température dépasse la moyenne, en multiples de D :

| Catégorie | Dépassement de la moyenne au pic | Nom |
|---|---|---|
| I | entre 1 et 2 fois D | Modérée |
| II | entre 2 et 3 fois D | Forte |
| III | entre 3 et 4 fois D | Sévère |
| IV | plus de 4 fois D | Extrême |

Exemple : moyenne 23 °C, seuil 24,5 °C, donc D = 1,5 °C. Si la mer monte à 26,8 °C (3,8 °C au-dessus de la moyenne, soit 2,5 × D), c'est une catégorie II, Forte. C'est l'idée des catégories d'ouragans, appliquée à la chaleur de la mer.

Les autres colonnes de `events.csv` : **durée** (jours), **intensité max** (écart maximal à la moyenne, en °C), **intensité moyenne**, et **intensité cumulée** (somme des écarts de chaque jour, en °C·jours : une vague longue et modérée peut faire autant de dégâts qu'une vague courte et violente).

### AMP et WDPA
Une **aire marine protégée (AMP)** est une zone de mer délimitée où les activités humaines sont encadrées pour protéger la nature (parc national de Port-Cros, réserve de Scandola, parc marin d'Iroise…). La **WDPA** (World Database on Protected Areas, consultable sur Protected Planet) est la base mondiale qui donne le **contour** (le polygone) de chaque aire protégée. Le projet s'en sert pour faire la moyenne de la température sur toute la surface de l'AMP au lieu d'un seul point.

### Le reste du projet (la partie informatique)
- **Workflow quotidien** : GitHub Actions relance l'analyse chaque jour, sans ton PC.
- **Dashboard** : la page GitHub Pages qui montre la carte et l'état de chaque AMP.
- **Alertes** : un message part quand une AMP passe en catégorie II ou plus.

## Que lire, du plus simple au plus technique

1. **Reporterre, « Les canicules marines, une hécatombe sous l'océan »** (français, grand public). Ce qu'est une canicule marine et pourquoi c'est grave.
   https://reporterre.net/Les-canicules-marines-une-hecatombe-sous-l-ocean
2. **Ministère de la Mer, « Le patrimoine marin et les aires marines protégées françaises »** (français). Ce qu'est une AMP et comment la France les organise.
   https://mer.gouv.fr/le-patrimoine-marin-et-les-aires-marines-protegees-francaises
3. **Marine Heatwaves International Working Group, « MHW Overview »** (anglais simple). Le site des chercheurs qui ont inventé la définition utilisée par le projet.
   https://www.marineheatwaves.org/mhw-overview.html
   Va voir aussi la carte mondiale en direct : https://www.marineheatwaves.org/tracker.html. C'est la même chose que MHW Watch, à l'échelle de la planète, et c'est le meilleur moyen de « voir » ton projet.
4. **Hobday et al. (2018), « Categorizing and Naming Marine Heatwaves »**, revue *Oceanography* (anglais, article scientifique gratuit et court, avec des figures très claires). **Si tu ne lis qu'un article scientifique, c'est celui-là** : il explique les catégories I à IV avec des exemples réels.
   https://tos.org/oceanography/article/categorizing-and-naming-marine-heatwaves
5. **NOAA, page du jeu de données OISST** (anglais). D'où viennent tes données et comment elles sont fabriquées.
   https://www.ncei.noaa.gov/products/optimum-interpolation-sst
6. **Protected Planet, la WDPA** (anglais). La base des contours d'aires protégées.
   https://www.protectedplanet.net/en/thematic-areas/wdpa
7. **Oliver et al. (2021), « Marine Heatwaves »**, *Annual Review of Marine Science* (anglais, synthèse complète : causes, impacts, tendances). Pour aller plus loin.
   https://figshare.utas.edu.au/articles/journal_contribution/Marine_heatwaves/22992626/1
8. **Hobday et al. (2016), « A hierarchical approach to defining marine heatwaves »**, *Progress in Oceanography* (anglais, technique). La définition d'origine (seuil, 5 jours, fusion des épisodes) ; c'est exactement ce que fait `detect.py`.
   https://doi.org/10.1016/j.pocean.2015.12.014
9. **Le code de référence** : le paquet Python d'Eric Oliver, que ton `detect.py` reproduit. Utile pour comparer tes résultats.
   https://github.com/ecjoliver/marineHeatWaves

## Une façon concrète d'apprendre avec ton propre projet

1. Lance `mhw-watch analyze --demo` puis ouvre `outputs/demo/recent.png` : la courbe bleue est la SST mesurée, la courbe grise continue la moyenne, la grise en pointillés le seuil, et les zones colorées (jaune → bordeaux selon la catégorie) sont les vagues de chaleur.
2. Ouvre `daily.csv` dans Excel, choisis un jour coloré et refais le calcul de catégorie à la main avec les colonnes sst, seas et thresh.
3. Avec les vraies données (`mhw-watch analyze --site port-cros`), ouvre `outputs/port-cros/events.csv`, trouve l'événement de l'été 2022 et compare avec ce que disent les articles de presse sur la Méditerranée cette année-là.
