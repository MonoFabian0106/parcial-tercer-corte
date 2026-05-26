"""Top 20 páginas por tiempo de permanencia promedio."""

from __future__ import annotations

from pyspark.sql import DataFrame, Window
from pyspark.sql import functions as F


def compute(events: DataFrame, top_n: int = 20) -> DataFrame:
    """Calcula las páginas con mayor `time_on_page_seconds` promedio.

    Sólo considera eventos `page_view`. Devuelve columnas:
    `dt, page_url, page_type, views, avg_time_on_page, p95_time_on_page`.
    """
    pv = events.filter(F.col("event_type") == "page_view")
    return (
        pv.groupBy("dt", "page_url", "page_type")
        .agg(
            F.count("*").alias("views"),
            F.avg("time_on_page_seconds").alias("avg_time_on_page"),
            F.percentile_approx("time_on_page_seconds", 0.95).alias("p95_time_on_page"),
        )
        .orderBy(F.col("dt"), F.desc("avg_time_on_page"))
        # Para "top_n por día" usamos un ranking en lugar de un limit global
        .withColumn(
            "rank",
            F.row_number().over(Window.partitionBy("dt").orderBy(F.desc("avg_time_on_page"))),
        )
        .filter(F.col("rank") <= top_n)
        .drop("rank")
    )
