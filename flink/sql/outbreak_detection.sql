-- Real-time outbreak detection (Apache Flink SQL, streaming mode)
--
--   Kafka topic of case-report events
--     -> event-time tumbling windows: weekly cases per disease and country
--     -> rolling baseline over the previous 8 weeks, z-score of the current week
--     -> PostgreSQL: stream_weekly_counts (every window) and stream_alerts (anomalies)
--
-- ${...} placeholders are filled in by submit.sh.
-- Note: the SQL client ends a statement at the first semicolon and treats the rest of that line
-- as the start of the next one, so no comment may follow a semicolon on the same line.

SET 'pipeline.name' = 'outbreak-detection';
SET 'execution.runtime-mode' = 'streaming';
SET 'parallelism.default' = '1';
SET 'table.exec.source.idle-timeout' = '10 s';
SET 'execution.checkpointing.interval' = '30 s';

-- ------------------------------------------------------------------ source
CREATE TABLE case_events (
    event_id     STRING,
    disease      STRING,
    iso3         STRING,
    report_date  STRING,
    new_cases    INT,
    new_deaths   INT,
    -- Event time, moved forward three days so that an ISO week (Monday to Sunday) coincides
    -- with one of Flink's epoch-aligned 7-day windows (the epoch began on a Thursday).
    --
    -- The obvious alternative, TUMBLE(..., INTERVAL '7' DAY, INTERVAL '4' DAY), loses data in
    -- Flink 1.20: the window operator buffers rows in memory and only moves them into state when
    -- the watermark crosses an epoch-aligned boundary, ignoring the offset. A watermark that falls
    -- between the offset boundary and the epoch one marks the window as fired while its rows are
    -- still buffered, so no timer is registered and the window is never emitted. Replaying the
    -- same topic dropped 3 to 5 whole weeks out of 192 on every run, with no late-record metric.
    week_clock   AS TO_TIMESTAMP(report_date, 'yyyy-MM-dd') + INTERVAL '3' DAY,
    -- reports for a given day may arrive up to a week late
    WATERMARK FOR week_clock AS week_clock - INTERVAL '7' DAY
) WITH (
    'connector' = 'kafka',
    'topic' = '${KAFKA_TOPIC}',
    'properties.bootstrap.servers' = '${KAFKA_BOOTSTRAP_SERVERS}',
    'properties.group.id' = 'flink-outbreak-detection',
    'scan.startup.mode' = 'earliest-offset',
    'format' = 'json',
    'json.ignore-parse-errors' = 'true'
);

-- ------------------------------------------------------------------- sinks
CREATE TABLE weekly_counts_sink (
    disease       STRING,
    iso3          STRING,
    window_start  TIMESTAMP(3),
    window_end    TIMESTAMP(3),
    cases         BIGINT,
    deaths        BIGINT,
    reports       BIGINT,
    PRIMARY KEY (disease, iso3, window_start) NOT ENFORCED
) WITH (
    'connector' = 'jdbc',
    'url' = '${JDBC_URL}',
    'table-name' = 'stream_weekly_counts',
    'username' = '${JDBC_USER}',
    'password' = '${JDBC_PASSWORD}',
    'sink.buffer-flush.interval' = '1 s',
    'sink.buffer-flush.max-rows' = '500'
);

CREATE TABLE alerts_sink (
    disease        STRING,
    iso3           STRING,
    window_start   TIMESTAMP(3),
    window_end     TIMESTAMP(3),
    cases          BIGINT,
    baseline_mean  DOUBLE,
    baseline_std   DOUBLE,
    z_score        DOUBLE,
    severity       STRING,
    PRIMARY KEY (disease, iso3, window_start) NOT ENFORCED
) WITH (
    'connector' = 'jdbc',
    'url' = '${JDBC_URL}',
    'table-name' = 'stream_alerts',
    'username' = '${JDBC_USER}',
    'password' = '${JDBC_PASSWORD}',
    'sink.buffer-flush.interval' = '1 s',
    'sink.buffer-flush.max-rows' = '100'
);

