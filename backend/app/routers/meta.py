"""Health, disease catalogue and headline numbers."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.engine import Connection
from sqlalchemy.exc import SQLAlchemyError

from ..db import fetch_all, fetch_one, get_conn, get_engine
from ..schemas import Disease, Health, Summary

router = APIRouter(tags=["meta"])


@router.get("/health", response_model=Health)
def health() -> Health:
    """Liveness + database reachability (used by the Kubernetes probes)."""
    try:
        with get_engine().connect() as conn:
            conn.execute(text("SELECT 1"))
            last_etl = conn.execute(text("SELECT max(finished_at) FROM etl_runs WHERE status = 'ok'")).scalar()
            run_id = conn.execute(text("SELECT run_id FROM v_active_run")).scalar()
        return Health(status="ok", database=True, last_etl=last_etl, active_model_run=run_id)
    except SQLAlchemyError:
        return Health(status="degraded", database=False)


@router.get("/ready", include_in_schema=False)
def ready() -> dict:
    """Readiness probe: 503 until the database is reachable and the schema exists."""
    try:
        with get_engine().connect() as conn:
            conn.execute(text("SELECT 1 FROM diseases LIMIT 1"))
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=503, detail="database not ready") from exc
    return {"status": "ready"}


@router.get("/diseases", response_model=list[Disease])
def diseases(conn: Connection = Depends(get_conn)) -> list[dict]:
    """Diseases under surveillance, with their source and coverage."""
    return fetch_all(
        conn,
        """SELECT d.*, coalesce(s.countries, 0) AS countries, coalesce(s.total_cases, 0) AS total_cases
           FROM diseases d
           LEFT JOIN (
               SELECT disease, count(DISTINCT iso3) AS countries, sum(new_cases) AS total_cases
               FROM case_reports WHERE new_cases > 0 GROUP BY disease
           ) s ON s.disease = d.code
           ORDER BY d.name""",
    )


def require_disease(conn: Connection, disease: str) -> dict:
    row = fetch_one(conn, "SELECT code, first_week, last_week FROM diseases WHERE code = :d", d=disease)
    if row is None:
        raise HTTPException(status_code=404, detail=f"unknown disease '{disease}'")
    return row


@router.get("/summary", response_model=Summary)
def summary(disease: str, conn: Connection = Depends(get_conn)) -> dict:
    """Headline figures for the latest reported week of a disease."""
    meta = require_disease(conn, disease)
    row = fetch_one(
        conn,
        """WITH latest AS (SELECT CAST(:week AS date) AS week),
           totals AS (
               SELECT sum(new_cases) AS total_cases, sum(new_deaths) AS total_deaths
               FROM case_reports WHERE disease = :d
           ),
           wk AS (
               SELECT
                   coalesce(sum(new_cases)  FILTER (WHERE week_start = (SELECT week FROM latest)), 0) AS new_cases,
                   coalesce(sum(new_cases)  FILTER (WHERE week_start = (SELECT week FROM latest) - 7), 0) AS prev_cases,
                   coalesce(sum(new_deaths) FILTER (WHERE week_start = (SELECT week FROM latest)), 0) AS new_deaths,
                   count(*) FILTER (WHERE week_start = (SELECT week FROM latest) AND reported) AS countries_reporting
               FROM case_reports
               WHERE disease = :d AND week_start >= (SELECT week FROM latest) - 7
           ),
           risk AS (
               SELECT max(week_start) AS risk_week FROM risk_scores
               WHERE disease = :d AND run_id = (SELECT run_id FROM v_active_run) AND week_start <= (SELECT week FROM latest)
           )
           SELECT
               wk.new_cases, wk.prev_cases AS new_cases_previous_week, wk.new_deaths, wk.countries_reporting,
               CASE WHEN wk.prev_cases > 0 THEN round(100.0 * (wk.new_cases - wk.prev_cases) / wk.prev_cases, 1) END AS change_pct,
               totals.total_cases, totals.total_deaths, risk.risk_week,
               (SELECT count(*) FROM risk_scores s
                 WHERE s.disease = :d AND s.run_id = (SELECT run_id FROM v_active_run)
                   AND s.week_start = risk.risk_week AND s.risk_level IN ('High', 'Critical')) AS countries_high_risk
           FROM wk, totals, risk""",
        d=disease,
        week=meta["last_week"],
    )
    return {"disease": disease, "week_start": meta["last_week"], **row}
