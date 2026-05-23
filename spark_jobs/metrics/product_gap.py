"""Productos más vistos vs más agregados al carrito (gap de conversión).

Identifica productos con alta vista pero baja conversión a carrito — candidatos
a mejora de precio, descripción o imagen.
"""

from __future__ import annotations

from pyspark.sql import DataFrame
from pyspark.sql import functions as F


def compute(events: DataFrame, min_views: int = 50, top_n: int = 50) -> DataFrame:
    """Devuelve columnas: `dt, product_id, category, views, cart_adds, gap_score`.

    `gap_score = 1 - (cart_adds / views)`. Productos con `views >= min_views`
    para evitar ruido de productos con muy pocas vistas.
    """
    pv = events.filter(F.col("event_type") == "product_view").groupBy(
        "dt", "product_id", "category"
    ).agg(F.count("*").alias("views"))

    carts = events.filter(
        (F.col("event_type") == "cart_event") & (F.col("action") == "add")
    ).groupBy("dt", "product_id").agg(F.count("*").alias("cart_adds"))

    joined = (
        pv.join(carts, on=["dt", "product_id"], how="left")
        .withColumn("cart_adds", F.coalesce(F.col("cart_adds"), F.lit(0)))
        .withColumn(
            "conversion",
            F.round(F.col("cart_adds") / F.col("views"), 4),
        )
        .withColumn(
            "gap_score",
            F.round(F.lit(1.0) - F.col("cart_adds") / F.col("views"), 4),
        )
        .filter(F.col("views") >= min_views)
        .orderBy(F.col("dt"), F.desc("gap_score"))
    )

    from pyspark.sql import Window

    w = Window.partitionBy("dt").orderBy(F.desc("gap_score"), F.desc("views"))
    return (
        joined.withColumn("rank", F.row_number().over(w))
        .filter(F.col("rank") <= top_n)
        .drop("rank")
    )
