"""Crea un archivo de prueba con líneas válidas e inválidas para el E2E test."""

from __future__ import annotations

import json
from pathlib import Path


def main():
    src = Path("data/raw/events_2026-05-22.jsonl")
    out = Path("data/raw/test_mixed.jsonl")

    invalid_lines = [
        "{not valid json}",
        json.dumps({"event_type": "unknown"}),
        json.dumps({"event_type": "page_view", "user_id": "INVALID"}),
        "not even close to json",
        json.dumps(
            {
                "event_type": "cart_event",
                "user_id": "U00000001",
                "session_id": "Sabcdef123456",
                "timestamp": "2026-05-22T13:45:00.000000Z",
                "product_id": "P000123",
                "action": "destroy",
            }
        ),
    ]

    with src.open("r", encoding="utf-8") as f, out.open("w", encoding="utf-8") as o:
        for _ in range(100):
            o.write(next(f))
        for line in invalid_lines:
            o.write(line + "\n")

    print(f"Created {out} with 100 valid + {len(invalid_lines)} invalid lines")


if __name__ == "__main__":
    main()
