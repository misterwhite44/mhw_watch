# Liens utiles pour MHW Watch

Tous les liens ont été ouverts et vérifiés le 11/10/2026, sauf ceux marqués *(non vérifié)*.
Pour les explications de base, voir aussi [../comprendre-mhw-watch.md](../comprendre-mhw-watch.md).

##  projet
- Dépôt GitHub : https://github.com/misterwhite44/mhw_watch
- Tableau de bord en ligne : https://misterwhite44.github.io/mhw_watch/

## Comprendre les vagues de chaleur marines
- Reporterre, « Les canicules marines, une hécatombe sous l'océan » (français, grand public) : https://reporterre.net/Les-canicules-marines-une-hecatombe-sous-l-ocean
- Le Grand Continent, la vague de chaleur marine précoce de juin 2022 en Méditerranée (français) : https://legrandcontinent.eu/fr/2022/06/29/la-mediterranee-a-connu-la-vague-de-chaleur-marine-extreme-la-plus-precoce-de-son-histoire-recente/
- Marine Heatwaves International Working Group, présentation (anglais simple) : https://www.marineheatwaves.org/mhw-overview.html
- Le même groupe, impacts sur les écosystèmes : https://www.marineheatwaves.org/mhw-impacts.html
- Le même groupe, liste de publications : https://www.marineheatwaves.org/publications.html

## Voir des vagues de chaleur en direct (projets proches du tien)
- Marine Heatwave Tracker, carte mondiale quotidienne : https://www.marineheatwaves.org/tracker.html
- NOAA PSL, prévisions de vagues de chaleur marines : https://psl.noaa.gov/marine-heatwaves/
- NOAA Coral Reef Watch, stress thermique des coraux (Degree Heating Weeks) : https://coralreefwatch.noaa.gov/

## Articles scientifiques de la méthode
- Hobday et al. 2018, les catégories I à IV (gratuit, court) : https://tos.org/oceanography/article/categorizing-and-naming-marine-heatwaves
- Hobday et al. 2016, la définition d'origine : https://doi.org/10.1016/j.pocean.2015.12.014 *(non vérifié)*
- Oliver et al. 2021, synthèse complète (PDF) : https://figshare.utas.edu.au/articles/journal_contribution/Marine_heatwaves/22992626/1 *(non vérifié)*

## Données utilisées par le projet
- NOAA OISST v2.1, la température de surface : https://www.ncei.noaa.gov/products/optimum-interpolation-sst
- ERDDAP CoastWatch, le serveur d'où le projet télécharge OISST : https://coastwatch.pfeg.noaa.gov/erddap/griddap/ncdcOisst21Agg_LonPM180.html
- Protected Planet / WDPA, les contours des aires protégées : https://www.protectedplanet.net/en/thematic-areas/wdpa
- Ministère de la Mer, les aires marines protégées françaises : https://mer.gouv.fr/le-patrimoine-marin-et-les-aires-marines-protegees-francaises

## Données pour aller plus loin (feuille de route)
- Copernicus Marine Service, SST haute résolution en Méditerranée : https://marine.copernicus.eu/
- T-MEDNet, températures et mortalités observées en Méditerranée : https://t-mednet.org/
- Global Fishing Watch, API d'effort de pêche : https://globalfishingwatch.org/our-apis/

## Code de référence et outils
- marineHeatWaves (Python, Eric Oliver), l'implémentation de référence de Hobday : https://github.com/ecjoliver/marineHeatWaves
- heatwaveR (R), même méthode, très bien documentée : https://robwschlegel.github.io/heatwaveR/
- xarray, pour manipuler des grilles de données (température × lat × lon × temps) : https://docs.xarray.dev/
- GeoPandas, pour les polygones des AMP : https://geopandas.org/
- Streamlit, pour un tableau de bord en Python : https://docs.streamlit.io/
- Leaflet, pour les cartes web : https://leafletjs.com/
- GitHub Actions, pour l'automatisation quotidienne : https://docs.github.com/en/actions

## Le secteur (pour ton portfolio)
- Mercator Ocean International, prévision océanique européenne : https://www.mercator-ocean.eu/
- Copernicus Marine Service (voir plus haut), principal utilisateur de ce type de données en Europe
