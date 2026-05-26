"""Tests para el uploader S3 con moto (mock de AWS)."""

from __future__ import annotations

from datetime import date

import boto3
import pytest
from moto import mock_aws

from data_generation.uploader import (
    ensure_bucket,
    s3_key_for_date,
    upload_day,
    upload_file,
)


@pytest.fixture
def s3_client():
    with mock_aws():
        client = boto3.client("s3", region_name="us-east-1")
        yield client


class TestS3KeyFormat:
    def test_basic_format(self):
        key = s3_key_for_date(date(2026, 5, 22))
        assert key == "events/year=2026/month=05/day=22/events_2026-05-22.jsonl"

    def test_custom_prefix(self):
        key = s3_key_for_date(date(2026, 1, 5), prefix="transactions")
        assert key == "transactions/year=2026/month=01/day=05/events_2026-01-05.jsonl"

    def test_zero_padding(self):
        # mes y día en single-digit deben quedar con padding
        key = s3_key_for_date(date(2026, 3, 7))
        assert "month=03" in key
        assert "day=07" in key


class TestEnsureBucket:
    def test_creates_bucket_when_missing(self, s3_client):
        ensure_bucket(s3_client, "shopstream-raw-test", region="us-east-1")
        assert s3_client.head_bucket(Bucket="shopstream-raw-test")

    def test_idempotent(self, s3_client):
        ensure_bucket(s3_client, "shopstream-raw-test", region="us-east-1")
        # Segunda llamada NO debe lanzar
        ensure_bucket(s3_client, "shopstream-raw-test", region="us-east-1")


class TestUpload:
    def test_upload_small_file(self, s3_client, tmp_path):
        local = tmp_path / "small.jsonl"
        local.write_text('{"a":1}\n{"b":2}\n', encoding="utf-8")
        ensure_bucket(s3_client, "test-bucket", "us-east-1")
        meta = upload_file(local, "test-bucket", "test/key.jsonl", s3_client=s3_client)
        assert meta["bucket"] == "test-bucket"
        assert meta["key"] == "test/key.jsonl"
        obj = s3_client.get_object(Bucket="test-bucket", Key="test/key.jsonl")
        body = obj["Body"].read().decode()
        assert "1" in body and "2" in body

    def test_upload_day_uses_partitioned_key(self, s3_client, tmp_path, monkeypatch):
        local = tmp_path / "events_2026-05-22.jsonl"
        local.write_text('{"event_id":"E1"}\n', encoding="utf-8")
        ensure_bucket(s3_client, "shopstream-raw-test", "us-east-1")
        meta = upload_day(
            local, date(2026, 5, 22), bucket="shopstream-raw-test", s3_client=s3_client
        )
        assert meta["key"] == "events/year=2026/month=05/day=22/events_2026-05-22.jsonl"
        # Verifica que existe en el bucket
        s3_client.head_object(Bucket="shopstream-raw-test", Key=meta["key"])

    def test_upload_day_requires_bucket(self, tmp_path, monkeypatch):
        local = tmp_path / "x.jsonl"
        local.write_text("{}\n", encoding="utf-8")
        monkeypatch.delenv("S3_BUCKET_RAW", raising=False)
        with pytest.raises(ValueError, match="Bucket no especificado"):
            upload_day(local, date(2026, 5, 22))

    def test_upload_metadata_attached(self, s3_client, tmp_path):
        local = tmp_path / "x.jsonl"
        local.write_text("{}\n", encoding="utf-8")
        ensure_bucket(s3_client, "test-bucket", "us-east-1")
        upload_file(local, "test-bucket", "x.jsonl", s3_client=s3_client)
        head = s3_client.head_object(Bucket="test-bucket", Key="x.jsonl")
        assert head["Metadata"]["source"] == "shopstream-generator"
        assert head["Metadata"]["format"] == "jsonl"
