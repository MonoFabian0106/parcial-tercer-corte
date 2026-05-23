"""Entry point Lambda — ingesta y validación de archivos S3 PutObject.

Disparado por eventos `s3:ObjectCreated:Put` sobre el bucket raw. Para cada
objeto:
1. Stream del cuerpo desde S3 línea a línea (sin cargar todo el archivo en RAM).
2. Validar cada línea contra el schema apropiado.
3. Acumular las líneas inválidas y subirlas a quarantine al final.
4. Publicar métricas en CloudWatch.

Variables de entorno requeridas:
- S3_BUCKET_QUARANTINE: bucket destino para errores.
- (opcional) METRICS_NAMESPACE: por defecto "ShopStream/Ingest".
- (opcional) MAX_INVALID_RATIO: si la tasa de inválidos supera este umbral
  (0-1), todo el archivo se considera "corrupto" y se vuelca completo a
  cuarentena. Por defecto 0.5 (50%).
"""

from __future__ import annotations

import json
import logging
import os
import time
from typing import Any
from urllib.parse import unquote_plus

import boto3

from lambda_ingest.metrics import DEFAULT_NAMESPACE, publish_ingest_metrics
from lambda_ingest.quarantine import quarantine_key, write_quarantine
from lambda_ingest.validator import event_type_counter, validate_line

logger = logging.getLogger()
logger.setLevel(os.environ.get("LOG_LEVEL", "INFO"))

_s3 = boto3.client("s3")
_cw = boto3.client("cloudwatch")


def _process_file(bucket: str, key: str) -> dict[str, Any]:
    """Procesa un único archivo S3. Devuelve métricas del proceso."""
    started = time.monotonic()
    logger.info("Processing s3://%s/%s", bucket, key)

    head = _s3.head_object(Bucket=bucket, Key=key)
    size_bytes = head["ContentLength"]

    obj = _s3.get_object(Bucket=bucket, Key=key)
    body = obj["Body"]  # botocore.response.StreamingBody (file-like)

    valid_count = 0
    invalid_records: list[dict] = []
    events_by_type = event_type_counter()

    for line_no, raw_line in enumerate(body.iter_lines(), start=1):
        result = validate_line(raw_line)
        if result.is_valid:
            valid_count += 1
            if result.event_type:
                events_by_type[result.event_type] = events_by_type.get(result.event_type, 0) + 1
        else:
            invalid_records.append(result.to_quarantine_record(line_no, key))

    invalid_count = len(invalid_records)
    total = valid_count + invalid_count
    invalid_ratio = (invalid_count / total) if total else 0.0
    max_ratio = float(os.environ.get("MAX_INVALID_RATIO", "0.5"))

    quarantine_meta: dict[str, Any] = {"bucket": None, "key": None, "count": 0}

    if invalid_records:
        if invalid_ratio >= max_ratio:
            logger.error(
                "File s3://%s/%s exceeds invalid ratio (%.2f >= %.2f). Quarantining entire file.",
                bucket, key, invalid_ratio, max_ratio,
            )
            # Volcar el archivo completo: re-leerlo y subirlo al bucket de quarantine
            quarantine_meta = _quarantine_whole_file(bucket, key, reason="invalid_ratio_exceeded")
        else:
            quarantine_meta = write_quarantine(
                records=invalid_records,
                source_bucket=bucket,
                source_key=key,
                s3_client=_s3,
            )

    duration_ms = (time.monotonic() - started) * 1000.0
    metrics_summary = {
        "source_bucket": bucket,
        "source_key": key,
        "size_bytes": size_bytes,
        "records_valid": valid_count,
        "records_invalid": invalid_count,
        "invalid_ratio": round(invalid_ratio, 4),
        "duration_ms": round(duration_ms, 2),
        "by_type": events_by_type,
        "quarantine": quarantine_meta,
    }

    publish_ingest_metrics(
        cw_client=_cw,
        source_bucket=bucket,
        bytes_processed=size_bytes,
        records_valid=valid_count,
        records_invalid=invalid_count,
        duration_ms=duration_ms,
        events_by_type=events_by_type,
        namespace=os.environ.get("METRICS_NAMESPACE", DEFAULT_NAMESPACE),
    )

    logger.info("Done: %s", json.dumps(metrics_summary, default=str))
    return metrics_summary


def _quarantine_whole_file(bucket: str, key: str, reason: str) -> dict:
    """Copia el archivo completo al bucket de cuarentena con metadata del motivo."""
    quarantine_bucket = os.environ["S3_BUCKET_QUARANTINE"]
    q_key = quarantine_key(key).replace(".errors.jsonl", ".full.jsonl")
    _s3.copy_object(
        Bucket=quarantine_bucket,
        Key=q_key,
        CopySource={"Bucket": bucket, "Key": key},
        Metadata={
            "source_bucket": bucket,
            "source_key": key,
            "reason": reason,
        },
        MetadataDirective="REPLACE",
        ContentType="application/x-ndjson",
    )
    return {"bucket": quarantine_bucket, "key": q_key, "count": -1, "reason": reason}


def lambda_handler(event: dict, context) -> dict:
    """Entry point invocado por AWS Lambda.

    Espera el formato estándar de eventos S3 PutObject.
    """
    results = []
    for record in event.get("Records", []):
        bucket = record["s3"]["bucket"]["name"]
        key = unquote_plus(record["s3"]["object"]["key"])
        try:
            results.append(_process_file(bucket, key))
        except Exception:
            logger.exception("Failed to process s3://%s/%s", bucket, key)
            # No re-lanzamos: Lambda re-intentará automáticamente; queremos métricas
            # publicadas siempre. En entorno real, considerar DLQ.
            results.append({"source_bucket": bucket, "source_key": key, "error": True})
    return {"processed": results}
