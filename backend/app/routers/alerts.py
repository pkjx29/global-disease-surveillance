"""Real-time anomaly alerts produced by the Flink job."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.engine import Connection

from ..config import get_settings
from ..db import fetch_all, fetch_one, get_conn, get_engine
from ..schemas import Alert, StreamStatus

router = APIRouter(tags=["stream"])

ALERT_SQL = """
    SELECT a.disease, trim(a.iso3) AS iso3, c.name AS country, a.window_start, a.window_end, a.cases,
           a.baseline_mean, a.baseline_std, a.z_score, a.severity, a.detected_at
    FROM stream_alerts a
    LEFT JOIN countries c ON c.iso3 = a.iso3
"""


@router.get("/alerts", response_model=list[Alert])
def alerts(
    disease: str | None = None,
    since: datetime | None = Query(None, description="only alerts detected after this instant"),
    limit: int = Query(50, ge=1, le=500),
    conn: Connection = Depends(get_conn),
) -> list[dict]:
    """Most recent alerts, newest first."""
    return fetch_all(
        conn,
        ALERT_SQL
        + """WHERE (CAST(:d AS text) IS NULL OR a.disease = :d)
               AND (CAST(:since AS timestamptz) IS NULL OR a.detected_at > :since)
             ORDER BY a.detected_at DESC, a.z_score DESC
             LIMIT :limit""",
        d=disease,
        since=since,
        limit=limit,
    )


@router.get("/stream/status", response_model=StreamStatus)
def stream_status(conn: Connection = Depends(get_conn)) -> dict:
    """How much the streaming job has processed (a quick liveness check for the dashboard)."""
    return fetch_one(
        conn,
        """SELECT
               (SELECT count(*) FROM stream_weekly_counts)                          AS windows_processed,
               (SELECT count(DISTINCT (disease, iso3)) FROM stream_weekly_counts)   AS series_tracked,
               (SELECT max(window_end) FROM stream_weekly_counts)                   AS latest_window_end,
               (SELECT count(*) FROM stream_alerts)                                 AS alerts_total,
               (SELECT max(detected_at) FROM stream_alerts)                         AS last_alert_at""",
    )


def _alerts_after(cursor: datetime) -> list[dict]:
    with get_engine().connect() as conn:
        return fetch_all(conn, ALERT_SQL + "WHERE a.detected_at > :c ORDER BY a.detected_at LIMIT 100", c=cursor)


@router.get("/alerts/stream")
async def alerts_stream(request: Request) -> StreamingResponse:
    """Server-Sent Events: pushes each new alert to the browser as Flink writes it."""
    poll = get_settings().alert_poll_seconds

    async def events() -> AsyncIterator[str]:
        cursor = datetime.now(UTC)
        yield "retry: 3000\n\n"
        while not await request.is_disconnected():
            rows = await asyncio.to_thread(_alerts_after, cursor)
            for row in rows:
                cursor = max(cursor, row["detected_at"])
                yield f"event: alert\ndata: {json.dumps(row, default=str)}\n\n"
            if not rows:
                yield ": keep-alive\n\n"
            await asyncio.sleep(poll)

    return StreamingResponse(events(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
