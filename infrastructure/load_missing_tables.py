"""Carga las 4 tablas fact faltantes desde S3 Parquet a RDS."""
import io
import os

import boto3
import pandas as pd
import sqlalchemy as sa

# Cargar .env.local manualmente
with open(".env.local") as f:
    for line in f:
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())

url = (
    f"postgresql+psycopg2://{os.environ['DB_USER']}:{os.environ['DB_PASSWORD']}"
    f"@{os.environ['DB_HOST']}:{os.environ['DB_PORT']}/{os.environ['DB_NAME']}"
)
engine = sa.create_engine(url)

s3 = boto3.client("s3")
BUCKET = "shopstream-processed-mf0106"

METRICS = {
    "device_country": "fact_device_country",
    "funnel":         "fact_conversion_funnel",
    "nav_paths":      "fact_nav_paths",
    "product_gap":    "fact_product_gap",
}

for metric, table in METRICS.items():
    print(f"\n=== {metric} -> {table} ===")
    paginator = s3.get_paginator("list_objects_v2")
    pages = paginator.paginate(Bucket=BUCKET, Prefix=f"metrics/{metric}/")
    keys = [
        obj["Key"]
        for page in pages
        for obj in page.get("Contents", [])
        if obj["Key"].endswith(".parquet")
    ]
    print(f"  Parquet files: {len(keys)}")

    dfs = []
    for key in keys:
        # dt está en el path: metrics/device_country/dt=2026-05-22/part-0.parquet
        dt_val = next((p.split("=")[1] for p in key.split("/") if p.startswith("dt=")), None)
        obj = s3.get_object(Bucket=BUCKET, Key=key)
        part = pd.read_parquet(io.BytesIO(obj["Body"].read()))
        if dt_val:
            part["dt"] = pd.to_datetime(dt_val).date()
        dfs.append(part)

    if not dfs:
        print("  Sin datos, saltando.")
        continue

    df = pd.concat(dfs, ignore_index=True)
    print(f"  Filas: {len(df)}  |  Columnas: {list(df.columns)}")

    with engine.begin() as conn:
        conn.execute(sa.text(f"DELETE FROM {table}"))
        df.to_sql(table, conn, if_exists="append", index=False, method="multi", chunksize=500)
    print(f"  OK -> {table}")

print("\n==> Listo.")
