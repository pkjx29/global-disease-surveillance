"""XGBoost outbreak-risk scores and the model card."""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.engine import Connection

from ..db import fetch_all, fetch_one, get_conn
from ..schemas import ModelCard, RiskHistoryPoint, RiskRow
from .meta import require_disease

router = APIRouter(prefix="/risk", tags=["risk"])

LEVELS = ["Low", "Moderate", "High", "Critical"]


@router.get("/scores", response_model=list[RiskRow])
def risk_scores(
    disease: str,
    week: date | None = Query(None, description="defaults to the latest complete reporting week"),
    min_level: str = Query("Low", description="lowest risk level to include"),
    limit: int = Query(300, ge=1, le=500),
    conn: Connection = Depends(get_conn),
) -> list[dict]:
    """Countries ranked by the probability of an outbreak over the next four weeks."""
    meta = require_disease(conn, disease)
    if min_level not in LEVELS:
        raise HTTPException(status_code=422, detail=f"min_level must be one of {LEVELS}")
    return fetch_all(
        conn,
        """SELECT s.disease, trim(s.iso3) AS iso3, c.name AS country, c.who_region, s.week_start,
                  s.risk_probability, s.risk_level, s.cases_4w, s.incidence_4w, s.growth_4w,
                  coalesce(s.top_drivers, '[]'::jsonb) AS top_drivers, s.outcome
           FROM risk_scores s
           JOIN countries c USING (iso3)
           WHERE s.run_id = (SELECT run_id FROM v_active_run)
             AND s.disease = :d
             AND s.week_start = :w
             AND s.risk_level = ANY(:levels)
           ORDER BY s.risk_probability DESC
           LIMIT :limit""",
        d=disease,
        w=week or meta["last_week"],
        levels=LEVELS[LEVELS.index(min_level):],
        limit=limit,
    )


@router.get("/history", response_model=list[RiskHistoryPoint])
def risk_history(disease: str, iso3: str, conn: Connection = Depends(get_conn)) -> list[dict]:
    """Weekly risk for one country, with what actually happened once known (back-test)."""
    require_disease(conn, disease)
    return fetch_all(
        conn,
        """SELECT week_start, risk_probability, risk_level, cases_4w, outcome
           FROM risk_scores
           WHERE run_id = (SELECT run_id FROM v_active_run) AND disease = :d AND iso3 = :i
           ORDER BY week_start""",
        d=disease,
        i=iso3.upper(),
    )


@router.get("/model", response_model=ModelCard)
def model_card(conn: Connection = Depends(get_conn)) -> dict:
    """The active model: training cut-off, held-out metrics and feature importance."""
    row = fetch_one(conn, "SELECT run_id, trained_at, algorithm, horizon_weeks, train_end, params, metrics, feature_importance FROM v_active_run")
    if row is None:
        raise HTTPException(status_code=404, detail="no trained model yet - run `python -m pipeline train`")
    return row
