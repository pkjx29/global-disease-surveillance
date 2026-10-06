"""Database access: one pooled engine, plain SQL, dict rows."""

from __future__ import annotations

from collections.abc import Iterator
from functools import lru_cache
from typing import Any

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Connection, Engine

from .config import get_settings


@lru_cache
def get_engine() -> Engine:
    settings = get_settings()
    return create_engine(settings.database_url, pool_size=settings.db_pool_size, max_overflow=5, pool_pre_ping=True)


def get_conn() -> Iterator[Connection]:
    """FastAPI dependency: a connection for the duration of the request."""
    with get_engine().connect() as conn:
        yield conn


def fetch_all(conn: Connection, sql: str, **params: Any) -> list[dict[str, Any]]:
    return [dict(row) for row in conn.execute(text(sql), params).mappings()]


def fetch_one(conn: Connection, sql: str, **params: Any) -> dict[str, Any] | None:
    row = conn.execute(text(sql), params).mappings().first()
    return dict(row) if row else None
