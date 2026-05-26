"""Validación de eventos contra los esquemas de ShopStream.

Reutiliza `data_generation.schemas.EVENT_TYPE_SCHEMAS`. No hace I/O; recibe una
línea cruda (bytes o str) y devuelve un veredicto estructurado.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from jsonschema import Draft7Validator

from data_generation.schemas import EVENT_TYPE_SCHEMAS

# Pre-compilados (una sola instancia, reutilizable entre invocaciones Lambda)
_VALIDATORS: dict[str, Draft7Validator] = {
    event_type: Draft7Validator(schema) for event_type, schema in EVENT_TYPE_SCHEMAS.items()
}


@dataclass
class ValidationResult:
    is_valid: bool
    event_type: str | None
    error: str | None
    raw: str

    def to_quarantine_record(self, line_no: int, source_key: str) -> dict[str, Any]:
        return {
            "line_number": line_no,
            "source_key": source_key,
            "event_type": self.event_type,
            "error_reason": self.error,
            "raw_payload": self.raw[:1000],
        }


def validate_line(line: bytes | str) -> ValidationResult:
    """Valida una línea JSONL contra el schema apropiado según `event_type`."""
    raw = line.decode("utf-8", errors="replace") if isinstance(line, bytes) else line
    raw = raw.rstrip("\r\n")
    if not raw.strip():
        return ValidationResult(False, None, "empty_line", raw)

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        return ValidationResult(False, None, f"json_decode_error: {exc.msg}", raw)

    if not isinstance(payload, dict):
        return ValidationResult(False, None, "payload_not_object", raw)

    event_type = payload.get("event_type")
    if event_type not in _VALIDATORS:
        return ValidationResult(False, event_type, f"unknown_event_type: {event_type!r}", raw)

    validator = _VALIDATORS[event_type]
    errors = list(validator.iter_errors(payload))
    if errors:
        # Reportamos el primer error con path para facilitar diagnóstico
        first = errors[0]
        path = ".".join(str(p) for p in first.path) or "<root>"
        reason = f"schema_violation at {path}: {first.message}"
        return ValidationResult(False, event_type, reason, raw)

    return ValidationResult(True, event_type, None, raw)


def event_type_counter() -> dict[str, int]:
    return {t: 0 for t in EVENT_TYPE_SCHEMAS}
