-- ============================================================
-- ShopStream Data Warehouse — PostgreSQL schema
-- DB: shopstream_dwh
-- ============================================================

-- ────────────────────────────────────────────────────────────
-- Dimension tables
-- ────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS dim_date (
    dt              DATE        PRIMARY KEY,
    year            SMALLINT    NOT NULL,
    month           SMALLINT    NOT NULL,
    day             SMALLINT    NOT NULL,
    day_of_week     SMALLINT    NOT NULL,   -- 0=Mon … 6=Sun
    is_weekend      BOOLEAN     NOT NULL,
    week_of_year    SMALLINT    NOT NULL
);

CREATE TABLE IF NOT EXISTS dim_country (
    country_code    CHAR(2)     PRIMARY KEY,   -- ISO 3166 alpha-2
    country_name    VARCHAR(100)
);

CREATE TABLE IF NOT EXISTS dim_device (
    device_type     VARCHAR(20) PRIMARY KEY    -- mobile | desktop | tablet
);

-- ────────────────────────────────────────────────────────────
-- Fact tables (todas con dt como clave de partición lógica)
-- ────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS fact_top_pages (
    id                  BIGSERIAL   PRIMARY KEY,
    dt                  DATE        NOT NULL REFERENCES dim_date(dt),
    page_url            TEXT        NOT NULL,
    page_type           VARCHAR(50),
    views               INTEGER     NOT NULL CHECK (views > 0),
    avg_time_on_page    NUMERIC(10,2),
    p95_time_on_page    NUMERIC(10,2),
    loaded_at           TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_top_pages_dt ON fact_top_pages(dt);
CREATE INDEX IF NOT EXISTS idx_top_pages_dt_url ON fact_top_pages(dt, page_url);

CREATE TABLE IF NOT EXISTS fact_bounce_rate (
    id                  BIGSERIAL   PRIMARY KEY,
    dt                  DATE        NOT NULL REFERENCES dim_date(dt),
    landing_page_type   VARCHAR(50) NOT NULL,
    total_sessions      INTEGER     NOT NULL CHECK (total_sessions > 0),
    bounce_sessions     INTEGER     NOT NULL CHECK (bounce_sessions >= 0),
    bounce_rate         NUMERIC(6,4) NOT NULL CHECK (bounce_rate BETWEEN 0 AND 1),
    loaded_at           TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_bounce_rate_dt ON fact_bounce_rate(dt);
CREATE UNIQUE INDEX IF NOT EXISTS uq_bounce_rate_dt_type ON fact_bounce_rate(dt, landing_page_type);

CREATE TABLE IF NOT EXISTS fact_conversion_funnel (
    id                              BIGSERIAL   PRIMARY KEY,
    dt                              DATE        NOT NULL REFERENCES dim_date(dt),
    stage                           VARCHAR(30) NOT NULL,
    sessions                        INTEGER     NOT NULL CHECK (sessions >= 0),
    conversion_rate_from_previous   NUMERIC(6,4),
    conversion_rate_overall         NUMERIC(6,4),
    loaded_at                       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_funnel_dt ON fact_conversion_funnel(dt);
CREATE UNIQUE INDEX IF NOT EXISTS uq_funnel_dt_stage ON fact_conversion_funnel(dt, stage);

CREATE TABLE IF NOT EXISTS fact_product_gap (
    id          BIGSERIAL   PRIMARY KEY,
    dt          DATE        NOT NULL REFERENCES dim_date(dt),
    product_id  VARCHAR(50) NOT NULL,
    category    VARCHAR(100),
    views       INTEGER     NOT NULL CHECK (views >= 0),
    cart_adds   INTEGER     NOT NULL CHECK (cart_adds >= 0),
    conversion  NUMERIC(6,4),
    gap_score   NUMERIC(6,4),
    loaded_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_product_gap_dt ON fact_product_gap(dt);
CREATE INDEX IF NOT EXISTS idx_product_gap_dt_pid ON fact_product_gap(dt, product_id);

CREATE TABLE IF NOT EXISTS fact_nav_paths (
    id              BIGSERIAL   PRIMARY KEY,
    dt              DATE        NOT NULL REFERENCES dim_date(dt),
    path            TEXT        NOT NULL,
    sessions        INTEGER     NOT NULL CHECK (sessions > 0),
    avg_path_length NUMERIC(5,2),
    loaded_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_nav_paths_dt ON fact_nav_paths(dt);

CREATE TABLE IF NOT EXISTS fact_device_country (
    id                  BIGSERIAL   PRIMARY KEY,
    dt                  DATE        NOT NULL REFERENCES dim_date(dt),
    device_type         VARCHAR(20) NOT NULL,
    country             CHAR(2)     NOT NULL,
    page_views          INTEGER     NOT NULL CHECK (page_views >= 0),
    avg_time_on_page    NUMERIC(10,2),
    p95_time_on_page    NUMERIC(10,2),
    unique_sessions     INTEGER,
    loaded_at           TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_device_country_dt ON fact_device_country(dt);
CREATE UNIQUE INDEX IF NOT EXISTS uq_device_country_dt_dev_ctry
    ON fact_device_country(dt, device_type, country);

CREATE TABLE IF NOT EXISTS fact_anomalies (
    id                          BIGSERIAL   PRIMARY KEY,
    dt                          DATE        NOT NULL REFERENCES dim_date(dt),
    session_id                  VARCHAR(50) NOT NULL,
    user_id                     VARCHAR(50),
    total_events                INTEGER,
    session_duration_seconds    NUMERIC(12,2),
    unique_pages                INTEGER,
    events_per_minute           NUMERIC(10,4),
    z_total_events              NUMERIC(8,3),
    z_session_duration_seconds  NUMERIC(8,3),
    z_unique_pages              NUMERIC(8,3),
    z_events_per_minute         NUMERIC(8,3),
    total_flags                 SMALLINT,
    anomaly_type                VARCHAR(30),
    loaded_at                   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_anomalies_dt ON fact_anomalies(dt);
CREATE INDEX IF NOT EXISTS idx_anomalies_dt_type ON fact_anomalies(dt, anomaly_type);

-- ────────────────────────────────────────────────────────────
-- Seed dim_device con los valores conocidos
-- ────────────────────────────────────────────────────────────
INSERT INTO dim_device(device_type)
VALUES ('mobile'), ('desktop'), ('tablet')
ON CONFLICT DO NOTHING;
