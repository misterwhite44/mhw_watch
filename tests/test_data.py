from datetime import date

import pytest
import requests

from mhw_watch import data

ERDDAP_CSV = "time,zlev,latitude,longitude,sst\nUTC,m,degrees_north,degrees_east,degree_C\n" \
             "2024-01-01T12:00:00Z,0.0,43.0,6.4,14.1\n2024-01-02T12:00:00Z,0.0,43.0,6.4,14.0\n"

# Forme de la réponse OPeNDAP .ascii du serveur PSL (valeurs réelles, Port-Cros, janvier 2024).
PSL_ASCII = """Dataset {
    Grid {
     ARRAY:
        Float32 sst[time = 3][lat = 1][lon = 1];
     MAPS:
        Float64 time[time = 3];
        Float32 lat[lat = 1];
        Float32 lon[lon = 1];
    } sst;
} Datasets/noaa.oisst.v2.highres/sst.day.mean.2024.nc;
---------------------------------------------
sst.sst[3][1][1]
[0][0], 13.66
[1][0], 13.679999
[2][0], -9.96921E36

sst.time[3]
81814.0, 81815.0, 81816.0

sst.lat[1]
42.875

sst.lon[1]
6.375
"""


class FakeResponse:
    status_code = 200

    def __init__(self, text):
        self.text = text

    def raise_for_status(self):
        pass


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    monkeypatch.setattr(data.time, "sleep", lambda s: None)
    for name in data.config.DEFAULTS:
        monkeypatch.delenv(data.config.PREFIX + name, raising=False)


def test_psl_indices_nearest_cell():
    assert data._psl_indices(42.875, 6.375) == (531, 25)
    assert data._psl_indices(43.0, 6.4) == (532, 25)
    assert data._psl_indices(-20.0, -150.0)[1] == 840  # maille centrée sur 210.125° E


def test_parse_psl_ascii():
    df = data._parse_psl_ascii(PSL_ASCII)
    assert list(df["time"].dt.strftime("%Y-%m-%d")) == ["2024-01-01", "2024-01-02", "2024-01-03"]
    assert df["sst"].iloc[0] == pytest.approx(13.66)
    assert df["sst"].isna().iloc[2]  # valeur manquante


def test_falls_back_to_next_erddap_mirror(monkeypatch):
    calls = []

    def fake_get(url, timeout):
        calls.append(url)
        if "coastwatch.pfeg" in url:
            raise requests.ConnectTimeout("timeout")
        return FakeResponse(ERDDAP_CSV)

    monkeypatch.setattr(data.requests, "get", fake_get)
    s = data.fetch_sst(43.0, 6.4, start=date(2024, 1, 1), end=date(2024, 1, 2), cache_dir=None)
    assert list(s.round(1)) == [14.1, 14.0]
    assert "upwell.pfeg" in calls[-1]


def test_falls_back_to_psl_when_erddap_down(monkeypatch, tmp_path):
    calls = []

    def fake_get(url, timeout):
        calls.append(url)
        if "erddap" in url:
            raise requests.ConnectTimeout("timeout")
        return FakeResponse(PSL_ASCII)

    monkeypatch.setattr(data.requests, "get", fake_get)
    monkeypatch.setattr(data, "_psl_ndays", lambda year: 3)
    s = data.fetch_sst(43.0, 6.4, start=date(2024, 1, 1), end=date(2024, 1, 2), cache_dir=tmp_path)
    assert s.round(2).tolist() == [13.66, 13.68]
    assert "sst.day.mean.2024.nc.ascii?sst%5B0:1:2%5D%5B532%5D%5B25%5D" in calls[-1]
    assert (tmp_path / "psl" / "psl_532_25_2024.csv").exists()


def test_all_sources_down_raises_clear_error(monkeypatch):
    def fake_get(url, timeout):
        raise requests.ConnectTimeout("timeout")

    monkeypatch.setattr(data.requests, "get", fake_get)
    with pytest.raises(data.DownloadError, match="--demo"):
        data.fetch_sst(43.0, 6.4, start=date(2024, 1, 1), end=date(2024, 1, 2), cache_dir=None)


def test_settings_from_dotenv(monkeypatch, tmp_path):
    env = tmp_path / ".env"
    env.write_text(
        "# commentaire\n"
        "MHW_WATCH_ERDDAP_SERVERS=https://example.org/erddap/, https://autre.org/erddap\n"
        'MHW_WATCH_PSL_WORKERS="2"\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("MHW_WATCH_RETRIES", "3")  # le terminal l'emporte sur .env
    env.write_text(env.read_text(encoding="utf-8") + "MHW_WATCH_RETRIES=0\n", encoding="utf-8")
    data.config.load_dotenv(env)
    assert data.config.get_list("ERDDAP_SERVERS") == ["https://example.org/erddap", "https://autre.org/erddap"]
    assert data.config.get_int("PSL_WORKERS") == 2
    assert data.config.get_int("RETRIES") == 3
    assert data.config.get("ERDDAP_DATASET") == "ncdcOisst21Agg_LonPM180"  # valeur par défaut


def test_sources_order_from_settings(monkeypatch):
    calls = []

    def fake_get(url, timeout):
        calls.append(url)
        return FakeResponse(PSL_ASCII)

    monkeypatch.setenv("MHW_WATCH_SOURCES", "psl")
    monkeypatch.setattr(data.requests, "get", fake_get)
    monkeypatch.setattr(data, "_psl_ndays", lambda year: 3)
    data.fetch_sst(43.0, 6.4, start=date(2024, 1, 1), end=date(2024, 1, 2), cache_dir=None)
    assert all("psl.noaa.gov" in u for u in calls)
