-- Does the stream agree with the batch tables?
--
-- The Flink job and the batch ETL count the same case reports by two independent routes, so
-- after a full replay every weekly total written by Flink must equal the one in case_reports.
-- "missing" and "partial" must both be 0.
--
--   docker compose exec -T postgres psql -U surveillance -d disease_surveillance -f - < flink/sql/reconcile.sql
--
-- Set replay_start to the REPLAY_START the producer was run with.
\set replay_start '2023-01-02'

WITH batch AS (
    SELECT disease, week_start, sum(new_cases) AS cases
    FROM case_reports
    WHERE reported AND week_start >= :'replay_start'
    GROUP BY disease, week_start
),
stream AS (
    SELECT disease, window_start::date AS week_start, sum(cases) AS cases
    FROM stream_weekly_counts
    GROUP BY disease, window_start
)
SELECT
    b.disease,
    count(*)                                        AS weeks,
    count(*) FILTER (WHERE s.cases = b.cases)       AS exact,
    count(*) FILTER (WHERE s.cases IS NULL)         AS missing,
    count(*) FILTER (WHERE s.cases <> b.cases)      AS partial
FROM batch b
LEFT JOIN stream s USING (disease, week_start)
GROUP BY b.disease
ORDER BY b.disease;
