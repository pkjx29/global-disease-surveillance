"""Extract-transform-load: public disease datasets -> PostgreSQL."""

from __future__ import annotations

import json
import logging

import pandas as pd
from sqlalchemy import text

from . import geo, load, sources, transform

log = logging.getLogger(__name__)


def build_country_table(countries, who_regions: pd.DataFrame, extra_iso3: list[str]) -> pd.DataFrame:
    """Natural Earth countries plus any territory that only appears in the case data."""
    table = pd.DataFrame(countries.drop(columns="geometry"))
    table["has_geometry"] = True
    table["geometry"] = countries.geometry.map(geo.web_geometry)
    if extra_iso3:
        table = pd.concat(
            [table, pd.DataFrame({"iso3": extra_iso3, "name": [geo.country_name(c) for c in extra_iso3], "has_geometry": False})],
            ignore_index=True,
        )
    table = table.merge(who_regions, on="iso3", how="left")
    table["population"] = table["population"].astype("Int64")
    table["has_geometry"] = table["has_geometry"].astype(bool)
    cols = ["iso3", "iso2", "name", "continent", "un_region", "subregion", "who_region", "population", "lat", "lon", "has_geometry", "geometry"]
    return table[cols]


def last_complete_week(cases: pd.DataFrame, lookback_weeks: int = 104, min_share: float = 0.5):
    """Latest week in which reporting is still broad.

    Sources trail off unevenly (countries publish with different delays), so the final
    weeks of a series cover only a handful of countries. The dashboard's "latest week" is
    the last one where at least ``min_share`` of the recent peak number of countries reported.
    """
    reporting = cases[cases["reported"]].groupby("week_start")["iso3"].nunique().sort_index()
    recent_peak = reporting.rolling(lookback_weeks, min_periods=1).max()
    complete = reporting[reporting >= min_share * recent_peak]
    return complete.index.max()


def run(force: bool = False) -> dict[str, int]:
    paths = sources.download_all(force=force)
    load.ensure_database()
    engine = load.get_engine()
    load.init_schema(engine)
    with engine.begin() as conn:
        etl_id = conn.execute(text("INSERT INTO etl_runs DEFAULT VALUES RETURNING run_id")).scalar_one()

    countries = geo.load_countries(paths["countries"])
    covid, who_regions = transform.covid19(paths["covid19"])
    cases = pd.concat([covid, transform.mpox(paths["mpox"]), transform.dengue(paths["dengue"])], ignore_index=True)
    extra = sorted(set(cases["iso3"]) - set(countries["iso3"]))
    country_table = build_country_table(countries, who_regions, extra)

    annual = pd.concat(
        [transform.gho_annual(paths["cholera_cases"], "cholera_cases"), transform.gho_annual(paths["measles_cases"], "measles_cases")],
        ignore_index=True,
    )
    annual = annual[annual["iso3"].isin(country_table["iso3"])]

    span = cases[cases["reported"]].groupby("disease")["week_start"].agg(["min", "max"])
    span["max"] = pd.Series({code: last_complete_week(cases[cases["disease"] == code]) for code in span.index})
    diseases = pd.DataFrame(
        [
            {
                "code": d["code"],
                "name": d["name"],
                "pathogen": d["pathogen"],
                "transmission": d["transmission"],
                "source_name": sources.SOURCES[d["source_key"]].provider,
                "source_url": sources.SOURCES[d["source_key"]].url,
                "licence": sources.SOURCES[d["source_key"]].licence,
                "first_week": span.loc[d["code"], "min"],
                "last_week": span.loc[d["code"], "max"],
            }
            for d in transform.DISEASES
        ]
    )

    counts = {
        "countries": load.upsert(engine, "countries", country_table, ["iso3"]),
        "country_neighbours": load.replace(engine, "country_neighbours", geo.neighbours(countries)),
        "diseases": load.upsert(engine, "diseases", diseases, ["code"]),
        "case_reports": load.upsert(engine, "case_reports", cases, ["disease", "iso3", "week_start"]),
        "annual_indicators": load.upsert(engine, "annual_indicators", annual, ["indicator", "iso3", "year"]),
    }
    with engine.begin() as conn:
        conn.execute(
            text("UPDATE etl_runs SET finished_at = now(), status = 'ok', rows_loaded = CAST(:r AS jsonb) WHERE run_id = :id"),
            {"r": json.dumps(counts), "id": etl_id},
        )
        conn.execute(text("ANALYZE case_reports"))
    for code, row in span.iterrows():
        log.info("%-8s %s -> %s", code, row["min"], row["max"])
    engine.dispose()
    return counts
