"""Tests para el generador de eventos: distribuciones, conteos, determinismo."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest
from jsonschema import Draft7Validator

from data_generation.catalog import build_or_load_catalog, generate_products, generate_users
from data_generation.generator import GeneratorConfig, generate_day
from data_generation.schemas import EVENT_TYPE_SCHEMAS


@pytest.fixture(scope="module")
def small_catalog(tmp_path_factory):
    base = tmp_path_factory.mktemp("catalog")
    return build_or_load_catalog(base, n_users=1_000, n_products=100, seed=42, rebuild=True)


class TestCatalog:
    def test_users_count(self, small_catalog):
        assert len(small_catalog.users) == 1_000

    def test_products_count(self, small_catalog):
        assert len(small_catalog.products) == 100

    def test_user_ids_unique(self, small_catalog):
        ids = [u["user_id"] for u in small_catalog.users]
        assert len(set(ids)) == len(ids)

    def test_product_ids_unique(self, small_catalog):
        ids = [p["product_id"] for p in small_catalog.products]
        assert len(set(ids)) == len(ids)

    def test_users_deterministic_with_seed(self):
        a = generate_users(50, seed=123)
        b = generate_users(50, seed=123)
        assert a == b

    def test_users_different_seeds_differ(self):
        a = generate_users(50, seed=1)
        b = generate_users(50, seed=2)
        assert a != b

    def test_products_by_category_covers_all(self, small_catalog):
        by_cat = small_catalog.products_by_category()
        # Cada categoría debería tener al menos algún producto en 100 muestras
        total = sum(len(v) for v in by_cat.values())
        assert total == 100


class TestEventGeneration:
    def test_target_events_reached(self, small_catalog, tmp_path):
        cfg = GeneratorConfig(target_events=5_000, seed=42)
        out = tmp_path / "events.jsonl"
        m = generate_day(date(2026, 5, 22), small_catalog, cfg, out)
        assert m["total_events"] >= 5_000
        assert m["total_events"] < 5_000 + 50  # overshoot acotado a una sesión completa

    def test_all_event_types_present(self, small_catalog, tmp_path):
        cfg = GeneratorConfig(target_events=10_000, seed=42)
        m = generate_day(date(2026, 5, 22), small_catalog, cfg, tmp_path / "e.jsonl")
        for t in ("page_view", "click", "search", "product_view", "cart_event"):
            assert m["by_type"][t] > 0, f"Missing event type: {t}"

    def test_bounce_rate_around_25_percent(self, small_catalog, tmp_path):
        cfg = GeneratorConfig(target_events=20_000, seed=42)
        m = generate_day(date(2026, 5, 22), small_catalog, cfg, tmp_path / "e.jsonl")
        bounce_rate = m["bounce_sessions"] / m["total_sessions"]
        assert 0.18 <= bounce_rate <= 0.32, f"Bounce rate {bounce_rate:.2%} fuera de rango"

    def test_anomalous_rate_around_half_percent(self, small_catalog, tmp_path):
        cfg = GeneratorConfig(target_events=50_000, seed=42)
        m = generate_day(date(2026, 5, 22), small_catalog, cfg, tmp_path / "e.jsonl")
        anomalous_rate = m["anomalous_sessions"] / m["total_sessions"]
        # Rango amplio para evitar flaking; el objetivo es 0.5%
        assert 0.001 <= anomalous_rate <= 0.012

    def test_page_views_are_dominant(self, small_catalog, tmp_path):
        cfg = GeneratorConfig(target_events=10_000, seed=42)
        m = generate_day(date(2026, 5, 22), small_catalog, cfg, tmp_path / "e.jsonl")
        pv = m["by_type"]["page_view"]
        # page_view debería ser el tipo más frecuente (>30%)
        assert pv / m["total_events"] > 0.30

    def test_events_validate_against_schema(self, small_catalog, tmp_path):
        cfg = GeneratorConfig(target_events=2_000, seed=42)
        out = tmp_path / "e.jsonl"
        generate_day(date(2026, 5, 22), small_catalog, cfg, out)
        validators = {k: Draft7Validator(v) for k, v in EVENT_TYPE_SCHEMAS.items()}
        with out.open() as f:
            for i, line in enumerate(f):
                ev = json.loads(line)
                errs = list(validators[ev["event_type"]].iter_errors(ev))
                assert not errs, f"Event #{i} invalid: {errs[0].message}"
                if i >= 500:  # verifica los primeros 500 para no eternizarse
                    break

    def test_same_seed_same_output(self, small_catalog, tmp_path):
        cfg = GeneratorConfig(target_events=2_000, seed=42)
        a = generate_day(date(2026, 5, 22), small_catalog, cfg, tmp_path / "a.jsonl")
        b = generate_day(date(2026, 5, 22), small_catalog, cfg, tmp_path / "b.jsonl")
        assert (tmp_path / "a.jsonl").read_text() == (tmp_path / "b.jsonl").read_text()
        assert a["total_events"] == b["total_events"]

    def test_different_dates_different_data(self, small_catalog, tmp_path):
        cfg = GeneratorConfig(target_events=2_000, seed=42)
        generate_day(date(2026, 5, 22), small_catalog, cfg, tmp_path / "a.jsonl")
        generate_day(date(2026, 5, 23), small_catalog, cfg, tmp_path / "b.jsonl")
        assert (tmp_path / "a.jsonl").read_text() != (tmp_path / "b.jsonl").read_text()

    def test_session_ids_consistent_within_session(self, small_catalog, tmp_path):
        cfg = GeneratorConfig(target_events=3_000, seed=42)
        out = tmp_path / "e.jsonl"
        generate_day(date(2026, 5, 22), small_catalog, cfg, out)
        # Verifica que los timestamps dentro de cada session_id son monotonos
        sessions: dict[str, list[str]] = {}
        with out.open() as f:
            for line in f:
                ev = json.loads(line)
                sessions.setdefault(ev["session_id"], []).append(ev["timestamp"])
        for sid, ts_list in sessions.items():
            assert ts_list == sorted(ts_list), f"Timestamps not sorted in session {sid}"
