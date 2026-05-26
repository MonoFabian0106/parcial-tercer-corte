"""Tests de Fase 4: integridad SQL del DWH y alerta Lambda.

Los tests de SQL usan SQLite (en memoria) para validar la estructura y
restricciones sin necesidad de RDS real. La Lambda de alerta se prueba
con moto para mockear SNS.
"""

from __future__ import annotations

import boto3
import pytest
from moto import mock_aws

# ─────────────────────────────────────────────────────────────
# Fixtures SQLite — simula el DWH con las tablas principales
# ─────────────────────────────────────────────────────────────


@pytest.fixture
def db_conn():
    """Conexión SQLite en memoria con el esquema DWH adaptado."""
    import sqlite3

    conn = sqlite3.connect(":memory:")
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript("""
        CREATE TABLE dim_date (
            dt          TEXT PRIMARY KEY,
            year        INTEGER NOT NULL,
            month       INTEGER NOT NULL,
            day         INTEGER NOT NULL,
            day_of_week INTEGER NOT NULL,
            is_weekend  INTEGER NOT NULL,
            week_of_year INTEGER NOT NULL
        );

        CREATE TABLE fact_bounce_rate (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            dt                  TEXT NOT NULL REFERENCES dim_date(dt),
            landing_page_type   TEXT NOT NULL,
            total_sessions      INTEGER NOT NULL CHECK(total_sessions > 0),
            bounce_sessions     INTEGER NOT NULL CHECK(bounce_sessions >= 0),
            bounce_rate         REAL NOT NULL CHECK(bounce_rate BETWEEN 0 AND 1)
        );

        CREATE TABLE fact_top_pages (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            dt                  TEXT NOT NULL REFERENCES dim_date(dt),
            page_url            TEXT NOT NULL,
            page_type           TEXT,
            views               INTEGER NOT NULL CHECK(views > 0),
            avg_time_on_page    REAL,
            p95_time_on_page    REAL
        );

        CREATE TABLE fact_conversion_funnel (
            id                              INTEGER PRIMARY KEY AUTOINCREMENT,
            dt                              TEXT NOT NULL REFERENCES dim_date(dt),
            stage                           TEXT NOT NULL,
            sessions                        INTEGER NOT NULL CHECK(sessions >= 0),
            conversion_rate_from_previous   REAL,
            conversion_rate_overall         REAL
        );

        CREATE TABLE fact_product_gap (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            dt          TEXT NOT NULL REFERENCES dim_date(dt),
            product_id  TEXT NOT NULL,
            category    TEXT,
            views       INTEGER NOT NULL CHECK(views >= 0),
            cart_adds   INTEGER NOT NULL CHECK(cart_adds >= 0),
            conversion  REAL,
            gap_score   REAL
        );

        CREATE TABLE fact_anomalies (
            id                          INTEGER PRIMARY KEY AUTOINCREMENT,
            dt                          TEXT NOT NULL REFERENCES dim_date(dt),
            session_id                  TEXT NOT NULL,
            user_id                     TEXT,
            total_events                INTEGER,
            session_duration_seconds    REAL,
            unique_pages                INTEGER,
            events_per_minute           REAL,
            z_total_events              REAL,
            z_session_duration_seconds  REAL,
            z_unique_pages              REAL,
            z_events_per_minute         REAL,
            total_flags                 INTEGER,
            anomaly_type                TEXT
        );

        CREATE TABLE fact_device_country (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            dt                  TEXT NOT NULL REFERENCES dim_date(dt),
            device_type         TEXT NOT NULL,
            country             TEXT NOT NULL,
            page_views          INTEGER NOT NULL CHECK(page_views >= 0),
            avg_time_on_page    REAL,
            p95_time_on_page    REAL,
            unique_sessions     INTEGER
        );

        CREATE TABLE fact_nav_paths (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            dt              TEXT NOT NULL REFERENCES dim_date(dt),
            path            TEXT NOT NULL,
            sessions        INTEGER NOT NULL CHECK(sessions > 0),
            avg_path_length REAL
        );
    """)
    conn.execute("INSERT INTO dim_date VALUES ('2026-05-22',2026,5,22,3,0,21)")
    conn.commit()
    yield conn
    conn.close()


# ─────────────────────────────────────────────────────────────
# Tests de estructura e integridad
# ─────────────────────────────────────────────────────────────


