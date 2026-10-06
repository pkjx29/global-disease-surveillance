"""Source normalisation: each transform must produce Monday-based weekly rows."""

import json
import zipfile
from datetime import date

import pandas as pd

from pipeline import transform
from pipeline.geo import iso2_to_iso3


def test_week_monday():
    out = transform.week_monday(pd.Series(["2024-01-01", "2024-01-07", "2024-01-08"]))
    assert [d.date() for d in out] == [date(2024, 1, 1), date(2024, 1, 1), date(2024, 1, 8)]


def test_iso2_to_iso3_handles_namibia_and_kosovo():
    assert iso2_to_iso3("NA") == "NAM"
    assert iso2_to_iso3("XK") == "XKX"
    assert iso2_to_iso3("XXL") is None


def test_covid19_weekly(tmp_path):
    csv = tmp_path / "covid.csv"
    csv.write_text(
        "Date_reported,Country_code,Country,WHO_region,New_cases,Cumulative_cases,New_deaths,Cumulative_deaths\n"
        "2024-01-07,NA,Namibia,AFRO,12,12,1,1\n"          # Sunday closing the week of Mon 2024-01-01
        "2024-01-14,NA,Namibia,AFRO,,12,,1\n"             # nothing reported
        "2024-01-07,IN,India,SEARO,-5,0,0,0\n"            # negative correction
        "2024-01-07,XXL,International commercial vessel,OTHER,3,3,0,0\n"
    )
    df, regions = transform.covid19(csv)
    assert set(df["iso3"]) == {"NAM", "IND"}               # "NA" is not parsed as missing; the vessel is dropped
    nam = df[df.iso3 == "NAM"].reset_index(drop=True)
    assert nam.loc[0, "week_start"] == date(2024, 1, 1) and nam.loc[0, "new_cases"] == 12 and bool(nam.loc[0, "reported"])
    assert nam.loc[1, "week_start"] == date(2024, 1, 8) and nam.loc[1, "new_cases"] == 0 and not bool(nam.loc[1, "reported"])
    assert df[df.iso3 == "IND"]["new_cases"].item() == 0   # clipped at zero
    assert dict(zip(regions.iso3, regions.who_region, strict=True)) == {"NAM": "AFRO", "IND": "SEARO"}


def test_mpox_daily_to_weekly(tmp_path):
    days = pd.date_range("2024-01-01", "2024-01-16")       # two full ISO weeks + two days
    rows = [{"iso_code": "COD", "date": d.date(), "new_cases": 2, "new_deaths": 0} for d in days]
    rows += [{"iso_code": "OWID_AFR", "date": d.date(), "new_cases": 99, "new_deaths": 0} for d in days]
    csv = tmp_path / "mpox.csv"
    pd.DataFrame(rows).to_csv(csv, index=False)
    df = transform.mpox(csv)
    assert set(df["iso3"]) == {"COD"}                      # continental aggregate removed
    assert df["week_start"].tolist() == [date(2024, 1, 1), date(2024, 1, 8)]   # the partial third week is dropped
    assert df["new_cases"].tolist() == [14, 14]


def test_dengue_keeps_weekly_records_only(tmp_path):
    raw = pd.DataFrame(
        {
            "ISO_A0": ["BRA", "BRA", "BRA", "BRA"],
            "calendar_start_date": ["2023-01-01", "2023-01-08", "2023-01-01", "1985-01-06"],
            "calendar_end_date": ["2023-01-07", "2023-01-14", "2023-01-31", "1985-01-12"],
            "Year": [2023, 2023, 2023, 1985],
            "dengue_total": [100.0, 150.0, 999.0, 5.0],
            "T_res": ["Week", "Week", "Month", "Week"],
        }
    )
    path = tmp_path / "dengue.zip"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("National_extract.csv", raw.to_csv(index=False))
    df = transform.dengue(path)
    # epi week starting Sunday 1 Jan 2023 maps to the ISO week of Monday 2 Jan
    assert df["week_start"].tolist() == [date(2023, 1, 2), date(2023, 1, 9)]
    assert df["new_cases"].tolist() == [100, 150]


def test_gho_annual_parses_display_values(tmp_path):
    payload = {
        "value": [
            {"SpatialDimType": "COUNTRY", "SpatialDim": "IND", "TimeDim": 2010, "NumericValue": 31458.0, "Value": "31 458"},
            {"SpatialDimType": "COUNTRY", "SpatialDim": "IND", "TimeDim": 1980, "NumericValue": None, "Value": "1 234"},
            {"SpatialDimType": "COUNTRY", "SpatialDim": "IND", "TimeDim": 1981, "NumericValue": None, "Value": None},
            {"SpatialDimType": "REGION", "SpatialDim": "SEAR", "TimeDim": 2010, "NumericValue": 5.0, "Value": "5"},
        ]
    }
    path = tmp_path / "gho.json"
    path.write_text(json.dumps(payload))
    df = transform.gho_annual(path, "measles_cases")
    assert sorted(zip(df.year, df.value, strict=True)) == [(1980, 1234.0), (2010, 31458.0)]
