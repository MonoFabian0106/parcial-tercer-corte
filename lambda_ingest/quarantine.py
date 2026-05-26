"""Escritura de registros inválidos al bucket de cuarentena.

Estrategia:
- Para cada archivo procesado se genera UN archivo de cuarentena con todas las
  líneas inválidas como JSONL, conteniendo metadata del error.
- La key replica el particionado original para facilitar el lookup.
- El archivo se sube con metadata S3 (`source_key`, `error_count`, etc.) para
  inspección rápida con `aws s3api head-object`.
"""

from __future__ import annotations

import io
import json
import logging
import os
from collections.abc import Iterable

logger = logging.getLogger(__name__)

QUARANTINE_BUCKET_ENV = "S3_BUCKET_QUARANTINE"


def quarantine_key(source_key: str) -> str:
    """Deriva la key de cuarentena preservando el particionado por fecha.

    Por ejemplo:
        events/year=2026/month=05/day=22/events_2026-05-22.jsonl ->
        quarantine/year=2026/month=05/day=22/events_2026-05-22.errors.jsonl
    """
    # Reemplaza el primer "events/" por "quarantine/"
    if source_key.startswith("events/"):
        rest = source_key[len("events/") :]
    else:
        rest = source_key
    # Cambia sufijo .jsonl por .errors.jsonl
    if rest.endswith(".jsonl"):
        rest = rest[: -len(".jsonl")] + ".errors.jsonl"
    else:
        rest = rest + ".errors.jsonl"
    return f"quarantine/{rest}"


def write_quarantine(
    records: Iterable[dict],
    source_bucket: str,
    source_key: str,
    s3_client,
    quarantine_bucket: str | None = None,
) -> dict:
    """Sube los registros inválidos como JSONL al bucket de cuarentena.

    Devuelve metadata con bucket/key/count.
    """
    bucket = quarantine_bucket or os.environ.get(QUARANTINE_BUCKET_ENV)
    if not bucket:
        raise ValueError(f"Bucket de cuarentena no configurado (define {QUARANTINE_BUCKET_ENV})")

    buf = io.BytesIO()
    count = 0
    for rec in records:
        buf.write(json.dumps(rec, ensure_ascii=False).encode("utf-8"))
        buf.write(b"\n")
        count += 1

    if count == 0:
        logger.info("No quarantine records to write for s3://%s/%s", source_bucket, source_key)
        return {"bucket": bucket, "key": None, "count": 0}

    key = quarantine_key(source_key)
    buf.seek(0)
    s3_client.put_object(
        Bucket=bucket,
        Key=key,
        Body=buf.getvalue(),
        ContentType="application/x-ndjson",
        Metadata={
            "source_bucket": source_bucket,
            "source_key": source_key,
            "error_count": str(count),
        },
    )
    logger.warning(
        "Quarantine wrote %d records to s3://%s/%s",
        count,
        bucket,
        key,
    )
    return {"bucket": bucket, "key": key, "count": count}
