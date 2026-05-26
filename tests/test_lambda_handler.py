"""Tests E2E del handler Lambda con moto."""

from __future__ import annotations

import importlib
import json

import boto3
import pytest
from moto import mock_aws

from tests.test_lambda_validator import VALID_CART_EVENT, VALID_PAGE_VIEW

RAW_BUCKET = "raw-bucket"
QUARANTINE_BUCKET = "quarantine-bucket"
SAMPLE_KEY = "events/year=2026/month=05/day=22/events_2026-05-22.jsonl"


def _s3_event(bucket: str, key: str) -> dict:
    """Construye un evento S3 PutObject como el que envía AWS."""
    return {
        "Records": [
            {
                "eventVersion": "2.1",
                "eventSource": "aws:s3",
                "eventName": "ObjectCreated:Put",
                "s3": {
                    "bucket": {"name": bucket},
                    "object": {"key": key},
                },
            }
        ]
    }


def _upload_jsonl(s3_client, bucket: str, key: str, lines: list[str]) -> None:
    body = "\n".join(lines).encode("utf-8")
    s3_client.put_object(Bucket=bucket, Key=key, Body=body)


@pytest.fixture
def aws(monkeypatch):
    """Setup completo: buckets S3, CloudWatch, env vars, e importa el handler."""
    monkeypatch.setenv("S3_BUCKET_QUARANTINE", QUARANTINE_BUCKET)
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")

    with mock_aws():
        s3 = boto3.client("s3", region_name="us-east-1")
        s3.create_bucket(Bucket=RAW_BUCKET)
        s3.create_bucket(Bucket=QUARANTINE_BUCKET)
        cw = boto3.client("cloudwatch", region_name="us-east-1")

        # Importar handler con los clientes mockeados ya activos
        import lambda_ingest.handler as h

        importlib.reload(h)

        yield {"s3": s3, "cw": cw, "handler": h}


class TestHandlerHappyPath:
    def test_all_valid_lines(self, aws):
        lines = [json.dumps(VALID_PAGE_VIEW), json.dumps(VALID_CART_EVENT)] * 50
        _upload_jsonl(aws["s3"], RAW_BUCKET, SAMPLE_KEY, lines)

        result = aws["handler"].lambda_handler(_s3_event(RAW_BUCKET, SAMPLE_KEY), context=None)
        proc = result["processed"][0]
        assert proc["records_valid"] == 100
        assert proc["records_invalid"] == 0
        assert proc["by_type"]["page_view"] == 50
        assert proc["by_type"]["cart_event"] == 50

    def test_no_quarantine_when_all_valid(self, aws):
        lines = [json.dumps(VALID_PAGE_VIEW)]
        _upload_jsonl(aws["s3"], RAW_BUCKET, SAMPLE_KEY, lines)

        aws["handler"].lambda_handler(_s3_event(RAW_BUCKET, SAMPLE_KEY), context=None)
        objs = aws["s3"].list_objects_v2(Bucket=QUARANTINE_BUCKET).get("Contents", [])
        assert objs == []


class TestHandlerWithInvalidLines:
    def test_mixed_valid_invalid(self, aws):
        # 8 válidos + 2 inválidos (20% inválido, bajo el umbral 50%)
        lines = (
            [json.dumps(VALID_PAGE_VIEW)] * 4
            + ["{not valid json}"]
            + [json.dumps(VALID_CART_EVENT)] * 4
            + [json.dumps({**VALID_PAGE_VIEW, "user_id": "WRONG"})]
        )
        _upload_jsonl(aws["s3"], RAW_BUCKET, SAMPLE_KEY, lines)

        result = aws["handler"].lambda_handler(_s3_event(RAW_BUCKET, SAMPLE_KEY), context=None)
        proc = result["processed"][0]
        assert proc["records_valid"] == 8
        assert proc["records_invalid"] == 2

        # Quarantine debe tener un archivo con 2 líneas (errores, no archivo completo)
        q_objs = aws["s3"].list_objects_v2(Bucket=QUARANTINE_BUCKET)["Contents"]
        assert len(q_objs) == 1
        assert q_objs[0]["Key"].endswith(".errors.jsonl")
        q_body = aws["s3"].get_object(Bucket=QUARANTINE_BUCKET, Key=q_objs[0]["Key"])["Body"].read()
        q_lines = q_body.decode().strip().split("\n")
        assert len(q_lines) == 2
        # La "{not valid json}" estaba en línea 5
        bad_json_record = json.loads(q_lines[0])
        assert bad_json_record["line_number"] == 5
        assert "json_decode_error" in bad_json_record["error_reason"]

    def test_quarantine_key_preserves_partition(self, aws):
        # 9 válidos + 1 inválido (10% < 50%)
        lines = [json.dumps(VALID_PAGE_VIEW)] * 9 + ["{bad"]
        _upload_jsonl(aws["s3"], RAW_BUCKET, SAMPLE_KEY, lines)
        aws["handler"].lambda_handler(_s3_event(RAW_BUCKET, SAMPLE_KEY), context=None)
        q_objs = aws["s3"].list_objects_v2(Bucket=QUARANTINE_BUCKET)["Contents"]
        assert q_objs[0]["Key"] == (
            "quarantine/year=2026/month=05/day=22/events_2026-05-22.errors.jsonl"
        )


class TestHandlerCorruptFile:
    def test_high_invalid_ratio_quarantines_whole_file(self, aws, monkeypatch):
        monkeypatch.setenv("MAX_INVALID_RATIO", "0.5")
        # Re-importar para que el handler lea la nueva env var
        import lambda_ingest.handler as h

        importlib.reload(h)

        lines = ["{bad}"] * 8 + [json.dumps(VALID_PAGE_VIEW)] * 2
        _upload_jsonl(aws["s3"], RAW_BUCKET, SAMPLE_KEY, lines)
        result = h.lambda_handler(_s3_event(RAW_BUCKET, SAMPLE_KEY), context=None)
        proc = result["processed"][0]
        assert proc["records_invalid"] == 8
        # El archivo entero debe haber sido copiado a quarantine
        q_objs = aws["s3"].list_objects_v2(Bucket=QUARANTINE_BUCKET)["Contents"]
        assert any(o["Key"].endswith(".full.jsonl") for o in q_objs)


class TestHandlerMetrics:
    def test_metrics_published(self, aws):
        lines = [json.dumps(VALID_PAGE_VIEW)] * 5 + ["{bad}"] * 1
        _upload_jsonl(aws["s3"], RAW_BUCKET, SAMPLE_KEY, lines)
        aws["handler"].lambda_handler(_s3_event(RAW_BUCKET, SAMPLE_KEY), context=None)

        metrics = aws["cw"].list_metrics(Namespace="ShopStream/Ingest")["Metrics"]
        names = {m["MetricName"] for m in metrics}
        assert "FilesProcessed" in names
        assert "RecordsValid" in names
        assert "RecordsInvalid" in names
        assert "InvalidRate" in names
