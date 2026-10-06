"""Response models (these drive the OpenAPI documentation at /docs)."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from pydantic import BaseModel


class Health(BaseModel):
    status: str
    database: bool
    last_etl: datetime | None = None
    active_model_run: int | None = None


class Disease(BaseModel):
    code: str
    name: str
    pathogen: str | None
    transmission: str | None
    source_name: str
    source_url: str
    licence: str | None
    first_week: date | None
    last_week: date | None
    countries: int
    total_cases: int


class Summary(BaseModel):
    disease: str
    week_start: date
    new_cases: int
    new_cases_previous_week: int
    change_pct: float | None
    new_deaths: int
    countries_reporting: int
    countries_high_risk: int
    risk_week: date | None
    total_cases: int
    total_deaths: int


class GlobalWeek(BaseModel):
    week_start: date
    new_cases: int
    new_deaths: int
    countries_reporting: int


class MapRow(BaseModel):
    iso3: str
    country: str
    new_cases: int
    new_deaths: int
    cases_4w: int
    incidence_4w: float | None
    growth_4w: float | None
    risk_probability: float | None
    risk_level: str | None


class MapResponse(BaseModel):
    disease: str
    week_start: date
    rows: list[MapRow]


class SeriesPoint(BaseModel):
    week_start: date
    new_cases: int
    new_deaths: int
    incidence_per_100k: float | None
    reported: bool


class Driver(BaseModel):
    feature: str
    label: str
    effect: str
    shap: float
    value: float | None


class RiskRow(BaseModel):
    disease: str
    iso3: str
    country: str
    who_region: str | None
    week_start: date
    risk_probability: float
    risk_level: str
    cases_4w: int
    incidence_4w: float | None
    growth_4w: float | None
    top_drivers: list[Driver]
    outcome: int | None


class RiskHistoryPoint(BaseModel):
    week_start: date
    risk_probability: float
    risk_level: str
    cases_4w: int
    outcome: int | None


class ModelCard(BaseModel):
    run_id: int
    trained_at: datetime
    algorithm: str
    horizon_weeks: int
    train_end: date
    params: dict[str, Any]
    metrics: dict[str, Any]
    feature_importance: list[dict[str, Any]]


class Alert(BaseModel):
    disease: str
    iso3: str
    country: str | None
    window_start: datetime
    window_end: datetime
    cases: int
    baseline_mean: float
    baseline_std: float
    z_score: float
    severity: str
    detected_at: datetime


class StreamStatus(BaseModel):
    windows_processed: int
    series_tracked: int
    latest_window_end: datetime | None
    alerts_total: int
    last_alert_at: datetime | None


class CountryDiseaseStat(BaseModel):
    disease: str
    last_week: date | None
    total_cases: int
    total_deaths: int
    cases_last_4w: int
    risk_probability: float | None
    risk_level: str | None


class CountryProfile(BaseModel):
    iso3: str
    name: str
    continent: str | None
    subregion: str | None
    who_region: str | None
    population: int | None
    neighbours: list[dict[str, str]]
    diseases: list[CountryDiseaseStat]


class AnnualPoint(BaseModel):
    indicator: str
    iso3: str
    year: int
    value: float
