"""Tiempo promedio en página por device_type × country."""

from __future__ import annotations

from pyspark.sql import DataFrame
from pyspark.sql import functions as F


def compute(events: DataFrame) -> DataFrame:
    """Devuelve columnas: `dt, device_type, country, page_views, avg_time_on_page, p95_time_on_page`."""
    pv = events.filter(F.col("event_type") == "page_view")
    return (
        pv.groupBy("dt", "device_type", "country")
        .agg(
            F.count("*").alias("page_views"),
            F.round(F.avg("time_on_page_seconds"), 2).alias("avg_time_on_page"),
            F.round(F.percentile_approx("time_on_page_seconds", 0.95), 2).alias("p95_time_on_page"),
            F.countDistinct("session_id").alias("unique_sessions"),
        )
        .orderBy("dt", "device_type", "country")
    )
