"""Construcción de SparkSession y carga del dataset raw.

Las funciones son agnósticas del entorno: funcionan local (testing) y en EMR.
"""

from __future__ import annotations

from pyspark.sql import DataFrame, SparkSession
from pyspark.sql import functions as F
from pyspark.sql.types import (
    DoubleType,
    IntegerType,
    StringType,
    StructField,
    StructType,
)

# Schema explícito: evita schema-inference (costoso en archivos grandes) y nos da
# control sobre tipos. Cada evento usa un subconjunto; las columnas no presentes
# quedan nulas (esperado).
EVENTS_SCHEMA = StructType(
    [
        StructField("event_id", StringType(), nullable=False),
        StructField("event_type", StringType(), nullable=False),
        StructField("user_id", StringType(), nullable=False),
        StructField("session_id", StringType(), nullable=False),
        StructField("timestamp", StringType(), nullable=False),  # parseamos después
        # page_view
        StructField("page_url", StringType(), nullable=True),
        StructField("page_type", StringType(), nullable=True),
        StructField("time_on_page_seconds", DoubleType(), nullable=True),
        StructField("referrer", StringType(), nullable=True),
        StructField("device_type", StringType(), nullable=True),
        StructField("country", StringType(), nullable=True),
        # click
        StructField("element_id", StringType(), nullable=True),
        StructField("element_type", StringType(), nullable=True),
        StructField("x_position", IntegerType(), nullable=True),
        StructField("y_position", IntegerType(), nullable=True),
        # search
        StructField("query", StringType(), nullable=True),
        StructField("results_count", IntegerType(), nullable=True),
        # product_view / cart_event
        StructField("product_id", StringType(), nullable=True),
        StructField("category", StringType(), nullable=True),
        StructField("price", DoubleType(), nullable=True),
        StructField("action", StringType(), nullable=True),
    ]
)


def build_spark_session(app_name: str = "shopstream-etl") -> SparkSession:
    """Crea una SparkSession con configuración estándar.

    Funciona tanto en EMR (toma configs del cluster) como local (master local[*]).
    """
    builder = (
        SparkSession.builder.appName(app_name)
        .config("spark.sql.parquet.compression.codec", "snappy")
        .config("spark.sql.sources.partitionOverwriteMode", "dynamic")
        .config("spark.sql.session.timeZone", "UTC")
        # EMR ya tiene un master configurado; local usa el default si no se sobrescribe
    )
    return builder.getOrCreate()


def read_events(spark: SparkSession, input_path: str) -> DataFrame:
    """Lee los archivos JSONL del particionado raw.

    `input_path` puede ser:
    - `s3://bucket/events/year=2026/month=05/day=22/*.jsonl` (un día)
    - `s3://bucket/events/year=2026/month=05/day=*/*.jsonl` (un mes)
    - `s3://bucket/events/` (todo)
    Spark expande glob y descubre particiones automáticamente.
    """
    df = spark.read.schema(EVENTS_SCHEMA).json(input_path)
    # Parsear timestamp + derivar columnas útiles
    df = df.withColumn("event_ts", F.to_timestamp("timestamp"))
    df = df.withColumn("dt", F.to_date("event_ts"))
    df = df.withColumn("hour", F.hour("event_ts"))
    return df
