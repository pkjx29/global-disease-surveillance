"""Feature engineering for the outbreak-risk model.

Builds a weekly panel (one row per disease, country and week) in which every
feature uses information available at the end of that week only, and the label
describes what happened over the following ``HORIZON_WEEKS``.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .settings import HORIZON_WEEKS, MIN_SURGE_CASES, MIN_SURGE_INCIDENCE, SURGE_RATIO

# name -> plain-language label (used by the API and dashboard)
FEATURE_LABELS: dict[str, str] = {
    "log_cases": "Cases this week",
    "log_cases_4w": "Cases in the last 4 weeks",
    "log_incidence_4w": "4-week incidence per 100k",
    "growth_1w": "Week-on-week growth",
    "growth_2w": "2-week growth",
    "growth_4w": "4-week growth",
    "growth_accel": "Change in growth rate",
    "zscore_12w": "Deviation from the 12-week baseline",
    "cv_12w": "Volatility over 12 weeks",
    "share_of_52w_peak": "Level relative to the past year's peak",
    "weeks_since_peak": "Weeks since the past year's peak",
    "zero_weeks_8w": "Weeks without cases in the last 8",
    "reported_frac_8w": "Reporting completeness (8 weeks)",
    "cfr_8w": "Case fatality ratio (8 weeks)",
    "growth_same_season_last_year": "What happened next at this time last year",
    "log_cases_4w_last_year": "Cases at this time last year",
    "nbr_log_incidence_4w": "Incidence in neighbouring countries",
    "nbr_growth_4w": "Growth in neighbouring countries",
    "nbr_share_growing": "Share of neighbours with rising cases",
    "region_log_incidence_4w": "Incidence across the subregion",
    "region_growth_4w": "Growth across the subregion",
    "global_growth_4w": "Global growth",
    "woy_sin": "Time of year (sine term)",
    "woy_cos": "Time of year (cosine term)",
    "lat": "Latitude",
    "abs_lat": "Distance from the equator",
    "log_population": "Population",
    "disease_code": "Which disease",
}
FEATURES = list(FEATURE_LABELS)
DISEASE_CODES = {"covid19": 0, "dengue": 1, "mpox": 2}
SERIES_KEY = ["disease", "iso3"]


def _complete_weeks(cases: pd.DataFrame) -> pd.DataFrame:
    """Give every (disease, country) an unbroken weekly index between its first and last report."""
    frames = []
    for (disease, iso3), grp in cases.groupby(["disease", "iso3"], sort=False):
        grp = grp.set_index("week_start").sort_index()
        full = pd.date_range(grp.index.min(), grp.index.max(), freq="7D")
        grp = grp.reindex(full)
        grp["reported"] = grp["reported"].fillna(False).astype(bool)
        grp[["new_cases", "new_deaths"]] = grp[["new_cases", "new_deaths"]].fillna(0)
        grp["disease"], grp["iso3"] = disease, iso3
        frames.append(grp.rename_axis("week_start").reset_index())
    return pd.concat(frames, ignore_index=True)


def _ratio(num: pd.Series, den: pd.Series) -> pd.Series:
    """Smoothed log growth ratio: 0 = flat, 0.69 = doubling."""
    return np.log((num + 1.0) / (den + 1.0))


def build_panel(cases: pd.DataFrame, countries: pd.DataFrame, neighbours: pd.DataFrame) -> pd.DataFrame:
    """Return the modelling panel with features, label and validity flags."""
    cases = cases.copy()
    cases["week_start"] = pd.to_datetime(cases["week_start"])
    df = _complete_weeks(cases).sort_values(["disease", "iso3", "week_start"]).reset_index(drop=True)
    df = df.merge(countries[["iso3", "population", "lat", "subregion"]], on="iso3", how="left")
    df["population"] = df["population"].astype(float).where(lambda s: s > 0)      # 0 = uninhabited territory
    cases_s, pop = df["new_cases"].astype(float), df["population"]

    def series(col: str):
        """Column grouped by (disease, country); rebuilt on each call so new columns are visible."""
        return df.groupby(SERIES_KEY, sort=False)[col]

    def roll(col: str, window: int, how: str = "sum", shift: int = 0) -> pd.Series:
        """Trailing-window statistic within each series, optionally lagged by ``shift`` weeks."""
        return series(col).transform(lambda s: getattr(s.shift(shift).rolling(window, min_periods=window), how)())

    c4 = roll("new_cases", 4)
    c4_prev = roll("new_cases", 4, shift=4)
    c2, c2_prev = roll("new_cases", 2), roll("new_cases", 2, shift=2)
    mean12, std12 = roll("new_cases", 12, "mean", shift=1), roll("new_cases", 12, "std", shift=1)
    peak52 = series("new_cases").transform(lambda s: s.rolling(4).sum().shift(1).rolling(52, min_periods=12).max())
    df["cases_4w"] = c4
    df["incidence_4w"] = c4 / pop * 1e5

    df["log_cases"] = np.log1p(cases_s)
    df["log_cases_4w"] = np.log1p(c4)
    df["log_incidence_4w"] = np.log1p(df["incidence_4w"])
    df["growth_1w"] = _ratio(cases_s, series("new_cases").shift(1))
    df["growth_2w"] = _ratio(c2, c2_prev)
    df["growth_4w"] = _ratio(c4, c4_prev)
    df["growth_accel"] = df["growth_4w"] - series("growth_4w").shift(2)
    df["zscore_12w"] = (cases_s - mean12) / (std12 + np.sqrt(mean12 + 1.0))
    df["cv_12w"] = std12 / (mean12 + 1.0)
    df["share_of_52w_peak"] = c4 / (peak52 + 1.0)
    df["weeks_since_peak"] = series("new_cases").transform(lambda s: s.rolling(52, min_periods=12).apply(lambda w: len(w) - 1 - int(np.argmax(w)), raw=True))
    df["zero_weeks_8w"] = series("new_cases").transform(lambda s: (s == 0).rolling(8, min_periods=8).sum())
    df["reported_frac_8w"] = series("reported").transform(lambda s: s.astype(float).rolling(8, min_periods=1).mean())
    df["cfr_8w"] = roll("new_deaths", 8) / (roll("new_cases", 8) + 1.0)

    # seasonal memory: what did the same weeks do one year ago?
    c4_last_year = series("cases_4w").shift(52)
    df["log_cases_4w_last_year"] = np.log1p(c4_last_year)
    df["growth_same_season_last_year"] = _ratio(series("cases_4w").shift(52 - HORIZON_WEEKS), c4_last_year)

    # spatial context: neighbours, subregion, world (same disease, same week)
    key = ["disease", "week_start"]
    nb_values = df[["disease", "week_start", "iso3", "incidence_4w", "growth_4w"]].rename(columns={"iso3": "neighbour_iso3"})
    nb_values["growing"] = (nb_values["growth_4w"] > 0.2).astype(float)
    nb = neighbours.merge(nb_values, on="neighbour_iso3")
    nb_agg = nb.groupby(["disease", "week_start", "iso3"]).agg(
        nbr_incidence=("incidence_4w", "mean"),
        nbr_growth_4w=("growth_4w", "mean"),
        nbr_share_growing=("growing", "mean"),
    )
    df = df.merge(nb_agg.reset_index(), on=["disease", "week_start", "iso3"], how="left")
    df["nbr_log_incidence_4w"] = np.log1p(df.pop("nbr_incidence"))

    region = df.groupby(key + ["subregion"], dropna=False).agg(r_cases=("cases_4w", "sum"), r_pop=("population", "sum")).reset_index()
    region = region.sort_values("week_start")
    region["r_prev"] = region.groupby(["disease", "subregion"], dropna=False)["r_cases"].shift(4)
    region["region_log_incidence_4w"] = np.log1p(region["r_cases"] / region["r_pop"].astype(float) * 1e5)
    region["region_growth_4w"] = _ratio(region["r_cases"], region["r_prev"])
    df = df.merge(region[key + ["subregion", "region_log_incidence_4w", "region_growth_4w"]], on=key + ["subregion"], how="left")

    world = df.groupby(key)["cases_4w"].sum().rename("w_cases").reset_index().sort_values("week_start")
    world["global_growth_4w"] = _ratio(world["w_cases"], world.groupby("disease")["w_cases"].shift(4))
    df = df.merge(world[key + ["global_growth_4w"]], on=key, how="left")

    week_of_year = df["week_start"].dt.isocalendar().week.astype(float)
    df["woy_sin"] = np.sin(2 * np.pi * week_of_year / 52.18)
    df["woy_cos"] = np.cos(2 * np.pi * week_of_year / 52.18)
    df["abs_lat"] = df["lat"].abs()
    df["log_population"] = np.log10(pop.where(pop > 0))
    df["disease_code"] = df["disease"].map(DISEASE_CODES).astype(float)

    df[FEATURES] = df[FEATURES].replace([np.inf, -np.inf], np.nan)

    # ---- label: do cases at least double over the next HORIZON_WEEKS (and reach a meaningful size)?
    df = df.sort_values(["disease", "iso3", "week_start"]).reset_index(drop=True)
    future = series("new_cases").transform(lambda s: s.rolling(HORIZON_WEEKS).sum().shift(-HORIZON_WEEKS))
    future_reported = series("reported").transform(lambda s: s.astype(float).rolling(HORIZON_WEEKS).sum().shift(-HORIZON_WEEKS))
    min_cases = df["disease"].map(MIN_SURGE_CASES).astype(float)
    min_incidence = df["disease"].map(MIN_SURGE_INCIDENCE).astype(float)
    future_incidence = (future / df["population"].astype(float) * 1e5).fillna(np.inf)    # unknown population: size test only
    df["future_cases_4w"] = future
    df["label"] = ((future >= SURGE_RATIO * df["cases_4w"].clip(lower=1)) & (future >= min_cases) & (future_incidence >= min_incidence)).astype(int)

    df["feature_valid"] = df["cases_4w"].notna() & df["growth_4w"].notna() & (df["reported_frac_8w"] >= 0.75) & df["reported"]
    df["label_valid"] = df["feature_valid"] & (future_reported == HORIZON_WEEKS)
    return df
