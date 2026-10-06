"""Case counts: global series, per-country series and the map snapshot."""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.engine import Connection

from ..db import fetch_all, get_conn
from ..schemas import GlobalWeek, MapResponse, SeriesPoint
from .meta import require_disease

router = APIRouter(prefix="/cases", tags=["cases"])


@router.get("/global", response_model=list[GlobalWeek])
def global_series(disease: str, start: date | None = None, end: date | None = None, conn: Connection = Depends(get_conn)) -> list[dict]:
    """Worldwide weekly totals for one disease."""
    require_disease(conn, disease)
    return fetch_all(
        conn,
        """SELECT week_start, new_cases, new_deaths, countries_reporting
           FROM v_global_weekly
           WHERE disease = :d
             AND (CAST(:start AS date) IS NULL OR week_start >= :start)
             AND (CAST(:end AS date) IS NULL OR week_start <= :end)
           ORDER BY week_start""",
        d=disease,
        start=start,
        end=end,
    )


@router.get("/timeseries", response_model=list[SeriesPoint])
def timeseries(disease: str, iso3: str, start: date | None = None, end: date | None = None, conn: Connection = Depends(get_conn)) -> list[dict]:
    """Weekly series for one country."""
    require_disease(conn, disease)
    rows = fetch_all(
        conn,
        """SELECT week_start, new_cases, new_deaths, round(incidence_per_100k::numeric, 3) AS incidence_per_100k, reported
           FROM v_weekly_incidence
           WHERE disease = :d AND iso3 = :i
             AND (CAST(:start AS date) IS NULL OR week_start >= :start)
             AND (CAST(:end AS date) IS NULL OR week_start <= :end)
           ORDER BY week_start""",
        d=disease,
        i=iso3.upper(),
        start=start,
        end=end,
    )
    if not rows:
        raise HTTPException(status_code=404, detail=f"no {disease} data for '{iso3}'")
    return rows


@router.get("/map", response_model=MapResponse)
def map_snapshot(
    disease: str,
    week: date | None = Query(None, description="Monday of the ISO week; defaults to the latest reported week"),
    conn: Connection = Depends(get_conn),
) -> dict:
    """Per-country snapshot for the choropleth: 4-week cases, incidence, growth and model risk."""
    meta = require_disease(conn, disease)
    week = week or meta["last_week"]
    rows = fetch_all(
        conn,
        """WITH win AS (
               SELECT
                   iso3,
                   coalesce(sum(new_cases)  FILTER (WHERE week_start = :w), 0)                               AS new_cases,
                   coalesce(sum(new_deaths) FILTER (WHERE week_start = :w), 0)                               AS new_deaths,
                   coalesce(sum(new_cases)  FILTER (WHERE week_start > CAST(:w AS date) - 28), 0)            AS cases_4w,
                   coalesce(sum(new_cases)  FILTER (WHERE week_start <= CAST(:w AS date) - 28), 0)           AS prev_4w
               FROM case_reports
               WHERE disease = :d AND week_start > CAST(:w AS date) - 56 AND week_start <= :w
               GROUP BY iso3
           )
           SELECT
               trim(c.iso3) AS iso3,
               c.name AS country,
               win.new_cases, win.new_deaths, win.cases_4w,
               CASE WHEN c.population > 0 THEN round((win.cases_4w * 100000.0 / c.population)::numeric, 3) END AS incidence_4w,
               round(((win.cases_4w + 1.0) / (win.prev_4w + 1.0))::numeric, 3) AS growth_4w,
               s.risk_probability, s.risk_level
           FROM win
           JOIN countries c USING (iso3)
           LEFT JOIN risk_scores s
             ON s.iso3 = win.iso3 AND s.disease = :d AND s.week_start = :w
            AND s.run_id = (SELECT run_id FROM v_active_run)
           ORDER BY win.cases_4w DESC""",
        d=disease,
        w=week,
    )
    return {"disease": disease, "week_start": week, "rows": rows}
