"""Manual input validators for query string params."""
from __future__ import annotations

from datetime import date, datetime


class ValidationError(ValueError):
    """Raised when a request param fails validation."""


def parse_date(raw: str | None, *, field: str = "date", required: bool = True) -> date | None:
    if raw is None or raw == "":
        if required:
            raise ValidationError(f"'{field}' is required (format YYYY-MM-DD)")
        return None
    try:
        return datetime.strptime(raw, "%Y-%m-%d").date()
    except ValueError as exc:
        raise ValidationError(f"'{field}' must be YYYY-MM-DD, got '{raw}'") from exc


def parse_enum(raw: str | None, allowed: set[str], *, field: str, required: bool = True) -> str | None:
    if raw is None or raw == "":
        if required:
            raise ValidationError(f"'{field}' is required (one of {sorted(allowed)})")
        return None
    if raw not in allowed:
        raise ValidationError(f"'{field}' must be one of {sorted(allowed)}, got '{raw}'")
    return raw


def parse_int(
    raw: str | None,
    *,
    field: str,
    default: int | None = None,
    minimum: int = 1,
    maximum: int = 1000,
) -> int:
    if raw is None or raw == "":
        if default is None:
            raise ValidationError(f"'{field}' is required (integer in [{minimum}, {maximum}])")
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValidationError(f"'{field}' must be an integer, got '{raw}'") from exc
    if value < minimum or value > maximum:
        raise ValidationError(f"'{field}' must be in [{minimum}, {maximum}], got {value}")
    return value


def parse_country(raw: str | None, *, field: str = "country", required: bool = False) -> str | None:
    if raw is None or raw == "":
        if required:
            raise ValidationError(f"'{field}' is required (ISO 3166 alpha-2)")
        return None
    normalized = raw.strip().upper()
    if len(normalized) != 2 or not normalized.isalpha():
        raise ValidationError(f"'{field}' must be a 2-letter ISO code, got '{raw}'")
    return normalized
