"""Tasa de rebote por tipo de página.

Una sesión "bounce" tiene exactamente UN `page_view`. La tasa de rebote por
`page_type` se calcula sobre el `page_type` de la página de aterrizaje (primer
page_view cronológico de la sesión).
"""

from __future__ import annotations

from pyspark.sql import DataFrame, Window
from pyspark.sql import functions as F


def compute(events: DataFrame) -> DataFrame:
    """Devuelve columnas: `dt, landing_page_type, total_sessions, bounce_sessions, bounce_rate`."""
    page_views = events.filter(F.col("event_type") == "page_view")

    # Por sesión: número de page_views + page_type de la primera página
    w_session = Window.partitionBy("session_id").orderBy(F.asc("event_ts"))
    landing = (
        page_views.withColumn("_rn", F.row_number().over(w_session))
        .filter(F.col("_rn") == 1)
        .select(
            F.col("dt"),
            F.col("session_id"),
            F.col("page_type").alias("landing_page_type"),
        )
    )

    pv_counts = page_views.groupBy("session_id").agg(F.count("*").alias("pv_count"))

    session_summary = landing.join(pv_counts, on="session_id", how="inner")

    return (
        session_summary.groupBy("dt", "landing_page_type")
        .agg(
            F.count("*").alias("total_sessions"),
            F.sum(F.when(F.col("pv_count") == 1, 1).otherwise(0)).alias("bounce_sessions"),
        )
        .withColumn(
            "bounce_rate",
            F.round(F.col("bounce_sessions") / F.col("total_sessions"), 4),
        )
        .orderBy("dt", "landing_page_type")
    )
