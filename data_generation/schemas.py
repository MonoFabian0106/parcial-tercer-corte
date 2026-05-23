"""JSON Schemas para todas las entidades del pipeline ShopStream.

Estos esquemas se usan tanto para validar la generación sintética (Punto 1) como
para validar la ingesta en la Lambda (Punto 2). Centralizarlos aquí evita
divergencia entre componentes.
"""

from __future__ import annotations

from typing import Any

# ---------------------------------------------------------------------------
# Constantes de dominio
# ---------------------------------------------------------------------------

DEVICE_TYPES = ["mobile", "desktop", "tablet"]
PAGE_TYPES = ["home", "category", "product", "cart", "checkout", "search", "other"]
EVENT_TYPES = ["page_view", "click", "search", "product_view", "cart_event"]
CART_ACTIONS = ["add", "remove"]
TRANSACTION_STATUS = ["completed", "pending", "failed", "refunded"]
COUNTRIES = ["MX", "CO", "AR", "ES", "PE", "CL", "US", "BR", "UY", "EC"]
BROWSERS = ["chrome", "safari", "firefox", "edge", "opera"]
ELEMENT_TYPES = ["button", "link", "image", "banner", "menu", "filter"]
PRODUCT_CATEGORIES = [
    "electronics",
    "clothing",
    "home",
    "sports",
    "books",
    "beauty",
    "toys",
    "food",
]
AGE_BUCKETS = ["18-24", "25-34", "35-44", "45-54", "55-64", "65+"]

# Pattern ISO 8601 UTC (con 'Z' o '+00:00')
ISO_TIMESTAMP_PATTERN = r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:\d{2})$"


# ---------------------------------------------------------------------------
# Esquemas
# ---------------------------------------------------------------------------

USER_SCHEMA: dict[str, Any] = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "title": "User",
    "type": "object",
    "required": ["user_id", "signup_date", "country", "age_bucket", "device_preference"],
    "additionalProperties": False,
    "properties": {
        "user_id": {"type": "string", "pattern": "^U[0-9]{8}$"},
        "signup_date": {"type": "string", "format": "date"},
        "country": {"type": "string", "enum": COUNTRIES},
        "age_bucket": {"type": "string", "enum": AGE_BUCKETS},
        "device_preference": {"type": "string", "enum": DEVICE_TYPES},
        "is_premium": {"type": "boolean"},
    },
}


PRODUCT_SCHEMA: dict[str, Any] = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "title": "Product",
    "type": "object",
    "required": ["product_id", "category", "subcategory", "name", "price", "stock", "created_at"],
    "additionalProperties": False,
    "properties": {
        "product_id": {"type": "string", "pattern": "^P[0-9]{6}$"},
        "category": {"type": "string", "enum": PRODUCT_CATEGORIES},
        "subcategory": {"type": "string", "minLength": 1, "maxLength": 60},
        "name": {"type": "string", "minLength": 1, "maxLength": 120},
        "price": {"type": "number", "minimum": 0.5, "maximum": 5000.0},
        "stock": {"type": "integer", "minimum": 0, "maximum": 10000},
        "brand": {"type": "string", "maxLength": 60},
        "rating": {"type": "number", "minimum": 0, "maximum": 5},
        "created_at": {"type": "string", "format": "date"},
    },
}


SESSION_SCHEMA: dict[str, Any] = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "title": "Session",
    "type": "object",
    "required": [
        "session_id",
        "user_id",
        "start_time",
        "end_time",
        "device_type",
        "browser",
        "country",
    ],
    "additionalProperties": False,
    "properties": {
        "session_id": {"type": "string", "pattern": "^S[a-f0-9]{12}$"},
        "user_id": {"type": "string", "pattern": "^U[0-9]{8}$"},
        "start_time": {"type": "string", "pattern": ISO_TIMESTAMP_PATTERN},
        "end_time": {"type": "string", "pattern": ISO_TIMESTAMP_PATTERN},
        "device_type": {"type": "string", "enum": DEVICE_TYPES},
        "browser": {"type": "string", "enum": BROWSERS},
        "country": {"type": "string", "enum": COUNTRIES},
        "referrer_source": {
            "type": "string",
            "enum": ["organic", "paid", "social", "direct", "email", "referral"],
        },
    },
}


# ---------------------------------------------------------------------------
# Eventos (5 tipos). Cada evento tiene event_id + event_type + payload propio.
# Se usa `oneOf` para que jsonschema seleccione la variante correcta según
# event_type.
# ---------------------------------------------------------------------------

_COMMON_EVENT_PROPS = {
    "event_id": {"type": "string", "pattern": "^E[a-f0-9]{16}$"},
    "event_type": {"type": "string", "enum": EVENT_TYPES},
    "user_id": {"type": "string", "pattern": "^U[0-9]{8}$"},
    "session_id": {"type": "string", "pattern": "^S[a-f0-9]{12}$"},
    "timestamp": {"type": "string", "pattern": ISO_TIMESTAMP_PATTERN},
}


PAGE_VIEW_SCHEMA: dict[str, Any] = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "title": "PageViewEvent",
    "type": "object",
    "required": [
        "event_id",
        "event_type",
        "user_id",
        "session_id",
        "timestamp",
        "page_url",
        "page_type",
        "time_on_page_seconds",
        "device_type",
        "country",
    ],
    "additionalProperties": False,
    "properties": {
        **_COMMON_EVENT_PROPS,
        "event_type": {"const": "page_view"},
        "page_url": {"type": "string", "minLength": 1, "maxLength": 500},
        "page_type": {"type": "string", "enum": PAGE_TYPES},
        "time_on_page_seconds": {"type": "number", "minimum": 0, "maximum": 7200},
        "referrer": {"type": ["string", "null"], "maxLength": 500},
        "device_type": {"type": "string", "enum": DEVICE_TYPES},
        "country": {"type": "string", "enum": COUNTRIES},
    },
}


