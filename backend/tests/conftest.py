"""Test fixtures: a throw-away PostgreSQL database seeded with a tiny, known dataset."""

from __future__ import annotations

import json
import os
from datetime import date, timedelta

import pandas as pd
import pytest
from sqlalchemy import text
from sqlalchemy.exc import OperationalError

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL", "postgresql+psycopg2://localhost:5432/disease_surveillance_test")
os.environ["DATABASE_URL"] = TEST_DATABASE_URL      # must be set before the app modules are imported

FIRST_WEEK = date(2024, 1, 1)                        # a Monday
N_WEEKS = 12
LAST_WEEK = FIRST_WEEK + timedelta(weeks=N_WEEKS - 1)
SQUARE = {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]]}
DRIVER = {"feature": "growth_4w", "label": "4-week growth", "effect": "raises", "shap": 1.2, "value": 0.9}


@pytest.fixture(scope="session")
def engine():
    from pipeline import load

    try:
        load.ensure_database(TEST_DATABASE_URL)
        eng = load.get_engine(TEST_DATABASE_URL)
        load.init_schema(eng)
    except OperationalError as exc:      # no database available: unit tests still run
        pytest.skip(f"PostgreSQL not reachable: {exc}")

    with eng.begin() as conn:
        conn.execute(text("TRUNCATE countries, diseases, model_runs, stream_alerts, stream_weekly_counts, etl_runs RESTART IDENTITY CASCADE"))
        conn.execute(
            text(
                """INSERT INTO countries (iso3, iso2, name, continent, subregion, who_region, population, lat, lon, has_geometry, geometry) VALUES
                   ('AAA', 'AA', 'Aland', 'Asia', 'Southern Asia', 'SEARO', 1000000, 0.5, 0.5, true, CAST(:g AS jsonb)),
                   ('BBB', 'BB', 'Bland', 'Asia', 'Southern Asia', 'SEARO', 2000000, 0.5, 1.5, true, CAST(:g AS jsonb)),
                   ('CCC', 'CC', 'Cland', NULL, NULL, NULL, NULL, NULL, NULL, false, NULL)"""
            ),
            {"g": json.dumps(SQUARE)},
        )
        conn.execute(text("INSERT INTO country_neighbours VALUES ('AAA', 'BBB'), ('BBB', 'AAA')"))
        conn.execute(
            text(
                """INSERT INTO diseases (code, name, pathogen, transmission, source_name, source_url, licence, first_week, last_week)
                   VALUES ('testpox', 'Testpox', 'virus', 'contact', 'unit test', 'https://example.org', 'CC0', :f, :l)"""
            ),
            {"f": FIRST_WEEK, "l": LAST_WEEK},
        )
        conn.execute(text("INSERT INTO etl_runs (finished_at, status) VALUES (now(), 'ok')"))
        run_id = conn.execute(
            text(
                """INSERT INTO model_runs (algorithm, horizon_weeks, train_end, params, metrics, feature_importance, is_active)
                   VALUES ('XGBoost', 4, '2023-12-31', '{}', '{"xgboost": {"roc_auc": 0.9}}', '[{"feature": "growth_4w", "gain": 1.0}]', true)
                   RETURNING run_id"""
            )
        ).scalar_one()
        conn.execute(
            text(
                """INSERT INTO risk_scores
                       (run_id, disease, iso3, week_start, risk_probability, risk_level, cases_4w, incidence_4w, growth_4w, top_drivers, outcome)
                   VALUES
                       (:r, 'testpox', 'AAA', :w, 0.72, 'Critical', 100, 10.0, 2.5, CAST(:drivers AS jsonb), NULL),
                       (:r, 'testpox', 'BBB', :w, 0.05, 'Low', 20, 1.0, 1.0, '[]', 0)"""
            ),
            {"r": run_id, "w": LAST_WEEK, "drivers": json.dumps([DRIVER])},
        )
        conn.execute(
            text(
                """INSERT INTO stream_alerts (disease, iso3, window_start, window_end, cases, baseline_mean, baseline_std, z_score, severity)
                   VALUES ('testpox', 'AAA', '2024-03-18', '2024-03-25', 40, 10, 2, 9.5, 'critical')"""
            )
        )

    # AAA: 10 cases a week, 40 in the final week; BBB: flat 5 a week
    weeks = [FIRST_WEEK + timedelta(weeks=i) for i in range(N_WEEKS)]
    rows = [{"disease": "testpox", "iso3": "AAA", "week_start": w, "new_cases": 40 if w == LAST_WEEK else 10, "new_deaths": 1, "reported": True} for w in weeks]
    rows += [{"disease": "testpox", "iso3": "BBB", "week_start": w, "new_cases": 5, "new_deaths": 0, "reported": True} for w in weeks]
    load.upsert(eng, "case_reports", pd.DataFrame(rows), ["disease", "iso3", "week_start"])
    yield eng
    eng.dispose()


@pytest.fixture(scope="session")
def client(engine):
    from fastapi.testclient import TestClient

    from app import config, db

    config.get_settings.cache_clear()
    db.get_engine.cache_clear()
    from app.main import create_app

    with TestClient(create_app()) as test_client:
        yield test_client
