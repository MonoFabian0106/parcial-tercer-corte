"""Tests para los esquemas JSON: validez del schema y casos válidos/inválidos."""

from __future__ import annotations

import pytest
from jsonschema import Draft7Validator, ValidationError, validate

from data_generation.schemas import (
    CART_EVENT_SCHEMA,
    CLICK_SCHEMA,
    ENTITY_SCHEMAS,
    EVENT_SCHEMA,
    EVENT_TYPE_SCHEMAS,
    PAGE_VIEW_SCHEMA,
    PRODUCT_SCHEMA,
    PRODUCT_VIEW_SCHEMA,
    SEARCH_SCHEMA,
    TRANSACTION_SCHEMA,
    USER_SCHEMA,
)


class TestSchemaValidity:
    """Cada schema debe ser un Draft 7 válido."""

    @pytest.mark.parametrize("name,schema", list(ENTITY_SCHEMAS.items()))
    def test_entity_schemas_are_valid(self, name, schema):
        Draft7Validator.check_schema(schema)

    @pytest.mark.parametrize("name,schema", list(EVENT_TYPE_SCHEMAS.items()))
    def test_event_type_schemas_are_valid(self, name, schema):
        Draft7Validator.check_schema(schema)


class TestUserSchema:
    def test_valid_user(self):
        user = {
            "user_id": "U00000001",
            "signup_date": "2024-01-15",
            "country": "MX",
            "age_bucket": "25-34",
            "device_preference": "mobile",
            "is_premium": True,
        }
        validate(user, USER_SCHEMA)

    def test_user_missing_required_field(self):
        user = {"user_id": "U00000001", "signup_date": "2024-01-15", "country": "MX"}
        with pytest.raises(ValidationError):
            validate(user, USER_SCHEMA)

    def test_user_invalid_country(self):
        user = {
            "user_id": "U00000001",
            "signup_date": "2024-01-15",
            "country": "XX",
            "age_bucket": "25-34",
            "device_preference": "mobile",
        }
        with pytest.raises(ValidationError):
            validate(user, USER_SCHEMA)

    def test_user_invalid_user_id_pattern(self):
        user = {
            "user_id": "not-a-valid-id",
            "signup_date": "2024-01-15",
            "country": "MX",
            "age_bucket": "25-34",
            "device_preference": "mobile",
        }
        with pytest.raises(ValidationError):
            validate(user, USER_SCHEMA)


class TestProductSchema:
    def test_valid_product(self):
        product = {
            "product_id": "P000123",
            "category": "electronics",
            "subcategory": "smartphones",
            "name": "Cool Phone",
            "price": 599.99,
            "stock": 50,
            "created_at": "2025-01-01",
        }
        validate(product, PRODUCT_SCHEMA)

    def test_product_price_out_of_range(self):
        product = {
            "product_id": "P000123",
            "category": "electronics",
            "subcategory": "smartphones",
            "name": "Stupid Expensive Phone",
            "price": 999999.99,
            "stock": 50,
            "created_at": "2025-01-01",
        }
        with pytest.raises(ValidationError):
            validate(product, PRODUCT_SCHEMA)


class TestEventSchemas:
    def test_valid_page_view(self):
        ev = {
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
        validate(ev, PAGE_VIEW_SCHEMA)
        validate(ev, EVENT_SCHEMA)  # también valida vía oneOf

    def test_valid_click(self):
        ev = {
            "event_id": "Eabcdef0123456789",
            "event_type": "click",
            "user_id": "U00000001",
            "session_id": "Sabcdef123456",
            "timestamp": "2026-05-22T13:45:00.000000Z",
            "element_id": "btn_buy",
            "element_type": "button",
            "page_url": "https://shopstream.com/product/P000001",
            "x_position": 100,
            "y_position": 250,
        }
        validate(ev, CLICK_SCHEMA)
        validate(ev, EVENT_SCHEMA)

    def test_valid_search(self):
        ev = {
            "event_id": "Eabcdef0123456789",
            "event_type": "search",
            "user_id": "U00000001",
            "session_id": "Sabcdef123456",
            "timestamp": "2026-05-22T13:45:00.000000Z",
            "query": "running shoes",
            "results_count": 42,
        }
        validate(ev, SEARCH_SCHEMA)
        validate(ev, EVENT_SCHEMA)

    def test_valid_product_view(self):
        ev = {
            "event_id": "Eabcdef0123456789",
            "event_type": "product_view",
            "user_id": "U00000001",
            "session_id": "Sabcdef123456",
            "timestamp": "2026-05-22T13:45:00.000000Z",
            "product_id": "P000123",
            "category": "electronics",
            "price": 299.99,
            "time_on_page_seconds": 45.0,
        }
        validate(ev, PRODUCT_VIEW_SCHEMA)
        validate(ev, EVENT_SCHEMA)

    def test_valid_cart_event(self):
        ev = {
            "event_id": "Eabcdef0123456789",
            "event_type": "cart_event",
            "user_id": "U00000001",
            "session_id": "Sabcdef123456",
            "timestamp": "2026-05-22T13:45:00.000000Z",
            "product_id": "P000123",
            "action": "add",
        }
        validate(ev, CART_EVENT_SCHEMA)
        validate(ev, EVENT_SCHEMA)

    def test_cart_event_invalid_action(self):
        ev = {
            "event_id": "Eabcdef0123456789",
            "event_type": "cart_event",
            "user_id": "U00000001",
            "session_id": "Sabcdef123456",
            "timestamp": "2026-05-22T13:45:00.000000Z",
            "product_id": "P000123",
            "action": "destroy",
        }
        with pytest.raises(ValidationError):
            validate(ev, CART_EVENT_SCHEMA)

    def test_event_with_wrong_type_payload_fails(self):
        # cart_event con campos de page_view -> debe fallar por additionalProperties
        ev = {
            "event_id": "Eabcdef0123456789",
            "event_type": "cart_event",
            "user_id": "U00000001",
            "session_id": "Sabcdef123456",
            "timestamp": "2026-05-22T13:45:00.000000Z",
            "product_id": "P000123",
            "action": "add",
            "page_url": "https://shopstream.com/",
        }
        with pytest.raises(ValidationError):
            validate(ev, CART_EVENT_SCHEMA)

    def test_timestamp_format(self):
        ev = {
            "event_id": "Eabcdef0123456789",
            "event_type": "cart_event",
            "user_id": "U00000001",
            "session_id": "Sabcdef123456",
            "timestamp": "not-a-timestamp",
            "product_id": "P000123",
            "action": "add",
        }
        with pytest.raises(ValidationError):
            validate(ev, CART_EVENT_SCHEMA)


class TestTransactionSchema:
    def test_valid_transaction(self):
        tx = {
            "transaction_id": "T" + "a" * 16,
            "user_id": "U00000001",
            "session_id": "Sabcdef123456",
            "product_ids": ["P000123", "P000456"],
            "total_amount": 899.98,
            "status": "completed",
            "timestamp": "2026-05-22T13:45:00.000000Z",
        }
        validate(tx, TRANSACTION_SCHEMA)

    def test_transaction_empty_products_invalid(self):
        tx = {
            "transaction_id": "T" + "a" * 16,
            "user_id": "U00000001",
            "session_id": "Sabcdef123456",
            "product_ids": [],
            "total_amount": 0,
            "status": "failed",
            "timestamp": "2026-05-22T13:45:00.000000Z",
        }
        with pytest.raises(ValidationError):
            validate(tx, TRANSACTION_SCHEMA)
