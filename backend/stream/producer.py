"""Replay historical case reports into Kafka as a live event stream.

Public surveillance data is published weekly, so there is no true real-time feed to
subscribe to. This producer simulates one: it reads the weekly counts from PostgreSQL,
splits each into daily report events and publishes them in calendar order at an
accelerated pace. The Flink job downstream treats the topic exactly as it would a live feed.

    python -m stream.producer
"""

from __future__ import annotations

import json
import logging
import os
import signal
import time
import uuid
from datetime import timedelta

import numpy as np
import pandas as pd
from kafka import KafkaConsumer, KafkaProducer, TopicPartition
from kafka.errors import KafkaError
from sqlalchemy import create_engine, text

log = logging.getLogger("stream.producer")

DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql+psycopg2://localhost:5432/disease_surveillance")
BOOTSTRAP = os.environ.get("KAFKA_BOOTSTRAP_SERVERS", "localhost:19092")
TOPIC = os.environ.get("KAFKA_TOPIC", "case-reports")
REPLAY_START = os.environ.get("REPLAY_START", "2023-01-02")
REPLAY_END = os.environ.get("REPLAY_END", "")                       # empty = to the end of the data
WEEKS_PER_SECOND = float(os.environ.get("REPLAY_WEEKS_PER_SECOND", "0.5"))
SEED = int(os.environ.get("REPLAY_SEED", "7"))

_running = True


def _stop(*_: object) -> None:
    global _running
    _running = False


def load_reports() -> pd.DataFrame:
    sql = text(
        """SELECT disease, trim(iso3) AS iso3, week_start, new_cases, new_deaths
           FROM case_reports
           WHERE reported AND (new_cases > 0 OR new_deaths > 0)
             AND week_start >= :start AND (CAST(:end AS date) IS NULL OR week_start <= :end)
           ORDER BY week_start, disease, iso3"""
    )
    engine = create_engine(DATABASE_URL)
    with engine.connect() as conn:
        df = pd.read_sql(sql, conn, params={"start": REPLAY_START, "end": REPLAY_END or None})
    engine.dispose()
    return df


def daily_events(week: pd.DataFrame, rng: np.random.Generator) -> list[dict]:
    """Split one week of country totals into daily report events (Monday to Sunday)."""
    events = []
    for row in week.itertuples(index=False):
        cases = rng.multinomial(int(row.new_cases), [1 / 7] * 7)
        deaths = rng.multinomial(int(row.new_deaths), [1 / 7] * 7)
        for day in range(7):
            if cases[day] == 0 and deaths[day] == 0:
                continue
            events.append(
                {
                    "event_id": str(uuid.uuid4()),
                    "disease": row.disease,
                    "iso3": row.iso3,
                    "report_date": (row.week_start + timedelta(days=day)).isoformat(),
                    "new_cases": int(cases[day]),
                    "new_deaths": int(deaths[day]),
                    "source": "replay",
                }
            )
    events.sort(key=lambda e: e["report_date"])
    return events


def publish(producer: KafkaProducer, key: str, event: dict) -> None:
    """Send one event as compact JSON, keyed so a country's reports stay in order."""
    producer.send(TOPIC, key=key.encode(), value=json.dumps(event, separators=(",", ":")).encode())


def connect(retries: int = 30) -> KafkaProducer:
    for attempt in range(1, retries + 1):
        try:
            return KafkaProducer(bootstrap_servers=BOOTSTRAP, linger_ms=50)
        except KafkaError:          # broker not accepting connections yet
            log.info("waiting for Kafka at %s (%d/%d)", BOOTSTRAP, attempt, retries)
            time.sleep(2)
    raise RuntimeError(f"Kafka not reachable at {BOOTSTRAP}")


def events_already_in_topic() -> int:
    """Number of events the topic already holds (0 for a new or missing topic)."""
    consumer = KafkaConsumer(bootstrap_servers=BOOTSTRAP)
    try:
        partitions = consumer.partitions_for_topic(TOPIC) or set()
        offsets = consumer.end_offsets([TopicPartition(TOPIC, p) for p in partitions]) if partitions else {}
        return sum(offsets.values())
    finally:
        consumer.close()


def reset_stream_tables() -> None:
    """Clear what an earlier replay wrote, so the dashboard shows this one building up from zero."""
    engine = create_engine(DATABASE_URL)
    with engine.begin() as conn:
        conn.execute(text("TRUNCATE stream_weekly_counts, stream_alerts"))
    engine.dispose()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s", datefmt="%H:%M:%S")
    logging.getLogger("kafka").setLevel(logging.ERROR)      # the client is chatty about connection details
    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)

    reports = load_reports()
    if reports.empty:
        raise SystemExit("no case reports to replay - run `python -m pipeline etl` first")
    weeks = sorted(reports["week_start"].unique())

    producer = connect()
    existing = events_already_in_topic()
    if existing:
        # Flink's watermark already sits at the end of that replay. A second pass over the same
        # dates would arrive late and be discarded, so leave the stream exactly as it is.
        log.info(
            "topic '%s' already holds %d events from an earlier replay - nothing to do "
            "(start from an empty broker, e.g. `docker compose down`, to replay again)",
            TOPIC, existing,
        )
        producer.close()
        return
    reset_stream_tables()
    log.info(
        "replaying %d weeks (%s -> %s), %d country-weeks, at %.2f weeks/second into '%s'",
        len(weeks), weeks[0], weeks[-1], len(reports), WEEKS_PER_SECOND, TOPIC,
    )
    rng = np.random.default_rng(SEED)
    sent = 0
    for i, (week_start, week) in enumerate(reports.groupby("week_start", sort=True), start=1):
        if not _running:
            break
        t0 = time.monotonic()
        for event in daily_events(week, rng):
            publish(producer, f"{event['disease']}:{event['iso3']}", event)
            sent += 1
        producer.flush()
        if i % 10 == 0 or i == len(weeks):
            log.info("week %s (%d/%d) - %d events sent", week_start, i, len(weeks), sent)
        time.sleep(max(0.0, 1.0 / WEEKS_PER_SECOND - (time.monotonic() - t0)))

    if not _running:
        # Interrupted (SIGTERM): stop here. Publishing the end marker now would push Flink's
        # watermark past every event a later replay sends, and they would all be dropped as late.
        producer.flush()
        producer.close()
        log.info("replay interrupted after %d events", sent)
        return

    # one far-future marker advances Flink's watermark so the final windows close
    marker = {
        "event_id": str(uuid.uuid4()),
        "disease": "_marker",
        "iso3": "ZZZ",
        "report_date": (weeks[-1] + timedelta(days=60)).isoformat(),
        "new_cases": 0,
        "new_deaths": 0,
        "source": "replay",
    }
    publish(producer, "_marker", marker)
    producer.flush()
    producer.close()
    log.info("replay finished: %d events", sent)


if __name__ == "__main__":
    main()
