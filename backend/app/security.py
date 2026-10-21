"""API-key authentication and per-key rate limiting.

Every route except ``/health`` and ``/ready`` (the Kubernetes probes) requires an
``X-API-Key`` header that matches one of the keys in the ``API_KEYS`` setting. With no keys
configured, every protected request is refused (fail closed).

The rate limit is a fixed window: each key may make ``RATE_LIMIT_PER_MINUTE`` requests per
60-second window, then gets HTTP 429 until the window ends. The counters live in the memory
of one process, so with N API processes the real limit is N times higher.
"""

from __future__ import annotations

import math
import secrets
import threading
import time
from collections.abc import Callable

from fastapi import HTTPException, Security, status
from fastapi.security import APIKeyHeader

from .config import get_settings

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False, description="API key issued by the operator")


class RateLimiter:
    """Allow at most ``limit`` calls per ``window`` seconds for each key."""

    def __init__(self, limit: int, window: float = 60.0, clock: Callable[[], float] = time.monotonic):
        self.limit, self.window, self.clock = limit, window, clock
        self._windows: dict[str, tuple[float, int]] = {}         # key -> (window start, calls so far)
        self._lock = threading.Lock()                            # FastAPI runs sync routes in a thread pool

    def hit(self, key: str) -> float:
        """Count one call. Returns 0 if it is allowed, otherwise the seconds until the window resets."""
        now = self.clock()
        with self._lock:
            start, calls = self._windows.get(key, (now, 0))
            if now - start >= self.window:                       # previous window is over: start a new one
                start, calls = now, 0
            if calls >= self.limit:
                return start + self.window - now
            self._windows[key] = (start, calls + 1)
            return 0.0


limiter = RateLimiter(get_settings().rate_limit_per_minute)


def require_api_key(api_key: str | None = Security(api_key_header)) -> str:
    """FastAPI dependency: reject the request unless it carries a valid key that is within its rate limit."""
    valid_keys = get_settings().api_key_list
    # compare_digest takes the same time whether the first or the last character differs
    if api_key is None or not any(secrets.compare_digest(api_key.encode(), key.encode()) for key in valid_keys):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="missing or invalid API key", headers={"WWW-Authenticate": "ApiKey"})
    retry_after = limiter.hit(api_key)
    if retry_after:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, detail="rate limit exceeded", headers={"Retry-After": str(math.ceil(retry_after))})
    return api_key
