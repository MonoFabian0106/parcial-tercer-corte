"""Tests for the Flask API — Flask test client + mocked DB session."""
from __future__ import annotations

from contextlib import contextmanager
from types import SimpleNamespace
from typing import Any

import pytest

from api import app as app_module


class _FakeResultProxy:
    """Mimics SQLAlchemy's Result enough for our endpoints (.all() and .one())."""

    def __init__(self, rows: list[Any]):
        self._rows = rows

    def all(self) -> list[Any]:
        return list(self._rows)

    def one(self):
        if len(self._rows) != 1:
            raise AssertionError(f"expected exactly one row, got {len(self._rows)}")
        return self._rows[0]


class _FakeSession:
    """Returns a queue of canned results, one per execute() call (FIFO)."""

    def __init__(self, results: list[list[Any]]):
        self._results = list(results)
        self.calls: list[tuple[str, dict]] = []

    def execute(self, stmt, params=None):
        text = getattr(stmt, "text", str(stmt))
        self.calls.append((text, dict(params or {})))
        if not self._results:
            raise AssertionError("FakeSession ran out of canned results")
        return _FakeResultProxy(self._results.pop(0))

    def close(self):
        pass


@pytest.fixture
def client():
    return app_module.app.test_client()


@pytest.fixture
def patch_db(monkeypatch):
    """Returns a helper that installs a fake session into every endpoint's get_session()."""

    def _install(results_per_endpoint: list[list[Any]]) -> _FakeSession:
        fake = _FakeSession(results_per_endpoint)

        @contextmanager
        def fake_get_session():
            yield fake

        monkeypatch.setattr("api.endpoints.pages.get_session", fake_get_session)
        monkeypatch.setattr("api.endpoints.sessions.get_session", fake_get_session)
        monkeypatch.setattr("api.endpoints.anomalies.get_session", fake_get_session)
        return fake

    return _install


# ────────────────────────────────────────────────────────────────────
# /health
# ────────────────────────────────────────────────────────────────────


