"""Publicación de métricas a CloudWatch.

Namespace: `ShopStream/Ingest`.

Métricas publicadas por archivo procesado:
- FilesProcessed (Count)
- BytesProcessed (Bytes)
- RecordsValid (Count)
- RecordsInvalid (Count)
- InvalidRate (Percent)
- ProcessingDurationMs (Milliseconds)
- EventsByType (Count, dimensión EventType)

Cada métrica incluye la dimensión `SourceBucket` para distinguir buckets si en
algún momento crecen los inputs.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

logger = logging.getLogger(__name__)

DEFAULT_NAMESPACE = "ShopStream/Ingest"


def _metric(name: str, value: float, unit: str, dimensions: list[dict]) -> dict:
    return {
        "MetricName": name,
        "Value": value,
        "Unit": unit,
        "Dimensions": dimensions,
        "Timestamp": datetime.now(UTC),
    }


def publish_ingest_metrics(
    cw_client,
    source_bucket: str,
    bytes_processed: int,
    records_valid: int,
    records_invalid: int,
    duration_ms: float,
    events_by_type: dict[str, int],
    namespace: str = DEFAULT_NAMESPACE,
) -> None:
    base_dims = [{"Name": "SourceBucket", "Value": source_bucket}]
    total = records_valid + records_invalid
    invalid_rate = (records_invalid / total * 100.0) if total else 0.0

    metrics: list[dict] = [
        _metric("FilesProcessed", 1, "Count", base_dims),
        _metric("BytesProcessed", float(bytes_processed), "Bytes", base_dims),
        _metric("RecordsValid", float(records_valid), "Count", base_dims),
        _metric("RecordsInvalid", float(records_invalid), "Count", base_dims),
        _metric("InvalidRate", invalid_rate, "Percent", base_dims),
        _metric("ProcessingDurationMs", duration_ms, "Milliseconds", base_dims),
    ]
    # Una métrica por tipo de evento con dimensión adicional
    for event_type, count in events_by_type.items():
        metrics.append(
            _metric(
                "EventsByType",
                float(count),
                "Count",
                [*base_dims, {"Name": "EventType", "Value": event_type}],
            )
        )

    # PutMetricData admite hasta 1000 métricas por llamada; estamos muy por debajo.
    _put_in_batches(cw_client, namespace, metrics)


def _put_in_batches(cw_client, namespace: str, metrics: list[dict], batch_size: int = 20) -> None:
    for i in range(0, len(metrics), batch_size):
        batch = metrics[i : i + batch_size]
        cw_client.put_metric_data(Namespace=namespace, MetricData=batch)
    logger.info("Published %d metrics to %s", len(metrics), namespace)
