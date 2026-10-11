from datetime import date
from urllib.parse import unquote

import pandas as pd
import pytest

from mhw_watch import cli, data, wdpa
from mhw_watch.sites import SITES, sites_in_region, slugify


def square(lon0, lat0, lon1, lat1):
    return [[lon0, lat0], [lon1, lat0], [lon1, lat1], [lon0, lat1], [lon0, lat0]]


def fc(*polys):
    return {"type": "FeatureCollection", "features": [
        {"type": "Feature", "geometry": {"type": "MultiPolygon", "coordinates": [list(p) for p in polys]}}
    ]}


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    monkeypatch.setattr(data.time, "sleep", lambda s: None)
    for name in data.config.DEFAULTS:
        monkeypatch.delenv(data.config.PREFIX + name, raising=False)


def test_contains_handles_holes():
    polys = wdpa.polygons(fc([square(0, 0, 4, 4), square(1, 1, 2, 2)]))
    inside = wdpa.contains(polys, [0.5, 1.5, 3.5, 5.0], [0.5, 1.5, 3.5, 0.5])
    assert inside.tolist() == [True, False, True, False]


def test_select_cells_keeps_centres_inside():
    # 1° x 0,5° : 4 x 2 = 8 centres de maille dedans.
    area = wdpa.select_cells(wdpa.polygons(fc([square(10.0, 40.0, 11.0, 40.5)])))
    assert area.inside and area.stride == 1 and len(area.cells) == 8
    lats = {round(float(wdpa.lat_of(i)), 3) for i, _ in area.cells}
    assert lats == {40.125, 40.375}


def test_select_cells_subsamples_large_areas():
    area = wdpa.select_cells(wdpa.polygons(fc([square(140, -20, 150, -10)])), max_cells=40)
    assert area.stride > 1 and 0 < len(area.cells) <= 40


def test_small_mpa_uses_neighbouring_cells():
    # Plus petite qu'une maille : 3 x 3 mailles autour.
    area = wdpa.select_cells(wdpa.polygons(fc([square(8.53, 42.34, 8.60, 42.40)])))
    assert not area.inside and len(area.cells) == 9


def test_antimeridian_is_unwrapped():
    polys = wdpa.polygons(fc([square(179.0, 20.0, 180.0, 21.0)], [square(-180.0, 20.0, -179.0, 21.0)]))
    lon0, _, lon1, _ = wdpa.bounds(polys)
    assert (lon0, lon1) == (179.0, 181.0)
    area = wdpa.select_cells(polys)
    js = sorted({j for _, j in area.cells})
    assert js[0] == 716 and js[-1] == 723  # 179.125° E … 180.875° E (= -179.125°)
    # ERDDAP (-180..180) : deux plages, de part et d'autre de l'antiméridien.
    assert wdpa.lon_runs(js, 1, offset=720) == [(0, 3), (1436, 1439)]
    assert wdpa.lon_runs(js, 1) == [(716, 723)]  # PSL (0..360) : une seule plage


def test_fetch_geometry_uses_cache(tmp_path, monkeypatch):
    (tmp_path / "wdpa").mkdir()
    (tmp_path / "wdpa" / "42.geojson").write_text(
        '{"type": "FeatureCollection", "features": [{"type": "Feature", "geometry": '
        '{"type": "Polygon", "coordinates": [[[0,0],[1,0],[1,1],[0,0]]]}}]}')
    monkeypatch.setattr(data.requests, "get", lambda *a, **k: pytest.fail("pas de réseau attendu"))
    assert wdpa.polygons(wdpa.fetch_geometry(42, tmp_path))


class FakeResponse:
    def __init__(self, text):
        self.text, self.status_code, self.headers = text, 200, {}

    def raise_for_status(self):
        pass