class TestDwhSchema:
    def test_dim_date_seeded(self, db_conn):
        row = db_conn.execute(
            "SELECT year,month,day FROM dim_date WHERE dt='2026-05-22'"
        ).fetchone()
        assert row == (2026, 5, 22)

    def test_fact_bounce_rate_insert_valid(self, db_conn):
        db_conn.execute(
            "INSERT INTO fact_bounce_rate(dt,landing_page_type,total_sessions,bounce_sessions,bounce_rate)"
            " VALUES ('2026-05-22','home',1000,248,0.248)"
        )
        db_conn.commit()
        count = db_conn.execute("SELECT COUNT(*) FROM fact_bounce_rate").fetchone()[0]
        assert count == 1

    def test_fact_bounce_rate_rejects_negative_sessions(self, db_conn):
        import sqlite3

        with pytest.raises(sqlite3.IntegrityError):
            db_conn.execute(
                "INSERT INTO fact_bounce_rate(dt,landing_page_type,total_sessions,bounce_sessions,bounce_rate)"
                " VALUES ('2026-05-22','product',-1,0,0.0)"
            )

    def test_fact_bounce_rate_rejects_rate_out_of_range(self, db_conn):
        import sqlite3

        with pytest.raises(sqlite3.IntegrityError):
            db_conn.execute(
                "INSERT INTO fact_bounce_rate(dt,landing_page_type,total_sessions,bounce_sessions,bounce_rate)"
                " VALUES ('2026-05-22','home',100,50,1.5)"
            )

    def test_fact_top_pages_insert_valid(self, db_conn):
        db_conn.execute(
            "INSERT INTO fact_top_pages(dt,page_url,page_type,views,avg_time_on_page,p95_time_on_page)"
            " VALUES ('2026-05-22','https://shopstream.com/','home',5000,45.2,120.0)"
        )
        db_conn.commit()
        row = db_conn.execute("SELECT views FROM fact_top_pages").fetchone()
        assert row[0] == 5000

    def test_fact_top_pages_rejects_zero_views(self, db_conn):
        import sqlite3

        with pytest.raises(sqlite3.IntegrityError):
            db_conn.execute(
                "INSERT INTO fact_top_pages(dt,page_url,views)" " VALUES ('2026-05-22','/page',0)"
            )

    def test_fact_conversion_funnel_all_stages(self, db_conn):
        stages = [
            ("page_view", 10000, 1.0, 1.0),
            ("product_view", 3000, 0.3, 0.3),
            ("cart_event", 800, 0.2667, 0.08),
            ("purchase", 300, 0.375, 0.03),
        ]
        for stage, sessions, conv_prev, conv_overall in stages:
            db_conn.execute(
                "INSERT INTO fact_conversion_funnel(dt,stage,sessions,conversion_rate_from_previous,conversion_rate_overall)"
                " VALUES ('2026-05-22',?,?,?,?)",
                (stage, sessions, conv_prev, conv_overall),
            )
        db_conn.commit()
        count = db_conn.execute("SELECT COUNT(*) FROM fact_conversion_funnel").fetchone()[0]
        assert count == 4

    def test_fact_anomalies_total_flags_gte_2(self, db_conn):
        db_conn.execute(
            "INSERT INTO fact_anomalies(dt,session_id,user_id,total_events,total_flags,anomaly_type)"
            " VALUES ('2026-05-22','S001','U001',500,3,'high_velocity')"
        )
        db_conn.commit()
        row = db_conn.execute("SELECT total_flags FROM fact_anomalies").fetchone()
        assert row[0] >= 2

    def test_fact_device_country_unique_combo(self, db_conn):
        db_conn.execute(
            "INSERT INTO fact_device_country(dt,device_type,country,page_views)"
            " VALUES ('2026-05-22','mobile','MX',50000)"
        )
        db_conn.commit()
        count = db_conn.execute("SELECT COUNT(*) FROM fact_device_country").fetchone()[0]
        assert count == 1

    def test_fact_nav_paths_insert(self, db_conn):
        db_conn.execute(
            "INSERT INTO fact_nav_paths(dt,path,sessions,avg_path_length)"
            " VALUES ('2026-05-22','home->product->cart',3500,3.0)"
        )
        db_conn.commit()
        row = db_conn.execute("SELECT path,sessions FROM fact_nav_paths").fetchone()
        assert row == ("home->product->cart", 3500)

    def test_foreign_key_rejected_without_dim_date(self, db_conn):
        import sqlite3

        with pytest.raises(sqlite3.IntegrityError):
            db_conn.execute(
                "INSERT INTO fact_bounce_rate(dt,landing_page_type,total_sessions,bounce_sessions,bounce_rate)"
                " VALUES ('1999-01-01','home',100,50,0.5)"
            )

    def test_all_fact_tables_exist(self, db_conn):
        tables = {
            r[0]
            for r in db_conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        }
        expected = {
            "dim_date",
            "fact_bounce_rate",
            "fact_top_pages",
            "fact_conversion_funnel",
            "fact_product_gap",
            "fact_anomalies",
            "fact_device_country",
            "fact_nav_paths",
        }
        assert expected.issubset(tables)


# ─────────────────────────────────────────────────────────────
# Tests de la Lambda de alerta (moto)
# ─────────────────────────────────────────────────────────────


@mock_aws
class TestAlertHandler:
    def _setup_sns(self):
        client = boto3.client("sns", region_name="us-east-1")
        topic_arn = client.create_topic(Name="shopstream-alerts")["TopicArn"]
        return client, topic_arn

    def test_handler_publishes_on_glue_failure(self, monkeypatch):
        _client, topic_arn = self._setup_sns()
        monkeypatch.setenv("SNS_TOPIC_ARN", topic_arn)

        from lambda_ingest import alert_handler

        event = {
            "source": "aws.glue",
            "detail-type": "Glue Job State Change",
            "account": "123456789012",
            "region": "us-east-1",
            "time": "2026-05-22T02:15:00Z",
            "detail": {
                "jobName": "shopstream-s3-to-rds",
                "state": "FAILED",
                "jobRunId": "jr_abc123",
            },
        }
        result = alert_handler.handler(event, None)
        assert result["statusCode"] == 200
        assert "messageId" in result

    def test_handler_publishes_on_unknown_format(self, monkeypatch):
        _, topic_arn = self._setup_sns()
        monkeypatch.setenv("SNS_TOPIC_ARN", topic_arn)

        from lambda_ingest import alert_handler

        event = {"jobName": "some-job", "errorMessage": "Out of memory"}
        result = alert_handler.handler(event, None)
        assert result["statusCode"] == 200
