import numpy as np
import pandas as pd

from mhw_watch import detect
from mhw_watch.synthetic import synthetic_sst


def test_doy366_aligns_march_first():
    idx = pd.to_datetime(["2023-03-01", "2024-03-01", "2024-02-29", "2023-12-31"])
    assert list(detect._doy366(idx)) == [61, 61, 60, 366]


def test_climatology_shape_and_threshold_above_mean():
    clim = detect.climatology(synthetic_sst(heatwave=None))
    assert len(clim) == 366
    assert (clim["thresh"] > clim["seas"]).all()


def test_injected_heatwave_is_detected():
    sst = synthetic_sst(heatwave=("2025-07-01", 30, 3.5))
    events, daily = detect.detect(sst)
    hits = events[(pd.to_datetime(events["start"]) <= "2025-07-20")
                  & (pd.to_datetime(events["end"]) >= "2025-07-10")]
    assert len(hits) == 1
    ev = hits.iloc[0]
    assert ev["duration_days"] >= 15
    assert ev["intensity_max"] > 2.5
    assert ev["category"] != "I - Modérée"


def test_short_spikes_are_ignored_and_gaps_merged():
    idx = pd.date_range("1991-01-01", "2020-12-31", freq="D")
    sst = pd.Series(20.0 + np.random.default_rng(0).normal(0, 0.3, len(idx)), index=idx)
    # Pic de 3 jours : trop court pour une MHW.
    sst["2010-06-01":"2010-06-03"] += 3
    # Deux pics de 5 jours séparés de 2 jours : un seul événement de 12 jours.
    sst["2015-06-01":"2015-06-05"] += 3
    sst["2015-06-08":"2015-06-12"] += 3
    events, _ = detect.detect(sst)
    starts = pd.to_datetime(events["start"])
    assert not ((starts >= "2010-05-25") & (starts <= "2010-06-10")).any()
    ev = events[(starts >= "2015-05-25") & (starts <= "2015-06-15")]
    assert len(ev) == 1
    assert ev.iloc[0]["duration_days"] == 12


def test_yearly_summary_counts_days():
    events, daily = detect.detect(synthetic_sst())
    summary = detect.yearly_summary(daily)
    assert summary["mhw_days"].sum() == events["duration_days"].sum()
