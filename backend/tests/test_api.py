"""API contract tests against the seeded database."""

from tests.conftest import FIRST_WEEK, LAST_WEEK, N_WEEKS

API = "/api/v1"


def test_health_reports_database_and_model(client):
    body = client.get(f"{API}/health").json()
    assert body["status"] == "ok" and body["database"] is True
    assert body["active_model_run"] == 1


def test_readiness_probe(client):
    assert client.get(f"{API}/ready").json() == {"status": "ready"}


def test_diseases_lists_coverage(client):
    (disease,) = client.get(f"{API}/diseases").json()
    assert disease["code"] == "testpox"
    assert disease["countries"] == 2
    assert disease["total_cases"] == (10 * (N_WEEKS - 1) + 40) + 5 * N_WEEKS


def test_summary_latest_week(client):
    body = client.get(f"{API}/summary", params={"disease": "testpox"}).json()
    assert body["week_start"] == LAST_WEEK.isoformat()
    assert body["new_cases"] == 45 and body["new_cases_previous_week"] == 15
    assert body["change_pct"] == 200.0
    assert body["countries_reporting"] == 2
    assert body["countries_high_risk"] == 1


def test_unknown_disease_is_404(client):
    assert client.get(f"{API}/summary", params={"disease": "nope"}).status_code == 404
    assert client.get(f"{API}/cases/map", params={"disease": "nope"}).status_code == 404


def test_global_series_sums_countries_and_respects_dates(client):
    rows = client.get(f"{API}/cases/global", params={"disease": "testpox"}).json()
    assert len(rows) == N_WEEKS
    assert rows[0] == {"week_start": FIRST_WEEK.isoformat(), "new_cases": 15, "new_deaths": 1, "countries_reporting": 2}
    clipped = client.get(f"{API}/cases/global", params={"disease": "testpox", "start": LAST_WEEK.isoformat()}).json()
    assert [r["new_cases"] for r in clipped] == [45]


def test_timeseries_incidence_uses_population(client):
    rows = client.get(f"{API}/cases/timeseries", params={"disease": "testpox", "iso3": "aaa"}).json()
    assert len(rows) == N_WEEKS
    assert rows[0]["incidence_per_100k"] == 1.0           # 10 cases / 1,000,000 people
    assert client.get(f"{API}/cases/timeseries", params={"disease": "testpox", "iso3": "CCC"}).status_code == 404


def test_map_snapshot_windows_and_risk_join(client):
    body = client.get(f"{API}/cases/map", params={"disease": "testpox"}).json()
    assert body["week_start"] == LAST_WEEK.isoformat()
    by_iso = {r["iso3"]: r for r in body["rows"]}
    a = by_iso["AAA"]
    assert a["new_cases"] == 40 and a["cases_4w"] == 70          # 10 + 10 + 10 + 40
    assert a["incidence_4w"] == 7.0
    assert a["growth_4w"] == round(71 / 41, 3)                   # smoothed ratio vs the previous 4 weeks
    assert a["risk_level"] == "Critical"
    assert by_iso["BBB"]["cases_4w"] == 20 and by_iso["BBB"]["growth_4w"] == 1.0


def test_geojson_feature_collection(client):
    resp = client.get(f"{API}/geo/countries")
    body = resp.json()
    assert body["type"] == "FeatureCollection"
    assert {f["id"] for f in body["features"]} == {"AAA", "BBB"}   # CCC has no geometry
    assert body["features"][0]["geometry"]["type"] == "Polygon"
    assert "max-age" in resp.headers["cache-control"]


def test_country_profile(client):
    body = client.get(f"{API}/countries/aaa").json()
    assert body["name"] == "Aland" and body["neighbours"] == [{"iso3": "BBB", "name": "Bland"}]
    (stat,) = body["diseases"]
    assert stat["cases_last_4w"] == 70 and stat["risk_level"] == "Critical"
    assert client.get(f"{API}/countries/ZZZ").status_code == 404


def test_risk_scores_ranked_and_filtered(client):
    rows = client.get(f"{API}/risk/scores", params={"disease": "testpox"}).json()
    assert [r["iso3"] for r in rows] == ["AAA", "BBB"]
    assert rows[0]["top_drivers"][0]["label"] == "4-week growth"
    high = client.get(f"{API}/risk/scores", params={"disease": "testpox", "min_level": "High"}).json()
    assert [r["iso3"] for r in high] == ["AAA"]
    assert client.get(f"{API}/risk/scores", params={"disease": "testpox", "min_level": "Extreme"}).status_code == 422


def test_risk_history_and_model_card(client):
    history = client.get(f"{API}/risk/history", params={"disease": "testpox", "iso3": "BBB"}).json()
    assert history == [{"week_start": LAST_WEEK.isoformat(), "risk_probability": 0.05, "risk_level": "Low", "cases_4w": 20, "outcome": 0}]
    card = client.get(f"{API}/risk/model").json()
    assert card["algorithm"] == "XGBoost" and card["metrics"]["xgboost"]["roc_auc"] == 0.9


def test_alerts_and_stream_status(client):
    (alert,) = client.get(f"{API}/alerts").json()
    assert alert["country"] == "Aland" and alert["severity"] == "critical" and alert["z_score"] == 9.5
    assert client.get(f"{API}/alerts", params={"disease": "other"}).json() == []
    status = client.get(f"{API}/stream/status").json()
    assert status["alerts_total"] == 1 and status["windows_processed"] == 0


def test_openapi_documents_every_router(client):
    paths = client.get(f"{API}/openapi.json").json()["paths"]
    for path in ("/health", "/cases/map", "/risk/scores", "/alerts/stream", "/geo/countries"):
        assert f"{API}{path}" in paths
