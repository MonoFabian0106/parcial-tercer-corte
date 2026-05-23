"""Subida de archivos generados a S3 con particionado year/month/day.

Estructura de keys:
    s3://<bucket>/events/year=YYYY/month=MM/day=DD/events_YYYY-MM-DD.jsonl
"""

from __future__ import annotations

import logging
import os
from datetime import date
from pathlib import Path

import boto3
from boto3.s3.transfer import TransferConfig
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)

# Multipart kicks in para archivos > 50 MB (los nuestros pesan ~200-500 MB)
DEFAULT_TRANSFER_CONFIG = TransferConfig(
    multipart_threshold=50 * 1024 * 1024,
    multipart_chunksize=16 * 1024 * 1024,
    max_concurrency=4,
    use_threads=True,
)


def s3_key_for_date(run_date: date, prefix: str = "events") -> str:
    return (
        f"{prefix}/year={run_date.year:04d}/"
        f"month={run_date.month:02d}/day={run_date.day:02d}/"
        f"events_{run_date.isoformat()}.jsonl"
    )


def ensure_bucket(s3_client, bucket: str, region: str) -> None:
    """Crea el bucket si no existe (idempotente)."""
    try:
        s3_client.head_bucket(Bucket=bucket)
        logger.info("Bucket %s already exists", bucket)
        return
    except ClientError as e:
        code = e.response.get("Error", {}).get("Code", "")
        if code not in ("404", "NoSuchBucket", "NotFound"):
            raise

    create_kwargs: dict = {"Bucket": bucket}
    if region != "us-east-1":
        create_kwargs["CreateBucketConfiguration"] = {"LocationConstraint": region}
    s3_client.create_bucket(**create_kwargs)
    logger.info("Bucket %s created in %s", bucket, region)


def upload_file(
    local_path: Path,
    bucket: str,
    key: str,
    s3_client=None,
    transfer_config: TransferConfig | None = None,
) -> dict:
    """Sube un archivo local a S3. Devuelve metadata básica."""
    if s3_client is None:
        s3_client = boto3.client("s3")
    size = local_path.stat().st_size
    logger.info("Uploading %s (%.2f MB) -> s3://%s/%s", local_path, size / 1e6, bucket, key)
    s3_client.upload_file(
        Filename=str(local_path),
        Bucket=bucket,
        Key=key,
        Config=transfer_config or DEFAULT_TRANSFER_CONFIG,
        ExtraArgs={
            "ContentType": "application/x-ndjson",
            "Metadata": {
                "source": "shopstream-generator",
                "format": "jsonl",
            },
        },
    )
    return {"bucket": bucket, "key": key, "size_bytes": size}


def upload_day(
    local_path: Path,
    run_date: date,
    bucket: str | None = None,
    s3_client=None,
) -> dict:
    """Sube el archivo de un día completo a la partición correcta."""
    bucket = bucket or os.environ.get("S3_BUCKET_RAW")
    if not bucket:
        raise ValueError(
            "Bucket no especificado. Pasa `bucket=...` o define S3_BUCKET_RAW en el entorno."
        )
    key = s3_key_for_date(run_date)
    return upload_file(local_path, bucket, key, s3_client=s3_client)