ERDDAP_BOX = (
    "time,zlev,latitude,longitude,sst\nUTC,m,degrees_north,degrees_east,degree_C\n"
    "2024-01-01T12:00:00Z,0.0,40.125,10.125,14.0\n"
    "2024-01-01T12:00:00Z,0.0,40.125,10.375,16.0\n"
    "2024-01-01T12:00:00Z,0.0,40.375,10.125,NaN\n"  # maille terre : ignorée
    "2024-01-01T12:00:00Z,0.0,40.375,10.375,99.0\n"  # hors sélection : ignorée
    "2024-01-02T12:00:00Z,0.0,40.125,10.125,15.0\n"
    "2024-01-02T12:00:00Z,0.0,40.125,10.375,15.0\n"
    "2024-01-02T12:00:00Z,0.0,40.375,10.125,NaN\n"
    "2024-01-02T12:00:00Z,0.0,40.375,10.375,99.0\n"
)


def test_fetch_sst_area_erddap_mean(monkeypatch):
    i, j = wdpa.cell_index(40.125, 10.125)
    area = wdpa.Area(cells=((int(i), int(j)), (int(i), int(j) + 1), (int(i) + 1, int(j))))
    urls = []
    monkeypatch.setattr(data.requests, "get", lambda url, timeout: urls.append(url) or FakeResponse(ERDDAP_BOX))
    s = data.fetch_sst_area(area, start=date(2024, 1, 1), end=date(2024, 1, 2), cache_dir=None)
    assert s.round(2).tolist() == [15.0, 15.0]
    assert "(40.125):1:(40.375)" in unquote(urls[0])


PSL_GRID = """Dataset {
} Datasets/noaa.oisst.v2.highres/sst.day.mean.2024.nc;
---------------------------------------------
sst.sst[2][2][2]
[0][0], 14.0, 16.0
[0][1], -9.96921E36, 99.0
[1][0], 15.0, 15.0
[1][1], -9.96921E36, 99.0

sst.time[2]
81814.0, 81815.0

sst.lat[2]
40.125, 40.375

sst.lon[2]
10.125, 10.375
"""


def test_psl_area_year_mean(monkeypatch):
    i, j = wdpa.cell_index(40.125, 10.125)
    area = wdpa.Area(cells=((int(i), int(j)), (int(i), int(j) + 1), (int(i) + 1, int(j))))
    urls = []
    monkeypatch.setattr(data.requests, "get", lambda url, timeout: urls.append(url) or FakeResponse(PSL_GRID))
    monkeypatch.setattr(data, "_psl_ndays", lambda year: 2)
    df = data._psl_area_year(2024, area, None)
    assert df["sst"].round(2).tolist() == [15.0, 15.0]
    assert f"%5B{i}:1:{i + 1}%5D%5B{j}:1:{j + 1}%5D" in urls[0]


def test_regions():
    assert slugify("Atlantique Nord-Est") == "atlantique-nord-est"
    med = sites_in_region("Méditerranée")
    assert "port-cros" in med and "iroise" not in med
    assert sites_in_region("all") == SITES
    with pytest.raises(SystemExit):
        sites_in_region("arctique")
    assert all(s.wdpa_id for s in SITES.values())


def test_region_summary(tmp_path):
    daily = pd.DataFrame(
        {"sst": [20.0], "seas": [19.0], "thresh": [20.5], "anom": [1.0], "in_mhw": [False], "category": [0]},
        index=pd.to_datetime(["2024-06-01"]),
    )
    (tmp_path / "port-cros").mkdir()
    daily.to_csv(tmp_path / "port-cros" / "daily.csv")
    path = cli.write_region_summary(sites_in_region("mediterranee"), tmp_path, "Méditerranée")
    table = pd.read_csv(path)
    assert path.name == "mediterranee.csv"
    row = table.set_index("site").loc["port-cros"]
    assert row["status"] == "Pas de vague de chaleur" and row["anom"] == 1.0
    assert table.set_index("site").loc["scandola", "status"] == "Pas de données"
