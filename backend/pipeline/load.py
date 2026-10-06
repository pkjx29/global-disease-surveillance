"""PostgreSQL helpers: schema bootstrap and bulk upserts via COPY."""

from __future__ import annotations

import csv
import io
import logging

import pandas as pd
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine, make_url

from .settings import DATABASE_URL, SCHEMA_FILE

log = logging.getLogger(__name__)


def ensure_database(url: str = DATABASE_URL) -> None:
    """Create the target database when it does not exist (local development convenience)."""
    target = make_url(url)
    admin = create_engine(target.set(database="postgres"), isolation_level="AUTOCOMMIT")
    try:
        with admin.connect() as conn:
            if not conn.execute(text("SELECT 1 FROM pg_database WHERE datname = :n"), {"n": target.database}).scalar():
                conn.execute(text(f'CREATE DATABASE "{target.database}"'))
                log.info("created database %s", target.database)
    finally:
        admin.dispose()


def get_engine(url: str = DATABASE_URL) -> Engine:
    return create_engine(url, pool_pre_ping=True)


def init_schema(engine: Engine) -> None:
    raw = engine.raw_connection()
    try:
        with raw.cursor() as cur:
            cur.execute(SCHEMA_FILE.read_text(encoding="utf-8"))
        raw.commit()
    finally:
        raw.close()


def upsert(engine: Engine, table: str, df: pd.DataFrame, key: list[str]) -> int:
    """Bulk upsert: COPY into a temp table, then INSERT ... ON CONFLICT DO UPDATE."""
    if df.empty:
        return 0
    cols = list(df.columns)
    updates = [c for c in cols if c not in key]
    action = f"DO UPDATE SET {', '.join(f'{c} = EXCLUDED.{c}' for c in updates)}" if updates else "DO NOTHING"
    buf = io.StringIO()
    df.to_csv(buf, index=False, header=False, na_rep="\\N", quoting=csv.QUOTE_MINIMAL)
    buf.seek(0)
    raw = engine.raw_connection()
    try:
        with raw.cursor() as cur:
            cur.execute(f"CREATE TEMP TABLE _stage (LIKE {table} INCLUDING DEFAULTS) ON COMMIT DROP")
            cur.copy_expert(f"COPY _stage ({', '.join(cols)}) FROM STDIN WITH (FORMAT csv, NULL '\\N')", buf)
            cur.execute(
                f"INSERT INTO {table} ({', '.join(cols)}) SELECT {', '.join(cols)} FROM _stage "
                f"ON CONFLICT ({', '.join(key)}) {action}"
            )
            n = cur.rowcount
        raw.commit()
    finally:
        raw.close()
    log.info("upserted %-20s %7d rows", table, len(df))
    return n


def replace(engine: Engine, table: str, df: pd.DataFrame, where: str = "", params: dict | None = None) -> int:
    """Delete (optionally filtered) then bulk insert."""
    with engine.begin() as conn:
        conn.execute(text(f"DELETE FROM {table} {('WHERE ' + where) if where else ''}"), params or {})
    return upsert(engine, table, df, key=_primary_key(engine, table))


def _primary_key(engine: Engine, table: str) -> list[str]:
    sql = text(
        """SELECT a.attname FROM pg_index i
           JOIN pg_attribute a ON a.attrelid = i.indrelid AND a.attnum = ANY (i.indkey)
           WHERE i.indrelid = CAST(:t AS regclass) AND i.indisprimary
           ORDER BY array_position(i.indkey, a.attnum)"""
    )
    with engine.connect() as conn:
        return [r[0] for r in conn.execute(sql, {"t": table})]
