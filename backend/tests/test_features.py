"""Feature engineering: labels look forward, features never do."""

import numpy as np
import pandas as pd
import pytest

from pipeline.features import FEATURES, build_panel
from pipeline.model import classification_metrics, risk_level

WEEKS = pd.date_range("2022-01-03", periods=40, freq="7D")
COUNTRIES = pd.DataFrame({"iso3": ["AAA", "BBB"], "population": [1_000_000, 5_000_000], "lat": [10.0, -20.0], "subregion": ["X", "X"]})
NEIGHBOURS = pd.DataFrame({"iso3": ["AAA", "BBB"], "neighbour_iso3": ["BBB", "AAA"]})


def make_cases(series: dict[str, list[int]], disease: str = "covid19") -> pd.DataFrame:
    frames = [
        pd.DataFrame({"disease": disease, "iso3": iso3, "week_start": WEEKS[: len(values)], "new_cases": values, "new_deaths": 0, "reported": True})
        for iso3, values in series.items()
    ]
    return pd.concat(frames, ignore_index=True)


@pytest.fixture
def panel():
    flat = [200] * 40
    surge = [200] * 20 + [1000] * 20            # jumps five-fold at week 20
    return build_panel(make_cases({"AAA": surge, "BBB": flat}), COUNTRIES, NEIGHBOURS)


def test_label_marks_the_weeks_before_a_surge(panel):
    a = panel[panel.iso3 == "AAA"].set_index("week_start")
    assert a.loc[WEEKS[19], "label"] == 1       # next 4 weeks = 4000 vs last 4 = 800
    assert a.loc[WEEKS[17], "label"] == 1       # 2000 + 2 x 200 = 2400 over the next 4 weeks vs 800
    assert a.loc[WEEKS[10], "label"] == 0       # flat ahead
    assert a.loc[WEEKS[25], "label"] == 0       # already at the new level
    assert panel[panel.iso3 == "BBB"]["label"].sum() == 0


def test_small_absolute_numbers_are_not_outbreaks():
    tiny = [1] * 20 + [5] * 20                  # five-fold rise, but far below the minimum size
    panel = build_panel(make_cases({"AAA": tiny, "BBB": [0] * 40}), COUNTRIES, NEIGHBOURS)
    assert panel["label"].sum() == 0


def test_last_weeks_have_no_label_because_the_future_is_unknown(panel):
    tail = panel[panel.week_start > WEEKS[-5]]
    assert not tail["label_valid"].any()
    assert tail["feature_valid"].all()          # ... but they can still be scored


def test_features_do_not_see_the_future():
    base = make_cases({"AAA": [200] * 40, "BBB": [200] * 40})
    changed = base.copy()
    changed.loc[(changed.iso3 == "AAA") & (changed.week_start > WEEKS[25]), "new_cases"] = 9999
    before = build_panel(base, COUNTRIES, NEIGHBOURS)
    after = build_panel(changed, COUNTRIES, NEIGHBOURS)
    mask = before.week_start <= WEEKS[25]
    pd.testing.assert_frame_equal(before.loc[mask, FEATURES].reset_index(drop=True), after.loc[mask, FEATURES].reset_index(drop=True))


def test_gaps_in_reporting_invalidate_rows():
    cases = make_cases({"AAA": [200] * 40, "BBB": [200] * 40})
    cases = cases[~((cases.iso3 == "AAA") & cases.week_start.isin(WEEKS[10:16]))]     # six missing weeks
    panel = build_panel(cases, COUNTRIES, NEIGHBOURS)
    a = panel[panel.iso3 == "AAA"].set_index("week_start")
    assert len(a) == 40                          # the index is completed
    assert not a.loc[WEEKS[12], "reported"] and not a.loc[WEEKS[12], "feature_valid"]
    assert not a.loc[WEEKS[17], "feature_valid"]  # too few of the last 8 weeks were reported
    assert a.loc[WEEKS[30], "feature_valid"]


def test_neighbour_features_reflect_the_other_country(panel):
    b = panel[panel.iso3 == "BBB"].set_index("week_start")
    assert b.loc[WEEKS[23], "nbr_growth_4w"] > 1.0          # AAA (its neighbour) has just surged
    assert b.loc[WEEKS[10], "nbr_growth_4w"] == pytest.approx(0.0)
    assert np.isfinite(panel[FEATURES].to_numpy(dtype=float)[~np.isnan(panel[FEATURES].to_numpy(dtype=float))]).all()


def test_risk_levels_and_metrics():
    assert risk_level(np.array([0.01, 0.15, 0.4, 0.9])).tolist() == ["Low", "Moderate", "High", "Critical"]
    y = np.array([1, 1, 0, 0, 0, 0, 0, 0, 0, 0])
    m = classification_metrics(y, np.linspace(0.9, 0.0, 10))
    assert m["roc_auc"] == 1.0 and m["pr_auc"] == 1.0 and m["positives"] == 2
    assert m["capture_top_10pct"] == 0.5         # the single top-ranked row holds one of two positives