-- ------------------------------------------------------------- weekly windows
-- 7-day tumbling windows on the shifted clock, which makes each window one ISO week.
CREATE TEMPORARY VIEW weekly_shifted AS
SELECT
    disease,
    iso3,
    window_start,
    window_end,
    window_time,
    SUM(new_cases)   AS cases,
    SUM(new_deaths)  AS deaths,
    COUNT(*)         AS reports
FROM TABLE(
    TUMBLE(TABLE case_events, DESCRIPTOR(week_clock), INTERVAL '7' DAY)
)
WHERE disease <> '_marker'
GROUP BY disease, iso3, window_start, window_end, window_time;

-- Back to calendar time: window_start is the Monday of the week, window_end the next Monday.
-- window_time stays on the shifted clock. It is only used to order the weeks below.
CREATE TEMPORARY VIEW weekly AS
SELECT
    disease,
    iso3,
    window_start - INTERVAL '3' DAY AS window_start,
    window_end - INTERVAL '3' DAY   AS window_end,
    window_time,
    cases,
    deaths,
    reports
FROM weekly_shifted;

-- ---------------------------------------------------------- rolling baseline
-- Streaming OVER windows must end at the current row, so the sums include it.
-- The current week is subtracted again below to get a baseline of previous weeks only.
CREATE TEMPORARY VIEW with_history AS
SELECT
    disease,
    iso3,
    window_start,
    window_end,
    cases,
    COUNT(*)                                         OVER w AS n,
    SUM(CAST(cases AS DOUBLE))                       OVER w AS sum_x,
    SUM(CAST(cases AS DOUBLE) * CAST(cases AS DOUBLE)) OVER w AS sum_xx
FROM weekly
WINDOW w AS (
    PARTITION BY disease, iso3
    ORDER BY window_time
    ROWS BETWEEN 8 PRECEDING AND CURRENT ROW
);

CREATE TEMPORARY VIEW scored AS
SELECT
    disease,
    iso3,
    window_start,
    window_end,
    cases,
    n - 1 AS baseline_weeks,
    (sum_x - cases) / (n - 1) AS baseline_mean,
    SQRT(GREATEST(
        ((sum_xx - CAST(cases AS DOUBLE) * cases) - (sum_x - cases) * (sum_x - cases) / (n - 1)) / (n - 2),
        0.0
    )) AS baseline_std
FROM with_history
-- at least six previous weeks of history
WHERE n >= 7;

-- --------------------------------------------------------------------- alerts
-- z-score against the previous weeks. The square-root floor is the Poisson noise
-- level, so small counts need a proportionally larger jump to raise an alert.
CREATE TEMPORARY VIEW z_scored AS
SELECT
    disease,
    iso3,
    window_start,
    window_end,
    cases,
    baseline_mean,
    baseline_std,
    (cases - baseline_mean) / GREATEST(baseline_std, SQRT(baseline_mean), 1.0) AS z_score
FROM scored;

-- (Defined as a view because the SQL client mistakes a CASE ... END inside a
--  statement set for the end of the set.)
CREATE TEMPORARY VIEW alerts AS
SELECT
    disease,
    iso3,
    window_start,
    window_end,
    cases,
    ROUND(baseline_mean, 2) AS baseline_mean,
    ROUND(baseline_std, 2)  AS baseline_std,
    ROUND(z_score, 2)       AS z_score,
    CASE
        WHEN z_score >= 8 THEN 'critical'
        WHEN z_score >= 5 THEN 'high'
        ELSE 'elevated'
    END AS severity
FROM z_scored
WHERE cases >= 20
  AND cases >= 2 * baseline_mean
  AND z_score >= 3;

-- ---------------------------------------------------------------------- run
-- Both inserts run as one job sharing the Kafka source and the windowing.
EXECUTE STATEMENT SET
BEGIN
INSERT INTO weekly_counts_sink
SELECT disease, iso3, window_start, window_end, cases, deaths, reports
FROM weekly;
INSERT INTO alerts_sink
SELECT disease, iso3, window_start, window_end, cases, baseline_mean, baseline_std, z_score, severity
FROM alerts;
END;
