-- Global Disease Surveillance & Outbreak Analytics Platform - PostgreSQL schema
-- Idempotent: safe to run on every start-up.

-- ------------------------------------------------------------------ reference
CREATE TABLE IF NOT EXISTS countries (
    iso3          char(3) PRIMARY KEY,
    iso2          char(2),
    name          text    NOT NULL,
    continent     text,
    un_region     text,
    subregion     text,
    who_region    text,
    population    bigint,
    lat           double precision,          -- label point
    lon           double precision,
    has_geometry  boolean NOT NULL DEFAULT false,
    geometry      jsonb                      -- simplified GeoJSON geometry for the web map
);

CREATE TABLE IF NOT EXISTS country_neighbours (
    iso3            char(3) NOT NULL REFERENCES countries (iso3) ON DELETE CASCADE,
    neighbour_iso3  char(3) NOT NULL REFERENCES countries (iso3) ON DELETE CASCADE,
    PRIMARY KEY (iso3, neighbour_iso3)
);

CREATE TABLE IF NOT EXISTS diseases (
    code          text PRIMARY KEY,
    name          text NOT NULL,
    pathogen      text,
    transmission  text,
    source_name   text NOT NULL,
    source_url    text NOT NULL,
    licence       text,
    first_week    date,
    last_week     date
);

-- ----------------------------------------------------------------------- facts
-- One row per disease, country and ISO week (week_start = Monday).
CREATE TABLE IF NOT EXISTS case_reports (
    disease     text    NOT NULL REFERENCES diseases (code),
    iso3        char(3) NOT NULL REFERENCES countries (iso3),
    week_start  date    NOT NULL,
    new_cases   integer NOT NULL DEFAULT 0 CHECK (new_cases >= 0),
    new_deaths  integer NOT NULL DEFAULT 0 CHECK (new_deaths >= 0),
    reported    boolean NOT NULL DEFAULT true,     -- false = the source had no figure for this week
    PRIMARY KEY (disease, iso3, week_start)
);
CREATE INDEX IF NOT EXISTS case_reports_week_idx ON case_reports (disease, week_start);
CREATE INDEX IF NOT EXISTS case_reports_country_idx ON case_reports (iso3, disease, week_start);

CREATE TABLE IF NOT EXISTS annual_indicators (
    indicator  text    NOT NULL,                   -- cholera_cases | measles_cases
    iso3       char(3) NOT NULL REFERENCES countries (iso3),
    year       integer NOT NULL,
    value      double precision NOT NULL,
    PRIMARY KEY (indicator, iso3, year)
);

-- ----------------------------------------------------------------------- model
CREATE TABLE IF NOT EXISTS model_runs (
    run_id              serial PRIMARY KEY,
    trained_at          timestamptz NOT NULL DEFAULT now(),
    algorithm           text NOT NULL,
    horizon_weeks       integer NOT NULL,
    train_end           date NOT NULL,
    params              jsonb NOT NULL,
    metrics             jsonb NOT NULL,
    feature_importance  jsonb NOT NULL,
    is_active           boolean NOT NULL DEFAULT false
);

CREATE TABLE IF NOT EXISTS risk_scores (
    run_id            integer NOT NULL REFERENCES model_runs (run_id) ON DELETE CASCADE,
    disease           text    NOT NULL REFERENCES diseases (code),
    iso3              char(3) NOT NULL REFERENCES countries (iso3),
    week_start        date    NOT NULL,
    risk_probability  real    NOT NULL,
    risk_level        text    NOT NULL CHECK (risk_level IN ('Low', 'Moderate', 'High', 'Critical')),
    cases_4w          integer NOT NULL,
    incidence_4w      real,                         -- cases per 100k over the last 4 weeks
    growth_4w         real,                         -- last 4 weeks / the 4 weeks before
    top_drivers       jsonb,                        -- largest SHAP contributions behind the score
    outcome           smallint,                     -- 1/0 once the following 4 weeks are known
    PRIMARY KEY (run_id, disease, iso3, week_start)
);
CREATE INDEX IF NOT EXISTS risk_scores_week_idx ON risk_scores (run_id, disease, week_start);

-- ---------------------------------------------------------------------- stream
-- Written by the Flink job (JDBC upsert sinks).
CREATE TABLE IF NOT EXISTS stream_weekly_counts (
    disease       text      NOT NULL,
    iso3          text      NOT NULL,
    window_start  timestamp NOT NULL,
    window_end    timestamp NOT NULL,
    cases         bigint    NOT NULL,
    deaths        bigint    NOT NULL,
    reports       bigint    NOT NULL,
    PRIMARY KEY (disease, iso3, window_start)
);

CREATE TABLE IF NOT EXISTS stream_alerts (
    disease        text      NOT NULL,
    iso3           text      NOT NULL,
    window_start   timestamp NOT NULL,
    window_end     timestamp NOT NULL,
    cases          bigint    NOT NULL,
    baseline_mean  double precision NOT NULL,
    baseline_std   double precision NOT NULL,
    z_score        double precision NOT NULL,
    severity       text      NOT NULL,
    detected_at    timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (disease, iso3, window_start)
);
CREATE INDEX IF NOT EXISTS stream_alerts_detected_idx ON stream_alerts (detected_at DESC);

CREATE TABLE IF NOT EXISTS etl_runs (
    run_id       serial PRIMARY KEY,
    started_at   timestamptz NOT NULL DEFAULT now(),
    finished_at  timestamptz,
    status       text NOT NULL DEFAULT 'running',
    rows_loaded  jsonb
);

-- ----------------------------------------------------------------------- views
CREATE OR REPLACE VIEW v_active_run AS
SELECT * FROM model_runs WHERE is_active ORDER BY run_id DESC LIMIT 1;

-- Weekly cases with population-normalised incidence.
CREATE OR REPLACE VIEW v_weekly_incidence AS
SELECT
    r.disease,
    r.iso3,
    c.name        AS country,
    c.who_region,
    c.continent,
    r.week_start,
    r.new_cases,
    r.new_deaths,
    r.reported,
    CASE WHEN c.population > 0 THEN r.new_cases * 100000.0 / c.population END AS incidence_per_100k
FROM case_reports r
JOIN countries c USING (iso3);

-- Global weekly totals per disease.
CREATE OR REPLACE VIEW v_global_weekly AS
SELECT
    disease,
    week_start,
    sum(new_cases)                               AS new_cases,
    sum(new_deaths)                              AS new_deaths,
    count(*) FILTER (WHERE new_cases > 0)        AS countries_reporting
FROM case_reports
GROUP BY disease, week_start;
