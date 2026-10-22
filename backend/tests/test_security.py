"""API keys and rate limiting: probes stay open, everything else needs a valid key."""

import pytest

from app import security
from app.security import RateLimiter
from tests.conftest import TEST_API_KEY

API = "/api/v1"


@pytest.fixture
def anonymous(client):
    """The same app, but requests carry no API key unless a test adds one."""
    client.headers.pop("X-API-Key")
    yield client
    client.headers["X-API-Key"] = TEST_API_KEY


def test_probes_and_docs_need_no_key(anonymous):
    assert anonymous.get(f"{API}/health").status_code == 200
    assert anonymous.get(f"{API}/ready").status_code == 200
    assert anonymous.get(f"{API}/openapi.json").status_code == 200


@pytest.mark.parametrize("path", ["/diseases", "/summary?disease=testpox", "/cases/global?disease=testpox", "/risk/model", "/alerts", "/geo/countries"])
def test_data_routes_reject_missing_or_wrong_key(anonymous, path):
    missing = anonymous.get(f"{API}{path}")
    assert missing.status_code == 401
    assert missing.headers["WWW-Authenticate"] == "ApiKey"
    assert anonymous.get(f"{API}{path}", headers={"X-API-Key": "wrong"}).status_code == 401
    assert anonymous.get(f"{API}{path}", headers={"X-API-Key": TEST_API_KEY}).status_code == 200


def test_openapi_documents_the_api_key(anonymous):
    spec = anonymous.get(f"{API}/openapi.json").json()
    assert spec["components"]["securitySchemes"]["APIKeyHeader"] == {
        "type": "apiKey", "in": "header", "name": "X-API-Key", "description": "API key issued by the operator"
    }


def test_rate_limit_returns_429_with_retry_after(client, monkeypatch):
    monkeypatch.setattr(security, "limiter", RateLimiter(limit=3))
    codes = [client.get(f"{API}/diseases").status_code for _ in range(4)]
    assert codes == [200, 200, 200, 429]
    blocked = client.get(f"{API}/diseases")
    assert 0 < int(blocked.headers["Retry-After"]) <= 60
    assert client.get(f"{API}/health").status_code == 200        # probes are never rate-limited


def test_rate_limiter_window_resets_and_keys_are_independent():
    now = [0.0]
    limiter = RateLimiter(limit=2, window=60, clock=lambda: now[0])
    assert [limiter.hit("a"), limiter.hit("a")] == [0.0, 0.0]
    assert limiter.hit("a") == 60.0              # third call in the window: wait 60 s
    assert limiter.hit("b") == 0.0               # another key has its own budget
    now[0] = 45.0
    assert limiter.hit("a") == 15.0
    now[0] = 60.0                                # new window
    assert limiter.hit("a") == 0.0
