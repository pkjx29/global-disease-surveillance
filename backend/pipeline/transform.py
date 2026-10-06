"""Normalise each source into the same weekly shape.

Every transform returns a DataFrame with the columns
``disease, iso3, week_start, new_cases, new_deaths, reported`` where
``week_start`` is the Monday of the ISO week.
"""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pandas as pd

from .geo import iso2_to_iso3

COLUMNS = ["disease", "iso3", "week_start", "new_cases", "new_deaths", "reported"]
DENGUE_FIRST_YEAR = 1990          # OpenDengue's stated coverage; a handful of earlier rows are isolated archive records

DISEASES = [
    {
        "code": "covid19",
        "name": "COVID-19",
        "pathogen": "SARS-CoV-2 (virus)",
        "transmission": "Respiratory",
        "source_key": "covid19",
    },
    {
        "code": "mpox",
        "name": "Mpox",
        "pathogen": "Monkeypox virus",
        "transmission": "Close contact",
        "source_key": "mpox",
    },
    {
        "code": "dengue",
        "name": "Dengue",
        "pathogen": "Dengue virus (DENV 1-4)",
        "transmission": "Mosquito-borne (Aedes)",
        "source_key": "dengue",
    },
]


def week_monday(dates: pd.Series) -> pd.Series:
    """Monday of the ISO week each date falls in."""
    dates = pd.to_datetime(dates)
    return (dates - pd.to_timedelta(dates.dt.weekday, unit="D")).dt.normalize()


def _finish(df: pd.DataFrame, disease: str) -> pd.DataFrame:
    df = df.dropna(subset=["iso3", "week_start"]).copy()
    df["disease"] = disease
    df["new_cases"] = df["new_cases"].fillna(0).clip(lower=0).round().astype(int)
    df["new_deaths"] = df["new_deaths"].fillna(0).clip(lower=0).round().astype(int)
    df["reported"] = df["reported"].astype(bool)
    df["week_start"] = pd.to_datetime(df["week_start"]).dt.date
    return df[COLUMNS].sort_values(["iso3", "week_start"]).reset_index(drop=True)


def covid19(path: str | Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    """WHO weekly COVID-19 counts. Also returns the WHO region of each country."""
    # keep_default_na=False: Namibia's ISO code is the string "NA"
    raw = pd.read_csv(path, keep_default_na=False, na_values=[""])
    raw["iso3"] = raw["Country_code"].map(iso2_to_iso3)
    raw = raw.dropna(subset=["iso3"])                      # drops "international conveyance" rows
    # WHO dates each record by the Sunday that closes the week
    raw["week_start"] = week_monday(pd.to_datetime(raw["Date_reported"]) - pd.Timedelta(days=6))
    df = pd.DataFrame(
        {
            "iso3": raw["iso3"],
            "week_start": raw["week_start"],
            "new_cases": raw["New_cases"],
            "new_deaths": raw["New_deaths"],
            "reported": raw["New_cases"].notna(),
        }
    )
    regions = raw[["iso3", "WHO_region"]].drop_duplicates("iso3").rename(columns={"WHO_region": "who_region"})
    return _finish(df, "covid19"), regions


def mpox(path: str | Path) -> pd.DataFrame:
    """OWID / WHO daily mpox counts, summed to ISO weeks."""
    raw = pd.read_csv(path, usecols=["iso_code", "date", "new_cases", "new_deaths"], low_memory=False)
    raw = raw[~raw["iso_code"].astype(str).str.startswith("OWID")]      # drop continent / world aggregates
    raw["week_start"] = week_monday(raw["date"])
    df = (
        raw.groupby(["iso_code", "week_start"], as_index=False)
        .agg(new_cases=("new_cases", "sum"), new_deaths=("new_deaths", "sum"), days=("date", "nunique"))
        .rename(columns={"iso_code": "iso3"})
    )
    df = df[df["days"] == 7]                                # partial first/last weeks would look like dips
    df["reported"] = True
    return _finish(df, "mpox")


def dengue(path: str | Path) -> pd.DataFrame:
    """OpenDengue national extract, weekly-resolution records only."""
    with zipfile.ZipFile(path) as archive:
        with archive.open(archive.namelist()[0]) as fh:
            raw = pd.read_csv(fh)
    raw = raw[(raw["T_res"] == "Week") & raw["dengue_total"].notna() & (raw["Year"] >= DENGUE_FIRST_YEAR)].copy()
    # epidemiological weeks run Sunday-Saturday; assign each to the ISO week holding its midpoint
    raw["week_start"] = week_monday(pd.to_datetime(raw["calendar_start_date"]) + pd.Timedelta(days=3))
    df = raw.groupby(["ISO_A0", "week_start"], as_index=False).agg(new_cases=("dengue_total", "max")).rename(columns={"ISO_A0": "iso3"})
    df["new_deaths"] = 0                                    # the extract carries case counts only
    df["reported"] = True
    return _finish(df, "dengue")


def gho_annual(path: str | Path, indicator: str) -> pd.DataFrame:
    """WHO Global Health Observatory annual country totals."""
    values = json.loads(Path(path).read_text(encoding="utf-8"))["value"]
    raw = pd.DataFrame(values)
    raw = raw[raw["SpatialDimType"] == "COUNTRY"].copy()
    # older records carry the figure only as display text ("1 234"), so fall back to parsing it
    parsed = pd.to_numeric(raw["Value"].astype(str).str.replace(r"[\s,]", "", regex=True), errors="coerce")
    raw["value"] = raw["NumericValue"].fillna(parsed)
    raw = raw.dropna(subset=["value"])
    df = pd.DataFrame({"indicator": indicator, "iso3": raw["SpatialDim"], "year": raw["TimeDim"].astype(int), "value": raw["value"].astype(float)})
    return df.drop_duplicates(["indicator", "iso3", "year"]).reset_index(drop=True)
