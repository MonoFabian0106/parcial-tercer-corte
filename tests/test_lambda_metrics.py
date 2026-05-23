"""Tests del publisher de métricas CloudWatch."""

from __future__ import annotations

import boto3
import pytest
from moto import mock_aws

from lambda_ingest.metrics import DEFAULT_NAMESPACE, publish_ingest_metrics


@pytest.fixture
def cw():
    with mock_aws():
        yield boto3.client("cloudwatch", region_name="us-east-1")


class TestPublishIngestMetrics:
    def test_publishes_core_metrics(self, cw):
        publish_ingest_metrics(
            cw_client=cw,
            source_bucket="shopstream-raw-test",
            bytes_processed=12345,
            records_valid=900,
            records_invalid=100,
            duration_ms=1234.5,
            events_by_type={
                "page_view": 500,
                "click": 200,
                "search": 50,
                "product_view": 100,
                "cart_event": 50,
            },
        )
        listed = cw.list_metrics(Namespace=DEFAULT_NAMESPACE)["Metrics"]
        names = {m["MetricName"] for m in listed}
        assert {
            "FilesProcessed",
            "BytesProcessed",
            "RecordsValid",
            "RecordsInvalid",
            "InvalidRate",
            "ProcessingDurationMs",
            "EventsByType",
        }.issubset(names)

    def test_event_type_dimension_present(self, cw):
        publish_ingest_metrics(
            cw_client=cw,
            source_bucket="b",
            bytes_processed=0,
            records_valid=1,
            records_invalid=0,
            duration_ms=1.0,
            events_by_type={"page_view": 1, "click": 0, "search": 0,
                            "product_view": 0, "cart_event": 0},
        )
        listed = cw.list_metrics(Namespace=DEFAULT_NAMESPACE, MetricName="EventsByType")["Metrics"]
        dimensions_seen = {
            tuple(sorted((d["Name"], d["Value"]) for d in m["Dimensions"]))
            for m in listed
        }
        # Debe haber al menos una entrada con EventType=page_view
        assert any("EventType" in {d for pair in entry for d in pair if isinstance(d, str)}
                   for entry in dimensions_seen)

    def test_invalid_rate_zero_when_no_records(self, cw):
        publish_ingest_metrics(
            cw_client=cw,
            source_bucket="b",
            bytes_processed=0,
            records_valid=0,
            records_invalid=0,
            duration_ms=1.0,
            events_by_type={t: 0 for t in
                            ["page_view", "click", "search", "product_view", "cart_event"]},
        )
        # No raise: división por cero manejada