def test_health_returns_ok(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json == {"status": "ok", "service": "shopstream-api"}


def test_health_has_cors_header(client):
    response = client.get("/health")
    assert response.headers["Access-Control-Allow-Origin"] == "*"


def test_unknown_path_returns_404(client):
    response = client.get("/nope")
    assert response.status_code == 404
    assert response.json == {"error": "not found"}


# ────────────────────────────────────────────────────────────────────
# /pages/top
# ────────────────────────────────────────────────────────────────────


def test_pages_top_time_on_page_ok(client, patch_db):
    patch_db([
        [
            SimpleNamespace(
                page_url="/p/abc",
                page_type="product",
                views=120,
                avg_time_on_page=87.5,
                p95_time_on_page=200.0,
            ),
            SimpleNamespace(
                page_url="/cat/shoes",
                page_type="category",
                views=300,
                avg_time_on_page=42.0,
                p95_time_on_page=140.0,
            ),
        ],
    ])

    response = client.get("/pages/top?metric=time_on_page&date=2026-05-22&limit=2")
    assert response.status_code == 200
    body = response.json
    assert body["metric"] == "time_on_page"
    assert body["date"] == "2026-05-22"
    assert body["limit"] == 2
    assert len(body["results"]) == 2
    assert body["results"][0]["page_url"] == "/p/abc"
    assert body["results"][0]["avg_time_on_page"] == 87.5


def test_pages_top_bounce_rate_ok(client, patch_db):
    patch_db([
        [
            SimpleNamespace(
                landing_page_type="home",
                total_sessions=1000,
                bounce_sessions=420,
                bounce_rate=0.42,
            ),
        ],
    ])

    response = client.get("/pages/top?metric=bounce_rate&date=2026-05-22")
    assert response.status_code == 200
    body = response.json
    assert body["metric"] == "bounce_rate"
    assert body["limit"] == 10  # default
    assert body["results"][0]["bounce_rate"] == 0.42


def test_pages_top_invalid_metric_returns_400(client):
    response = client.get("/pages/top?metric=banana&date=2026-05-22")
    assert response.status_code == 400
    assert "metric" in response.json["error"]


def test_pages_top_missing_date_returns_400(client):
    response = client.get("/pages/top?metric=time_on_page")
    assert response.status_code == 400


def test_pages_top_invalid_date_returns_400(client):
    response = client.get("/pages/top?metric=time_on_page&date=2026/05/22")
    assert response.status_code == 400


def test_pages_top_limit_out_of_range_returns_400(client):
    response = client.get("/pages/top?metric=time_on_page&date=2026-05-22&limit=9999")
    assert response.status_code == 400


def test_pages_top_no_data_returns_404(client, patch_db):
    patch_db([[]])
    response = client.get("/pages/top?metric=time_on_page&date=2026-05-22")
    assert response.status_code == 404


# ────────────────────────────────────────────────────────────────────
# /sessions/summary
# ────────────────────────────────────────────────────────────────────


def test_sessions_summary_ok(client, patch_db):
    patch_db([
        [SimpleNamespace(total_sessions=500, total_page_views=2000, avg_time_on_page=33.3, segments=4)],
        [SimpleNamespace(overall_bounce_rate=0.25)],
    ])
    response = client.get("/sessions/summary?date=2026-05-22&country=MX&device=mobile")
    assert response.status_code == 200
    body = response.json
    assert body["country"] == "MX"
    assert body["device"] == "mobile"
    assert body["total_sessions"] == 500
    assert body["overall_bounce_rate"] == 0.25


def test_sessions_summary_only_date(client, patch_db):
    patch_db([
        [SimpleNamespace(total_sessions=1200, total_page_views=4000, avg_time_on_page=40.0, segments=12)],
        [SimpleNamespace(overall_bounce_rate=0.3)],
    ])
    response = client.get("/sessions/summary?date=2026-05-22")
    assert response.status_code == 200
    assert response.json["country"] is None
    assert response.json["device"] is None


def test_sessions_summary_invalid_country_returns_400(client):
    response = client.get("/sessions/summary?date=2026-05-22&country=MEX")
    assert response.status_code == 400


def test_sessions_summary_invalid_device_returns_400(client):
    response = client.get("/sessions/summary?date=2026-05-22&device=smarttv")
    assert response.status_code == 400


def test_sessions_summary_no_data_returns_404(client, patch_db):
    patch_db([
        [SimpleNamespace(total_sessions=0, total_page_views=0, avg_time_on_page=None, segments=0)],
    ])
    response = client.get("/sessions/summary?date=2026-05-22&country=ZZ")
    assert response.status_code == 404


# ────────────────────────────────────────────────────────────────────
# /anomalies
# ────────────────────────────────────────────────────────────────────


def test_anomalies_ok(client, patch_db):
    patch_db([
        [
            SimpleNamespace(
                session_id="s-1",
                user_id="u-1",
                total_events=350,
                session_duration_seconds=120.5,
                unique_pages=2,
                events_per_minute=175.0,
                z_total_events=4.2,
                z_session_duration_seconds=-3.1,
                z_unique_pages=0.0,
                z_events_per_minute=5.8,
                total_flags=3,
                anomaly_type="bot_like",
            ),
        ],
    ])
    response = client.get("/anomalies?date=2026-05-22")
    assert response.status_code == 200
    body = response.json
    assert body["count"] == 1
    assert body["results"][0]["anomaly_type"] == "bot_like"
    assert body["results"][0]["z_score"]["events_per_minute"] == 5.8


def test_anomalies_missing_date_returns_400(client):
    response = client.get("/anomalies")
    assert response.status_code == 400


def test_anomalies_no_data_returns_404(client, patch_db):
    patch_db([[]])
    response = client.get("/anomalies?date=2026-05-22")
    assert response.status_code == 404


# ────────────────────────────────────────────────────────────────────
# validators
# ────────────────────────────────────────────────────────────────────


def test_validators_country_normalizes_case():
    from api.validators import parse_country

    assert parse_country("mx") == "MX"


def test_validators_int_default():
    from api.validators import parse_int

    assert parse_int(None, field="limit", default=10) == 10


def test_validators_int_invalid_raises():
    from api.validators import ValidationError, parse_int

    with pytest.raises(ValidationError):
        parse_int("abc", field="limit", default=10)
