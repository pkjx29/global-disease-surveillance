"""Country geometry and profiles."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.engine import Connection

from ..db import fetch_all, fetch_one, get_conn
from ..schemas import AnnualPoint, CountryProfile

router = APIRouter(tags=["geography"])


@router.get("/geo/countries")
def countries_geojson(response: Response, conn: Connection = Depends(get_conn)) -> dict:
    """World countries as a GeoJSON FeatureCollection (simplified for web maps)."""
    rows = fetch_all(
        conn,
        """SELECT iso3, name, continent, subregion, who_region, population, lat, lon, geometry
           FROM countries WHERE has_geometry AND geometry IS NOT NULL ORDER BY iso3""",
    )
    response.headers["Cache-Control"] = "public, max-age=86400"
    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "id": r["iso3"].strip(),
                "properties": {k: (v.strip() if k == "iso3" else v) for k, v in r.items() if k != "geometry"},
                "geometry": r["geometry"],
            }
            for r in rows
        ],
    }


@router.get("/countries/{iso3}", response_model=CountryProfile)
def country_profile(iso3: str, conn: Connection = Depends(get_conn)) -> dict:
    """Reference data, neighbours and per-disease status for one country."""
    iso3 = iso3.upper()
    country = fetch_one(conn, "SELECT iso3, name, continent, subregion, who_region, population FROM countries WHERE iso3 = :i", i=iso3)
    if country is None:
        raise HTTPException(status_code=404, detail=f"unknown country '{iso3}'")
    neighbours = fetch_all(
        conn,
        """SELECT c.iso3, c.name FROM country_neighbours n JOIN countries c ON c.iso3 = n.neighbour_iso3
           WHERE n.iso3 = :i ORDER BY c.name""",
        i=iso3,
    )
    diseases = fetch_all(
        conn,
        """SELECT
               d.code AS disease,
               max(r.week_start) FILTER (WHERE r.reported) AS last_week,
               coalesce(sum(r.new_cases), 0)  AS total_cases,
               coalesce(sum(r.new_deaths), 0) AS total_deaths,
               coalesce(sum(r.new_cases) FILTER (WHERE r.week_start > d.last_week - 28), 0) AS cases_last_4w,
               s.risk_probability,
               s.risk_level
           FROM diseases d
           LEFT JOIN case_reports r ON r.disease = d.code AND r.iso3 = :i
           LEFT JOIN LATERAL (
               SELECT risk_probability, risk_level FROM risk_scores
               WHERE disease = d.code AND iso3 = :i AND run_id = (SELECT run_id FROM v_active_run)
               ORDER BY week_start DESC LIMIT 1
           ) s ON true
           GROUP BY d.code, d.name, s.risk_probability, s.risk_level
           ORDER BY d.name""",
        i=iso3,
    )
    country["iso3"] = country["iso3"].strip()
    return {**country, "neighbours": [{"iso3": n["iso3"].strip(), "name": n["name"]} for n in neighbours], "diseases": diseases}


@router.get("/annual", response_model=list[AnnualPoint])
def annual_indicators(indicator: str, iso3: str | None = None, conn: Connection = Depends(get_conn)) -> list[dict]:
    """Annual WHO GHO totals (``cholera_cases`` or ``measles_cases``); world total when no country is given."""
    if indicator not in ("cholera_cases", "measles_cases"):
        raise HTTPException(status_code=404, detail="indicator must be cholera_cases or measles_cases")
    if iso3:
        return fetch_all(
            conn,
            "SELECT indicator, trim(iso3) AS iso3, year, value FROM annual_indicators WHERE indicator = :n AND iso3 = :i ORDER BY year",
            n=indicator,
            i=iso3.upper(),
        )
    return fetch_all(
        conn,
        "SELECT indicator, 'WLD' AS iso3, year, sum(value) AS value FROM annual_indicators WHERE indicator = :n GROUP BY indicator, year ORDER BY year",
        n=indicator,
    )
