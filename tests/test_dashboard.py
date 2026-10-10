import pandas as pd

from mhw_watch import dashboard, detect
from mhw_watch.sites import SITES, Site
from mhw_watch.synthetic import synthetic_sst

SITE = Site("test", "Site test", 43.0, 6.4, "Méditerranée")


def write_outputs(out, key, sst):
    events, daily = detect.detect(sst)
    d = out / key
    d.mkdir(parents=True)
    events.to_csv(d / "events.csv", index=False)
    detect.yearly_summary(daily).to_csv(d / "yearly_summary.csv")
    daily.round(3).to_csv(d / "daily.csv")
    return daily


def test_site_never_analysed_has_no_data(tmp_path):
    status = dashboard.status_from_daily(SITE, dashboard.read_daily(tmp_path, "test"))
    assert not status.has_data
    assert status.label == "Pas de données"
    assert status.color == dashboard.NO_DATA_COLOR
    assert dashboard.read_events(tmp_path, "test").empty


def test_ongoing_heatwave_on_last_day(tmp_path):
    # Vague de chaleur forte (+4 °C) sur les 20 derniers jours de la série synthétique.
    sst = synthetic_sst(heatwave=None)
    sst.iloc[-20:] += 4.0
    last = sst.index[-1]
    write_outputs(tmp_path, "test", sst)
    status = dashboard.status_from_daily(SITE, dashboard.read_daily(tmp_path, "test"))
    assert status.has_data
    assert status.category >= 2
    assert status.date == last
    assert "catégorie" in status.label
    assert status.color != dashboard.NO_MHW_COLOR


def test_no_heatwave_when_last_day_is_not_in_event():
    idx = pd.date_range("2024-01-01", periods=3)
    daily = pd.DataFrame(
        {"sst": [20, 21, 22], "anom": [0, 1, 2], "category": [0, 1, 2], "in_mhw": [False, False, False]},
        index=idx,
    )
    status = dashboard.status_from_daily(SITE, daily)
    assert status.category == 0
    assert status.label == "Pas de vague de chaleur"
    assert status.sst == 22


def test_all_statuses_covers_every_site(tmp_path):
    statuses = dashboard.all_statuses(tmp_path)
    assert [s.site.key for s in statuses] == list(SITES)
    assert not any(s.has_data for s in statuses)


def test_site_at_finds_clicked_marker():
    s = next(iter(SITES.values()))
    assert dashboard.site_at(s.lat, s.lon) == s
    assert dashboard.site_at(0.123, 0.456) is None


def test_history_window():
    daily = pd.DataFrame({"sst": range(3000)}, index=pd.date_range("2018-01-01", periods=3000))
    assert len(dashboard.history_window(daily, "Tout")) == 3000
    assert len(dashboard.history_window(daily, "12 mois")) == 365
    assert (dashboard.history_window(daily, "2020").index.year == 2020).all()
    five = dashboard.history_window(daily, "5 ans")
    assert 1820 <= len(five) <= 1830
