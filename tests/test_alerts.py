import pandas as pd

from mhw_watch import alerts, dashboard
from mhw_watch.sites import Site

SITE = Site("test", "Site test", 43.0, 6.4, "Méditerranée")
DAY = pd.Timestamp("2026-08-10")


def status(category, has_data=True):
    return dashboard.SiteStatus(SITE, has_data=has_data, category=category, date=DAY, sst=27.3, anom=3.1)


def run_days(categories, state=None):
    """Enchaîne les passages quotidiens ; renvoie le nombre d'alertes par jour et l'état final."""
    state, sent = state or {}, []
    for c in categories:
        found, state = alerts.evaluate([status(c)], state)
        sent.append([a.status.category for a in found])
    return sent, state


def test_alert_only_on_entering_category_two():
    sent, state = run_days([0, 1, 2, 2, 2])
    assert sent == [[], [], [2], [], []]
    assert state["test"] == {"category": 2, "alerted": 2, "date": "2026-08-10"}


def test_escalation_alerts_but_bouncing_does_not():
    sent, _ = run_days([2, 1, 2, 3, 2, 3, 4])
    assert sent == [[2], [], [], [3], [], [], [4]]


def test_new_episode_alerts_again():
    sent, _ = run_days([2, 0, 1, 2])
    assert sent == [[2], [], [], [2]]


def test_site_without_data_keeps_state():
    _, state = run_days([3])
    found, new_state = alerts.evaluate([status(0, has_data=False)], state)
    assert found == [] and new_state == state


def test_episode_start_and_text():
    idx = pd.date_range("2026-08-01", periods=10)
    daily = pd.DataFrame({"sst": 25.0, "in_mhw": [True, False, False] + [True] * 7}, index=idx)
    assert alerts.episode_start(daily) == pd.Timestamp("2026-08-04")
    daily.loc[idx[-1], "in_mhw"] = False
    assert alerts.episode_start(daily) is None

    text = alerts.Alert(status(2), pd.Timestamp("2026-08-04")).text("https://example.org/")
    assert "catégorie II - Forte" in text and "Site test" in text
    assert "anomalie +3.1 °C" in text and "04/08/2026" in text and text.endswith("https://example.org/")


def test_run_sends_once_and_remembers(tmp_path, monkeypatch):
    idx = pd.date_range("2026-08-01", periods=10)
    out = tmp_path / "outputs" / "test"
    out.mkdir(parents=True)
    pd.DataFrame(
        {"sst": 27.0, "seas": 24.0, "thresh": 25.5, "anom": 3.0, "category": 2, "in_mhw": True}, index=idx
    ).rename_axis("time").to_csv(out / "daily.csv")

    sent = []
    monkeypatch.setattr(alerts, "channels", lambda: {"test": lambda a, url: sent.append(a)})
    state = tmp_path / "state.json"
    sites = {"test": SITE}
    assert alerts.run(tmp_path / "outputs", state, sites=sites) == 0
    assert alerts.run(tmp_path / "outputs", state, sites=sites) == 0
    assert len(sent) == 1 and sent[0][0].episode_start == idx[0]

    # Canal en panne : l'état n'avance pas, pour réessayer au prochain passage.
    state.unlink()
    monkeypatch.setattr(alerts, "channels", lambda: {"x": lambda a, url: 1 / 0})
    assert alerts.run(tmp_path / "outputs", state, sites=sites) == 1
    assert not state.exists()
