"""Limpieza de eventos: deduplicación, imputación, normalización.

Cada función es pura: recibe un DataFrame y devuelve otro DataFrame nuevo.
"""

from __future__ import annotations

from pyspark.sql import DataFrame
from pyspark.sql import functions as F
from pyspark.sql import Window


def deduplicate_events(df: DataFrame) -> DataFrame:
    """Elimina eventos duplicados por `event_id`.

    Si dos filas tienen el mismo event_id, conservamos la primera por orden
    temporal (timestamp ascendente). Si event_id es nulo, se descarta.
    """
    w = Window.partitionBy("event_id").orderBy(F.asc("event_ts"))
    return (
        df.filter(F.col("event_id").isNotNull())
        .withColumn("_rn", F.row_number().over(w))
        .filter(F.col("_rn") == 1)
        .drop("_rn")
    )


def impute_country(df: DataFrame) -> DataFrame:
    """Imputa `country` nulo a 'UNKNOWN' (solo aplica a eventos page_view)."""
    return df.withColumn(
        "country",
        F.when(F.col("country").isNull(), F.lit("UNKNOWN")).otherwise(F.col("country")),
    )


def impute_device_type(df: DataFrame) -> DataFrame:
    """Para los eventos sin `device_type` (click, search, product_view, cart_event),
    imputa con el `device_type` modal del `user_id` calculado de los page_view del día.
    Si tampoco existe, deja 'UNKNOWN'.
    """
    # Calcula moda del device_type por user_id usando los page_view
    user_device = (
        df.filter(F.col("event_type") == "page_view")
        .filter(F.col("device_type").isNotNull())
        .groupBy("user_id", "device_type")
        .count()
    )
    w = Window.partitionBy("user_id").orderBy(F.desc("count"))
    user_mode = (
        user_device.withColumn("_rn", F.row_number().over(w))
        .filter(F.col("_rn") == 1)
        .select(F.col("user_id"), F.col("device_type").alias("user_modal_device"))
    )

    return (
        df.join(user_mode, on="user_id", how="left")
        .withColumn(
            "device_type",
            F.coalesce(F.col("device_type"), F.col("user_modal_device"), F.lit("UNKNOWN")),
        )
        .drop("user_modal_device")
    )


def impute_time_on_page(df: DataFrame) -> DataFrame:
    """Imputa `time_on_page_seconds` nulo con la mediana del `page_type` (solo page_view)."""
    pv = df.filter(F.col("event_type") == "page_view")
    # percentile_approx 0.5 = mediana
    medians = pv.groupBy("page_type").agg(
        F.percentile_approx("time_on_page_seconds", 0.5).alias("_median_top")
    )
    df2 = df.join(medians, on="page_type", how="left")
    df2 = df2.withColumn(
        "time_on_page_seconds",
        F.when(
            (F.col("event_type") == "page_view")
            & F.col("time_on_page_seconds").isNull(),
            F.col("_median_top"),
        ).otherwise(F.col("time_on_page_seconds")),
    ).drop("_median_top")
    return df2


def normalize_urls(df: DataFrame) -> DataFrame:
    """Normaliza `page_url`: lowercase y elimina query string (?...)."""
    return df.withColumn(
        "page_url",
        F.when(
            F.col("page_url").isNotNull(),
            F.lower(F.split(F.col("page_url"), "\\?").getItem(0)),
        ),
    )


def normalize_country(df: DataFrame) -> DataFrame:
    """Asegura códigos de país en mayúsculas (idempotente)."""
    return df.withColumn(
        "country",
        F.when(F.col("country").isNotNull(), F.upper(F.col("country"))),
    )


def clean_events(df: DataFrame) -> DataFrame:
    """Pipeline completo de limpieza."""
    return (
        df.transform(deduplicate_events)
        .transform(impute_country)
        .transform(impute_device_type)
        .transform(impute_time_on_page)
        .transform(normalize_urls)
        .transform(normalize_country)
    )