CLICK_SCHEMA: dict[str, Any] = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "title": "ClickEvent",
    "type": "object",
    "required": [
        "event_id",
        "event_type",
        "user_id",
        "session_id",
        "timestamp",
        "element_id",
        "element_type",
        "page_url",
        "x_position",
        "y_position",
    ],
    "additionalProperties": False,
    "properties": {
        **_COMMON_EVENT_PROPS,
        "event_type": {"const": "click"},
        "element_id": {"type": "string", "minLength": 1, "maxLength": 100},
        "element_type": {"type": "string", "enum": ELEMENT_TYPES},
        "page_url": {"type": "string", "minLength": 1, "maxLength": 500},
        "x_position": {"type": "integer", "minimum": 0, "maximum": 5000},
        "y_position": {"type": "integer", "minimum": 0, "maximum": 10000},
    },
}


SEARCH_SCHEMA: dict[str, Any] = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "title": "SearchEvent",
    "type": "object",
    "required": [
        "event_id",
        "event_type",
        "user_id",
        "session_id",
        "timestamp",
        "query",
        "results_count",
    ],
    "additionalProperties": False,
    "properties": {
        **_COMMON_EVENT_PROPS,
        "event_type": {"const": "search"},
        "query": {"type": "string", "minLength": 1, "maxLength": 200},
        "results_count": {"type": "integer", "minimum": 0, "maximum": 10000},
    },
}


PRODUCT_VIEW_SCHEMA: dict[str, Any] = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "title": "ProductViewEvent",
    "type": "object",
    "required": [
        "event_id",
        "event_type",
        "user_id",
        "session_id",
        "timestamp",
        "product_id",
        "category",
        "price",
        "time_on_page_seconds",
    ],
    "additionalProperties": False,
    "properties": {
        **_COMMON_EVENT_PROPS,
        "event_type": {"const": "product_view"},
        "product_id": {"type": "string", "pattern": "^P[0-9]{6}$"},
        "category": {"type": "string", "enum": PRODUCT_CATEGORIES},
        "price": {"type": "number", "minimum": 0.5, "maximum": 5000.0},
        "time_on_page_seconds": {"type": "number", "minimum": 0, "maximum": 7200},
    },
}


CART_EVENT_SCHEMA: dict[str, Any] = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "title": "CartEvent",
    "type": "object",
    "required": [
        "event_id",
        "event_type",
        "user_id",
        "session_id",
        "timestamp",
        "product_id",
        "action",
    ],
    "additionalProperties": False,
    "properties": {
        **_COMMON_EVENT_PROPS,
        "event_type": {"const": "cart_event"},
        "product_id": {"type": "string", "pattern": "^P[0-9]{6}$"},
        "action": {"type": "string", "enum": CART_ACTIONS},
    },
}


# Schema "polimorfico" para validar cualquier evento via `oneOf`.
EVENT_SCHEMA: dict[str, Any] = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "title": "Event",
    "oneOf": [
        PAGE_VIEW_SCHEMA,
        CLICK_SCHEMA,
        SEARCH_SCHEMA,
        PRODUCT_VIEW_SCHEMA,
        CART_EVENT_SCHEMA,
    ],
}


TRANSACTION_SCHEMA: dict[str, Any] = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "title": "Transaction",
    "type": "object",
    "required": [
        "transaction_id",
        "user_id",
        "session_id",
        "product_ids",
        "total_amount",
        "status",
        "timestamp",
    ],
    "additionalProperties": False,
    "properties": {
        "transaction_id": {"type": "string", "pattern": "^T[a-f0-9]{16}$"},
        "user_id": {"type": "string", "pattern": "^U[0-9]{8}$"},
        "session_id": {"type": "string", "pattern": "^S[a-f0-9]{12}$"},
        "product_ids": {
            "type": "array",
            "items": {"type": "string", "pattern": "^P[0-9]{6}$"},
            "minItems": 1,
            "maxItems": 50,
        },
        "total_amount": {"type": "number", "minimum": 0.5, "maximum": 100000.0},
        "status": {"type": "string", "enum": TRANSACTION_STATUS},
        "payment_method": {
            "type": "string",
            "enum": ["credit_card", "debit_card", "paypal", "transfer", "cash_on_delivery"],
        },
        "timestamp": {"type": "string", "pattern": ISO_TIMESTAMP_PATTERN},
    },
}


# ---------------------------------------------------------------------------
# Registry para lookup por nombre de entidad / tipo de evento
# ---------------------------------------------------------------------------

ENTITY_SCHEMAS: dict[str, dict[str, Any]] = {
    "user": USER_SCHEMA,
    "product": PRODUCT_SCHEMA,
    "session": SESSION_SCHEMA,
    "event": EVENT_SCHEMA,
    "transaction": TRANSACTION_SCHEMA,
}

EVENT_TYPE_SCHEMAS: dict[str, dict[str, Any]] = {
    "page_view": PAGE_VIEW_SCHEMA,
    "click": CLICK_SCHEMA,
    "search": SEARCH_SCHEMA,
    "product_view": PRODUCT_VIEW_SCHEMA,
    "cart_event": CART_EVENT_SCHEMA,
}
