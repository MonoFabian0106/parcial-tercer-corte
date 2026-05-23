"""Tests del módulo de cuarentena."""

from __future__ import annotations

import json

import boto3
import pytest
from moto import mock_aws

from lambda_ingest.quarantine import quarantine_key, write_quarantine


class TestQuarantineKey:
    def test_replaces_events_prefix(self):
        k = quarantine_key("events/year=2026/month=05/day=22/events_2026-05-22.jsonl")
        assert k == "quarantine/year=2026/month=05/day=22/events_2026-05-22.errors.jsonl"

    def test_non_events_prefix_passthrough(self):
        k = quarantine_key("random/path/file.jsonl")
        assert k == "quarantine/random/path/file.errors.jsonl"

    def test_non_jsonl_suffix(self):
        k = quarantine_key("events/file.txt")
        assert k == "quarantine/file.txt.errors.jsonl"


@pytest.fixture
def s3_setup():
    with mock_aws():
        client = boto3.client("s3", region_name="us-east-1")
        client.create_bucket(Bucket="src-bucket")
        client.create_bucket(Bucket="quarantine-bucket")
        yield client


class TestWriteQuarantine:
    def test_no_records_returns_zero_count(self, s3_setup):
        meta = write_quarantine(
            records=[],
            source_bucket="src-bucket",
            source_key="events/year=2026/month=05/day=22/x.jsonl",
            s3_client=s3_setup,
            quarantine_bucket="quarantine-bucket",
        )
        assert meta["count"] == 0
        assert meta["key"] is None

    def test_writes_records_as_jsonl(self, s3_setup):
        records = [
            {"line_number": 1, "error_reason": "json_decode_error", "raw_payload": "{bad"},
            {"line_number": 5, "error_reason": "schema_violation", "raw_payload": "{}"},
        ]
        meta = write_quarantine(
            records=records,
            source_bucket="src-bucket",
            source_key="events/year=2026/month=05/day=22/x.jsonl",
            s3_client=s3_setup,
            quarantine_bucket="quarantine-bucket",
        )
        assert meta["count"] == 2
        obj = s3_setup.get_object(Bucket="quarantine-bucket", Key=meta["key"])
        body = obj["Body"].read().decode().strip()
        lines = body.split("\n")
        assert len(lines) == 2
        assert json.loads(lines[0])["line_number"] == 1
        assert json.loads(lines[1])["error_reason"] == "schema_violation"

    def test_metadata_attached(self, s3_setup):
        meta = write_quarantine(
            records=[{"line_number": 1, "error_reason": "x", "raw_payload": "y"}],
            source_bucket="src-bucket",
            source_key="events/foo.jsonl",
            s3_client=s3_setup,
            quarantine_bucket="quarantine-bucket",
        )
        head = s3_setup.head_object(Bucket="quarantine-bucket", Key=meta["key"])
        assert head["Metadata"]["source_bucket"] == "src-bucket"
        assert head["Metadata"]["source_key"] == "events/foo.jsonl"
        assert head["Metadata"]["error_count"] == "1"
        assert head["ContentType"] == "application/x-ndjson"

    def test_missing_bucket_raises(self, s3_setup, monkeypatch):
        monkeypatch.delenv("S3_BUCKET_QUARANTINE", raising=False)
        with pytest.raises(ValueError, match="Bucket de cuarentena"):
            write_quarantine(
                records=[{"line_number": 1}],
                source_bucket="src-bucket",
                source_key="events/foo.jsonl",
                s3_client=s3_setup,
            )
