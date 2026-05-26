"""Tests del validador de eventos."""

from __future__ import annotations

import json

from lambda_ingest.validator import event_type_counter, validate_line

VALID_PAGE_VIEW = {
    "event_id": "Eabcdef0123456789",
    "event_type": "page_view",
    "user_id": "U00000001",
    "session_id": "Sabcdef123456",
    "timestamp": "2026-05-22T13:45:00.000000Z",
    "page_url": "https://shopstream.com/",
    "page_type": "home",
    "time_on_page_seconds": 12.5,
    "referrer": None,
    "device_type": "mobile",
    "country": "MX",
}

VALID_CART_EVENT = {
    "event_id": "Eabcdef0123456789",
    "event_type": "cart_event",
    "user_id": "U00000001",
    "session_id": "Sabcdef123456",
    "timestamp": "2026-05-22T13:45:00.000000Z",
    "product_id": "P000123",
    "action": "add",
}


class TestValidateLine:
    def test_valid_page_view(self):
        r = validate_line(json.dumps(VALID_PAGE_VIEW))
        assert r.is_valid is True
        assert r.event_type == "page_view"
        assert r.error is None

    def test_valid_page_view_bytes(self):
        r = validate_line(json.dumps(VALID_PAGE_VIEW).encode("utf-8"))
        assert r.is_valid is True

    def test_empty_line(self):
        r = validate_line("")
        assert r.is_valid is False
        assert r.error == "empty_line"

    def test_whitespace_only(self):
        r = validate_line("   \n")
        assert r.is_valid is False

    def test_invalid_json(self):
        r = validate_line("{not valid json}")
        assert r.is_valid is False
        assert "json_decode_error" in r.error

    def test_not_an_object(self):
        r = validate_line('["just", "an", "array"]')
        assert r.is_valid is False
        assert r.error == "payload_not_object"

    def test_unknown_event_type(self):
        bad = {**VALID_PAGE_VIEW, "event_type": "telepathy"}
        r = validate_line(json.dumps(bad))
        assert r.is_valid is False
        assert "unknown_event_type" in r.error

    def test_missing_event_type(self):
        bad = {k: v for k, v in VALID_PAGE_VIEW.items() if k != "event_type"}
        r = validate_line(json.dumps(bad))
        assert r.is_valid is False
        assert "unknown_event_type" in r.error

    def test_schema_violation_missing_field(self):
        bad = {k: v for k, v in VALID_PAGE_VIEW.items() if k != "page_url"}
        r = validate_line(json.dumps(bad))
        assert r.is_valid is False
        assert "schema_violation" in r.error

    def test_schema_violation_out_of_range(self):
        bad = {**VALID_PAGE_VIEW, "time_on_page_seconds": -10}
        r = validate_line(json.dumps(bad))
        assert r.is_valid is False
        assert "schema_violation" in r.error

    def test_schema_violation_bad_pattern(self):
        bad = {**VALID_PAGE_VIEW, "user_id": "not-a-valid-uid"}
        r = validate_line(json.dumps(bad))
        assert r.is_valid is False
        assert "schema_violation" in r.error

    def test_cart_event_valid(self):
        r = validate_line(json.dumps(VALID_CART_EVENT))
        assert r.is_valid is True
        assert r.event_type == "cart_event"

    def test_raw_payload_truncated_to_1000_chars(self):
        bad = json.dumps(VALID_PAGE_VIEW) + ("x" * 5000)
        r = validate_line(bad)
        rec = r.to_quarantine_record(line_no=1, source_key="events/foo.jsonl")
        assert len(rec["raw_payload"]) <= 1000


class TestEventTypeCounter:
    def test_returns_all_event_types_at_zero(self):
        c = event_type_counter()
        assert set(c.keys()) == {"page_view", "click", "search", "product_view", "cart_event"}
        assert all(v == 0 for v in c.values())
