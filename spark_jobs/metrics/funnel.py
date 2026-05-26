"""Embudo de conversión: page_view → product_view → cart_event → compra.

Una sesión "compra completada" se detecta como page_view con `page_type='checkout'`
(coincidente con el generador). El recuento es a nivel de SESIÓN, no usuario,
para reflejar el comportamiento por visita.
"""

from __future__ import annotations

from pyspark.sql import DataFrame
from pyspark.sql import functions as F


def compute(events: DataFrame) -> DataFrame:
    """Devuelve un DataFrame con la cuenta de sesiones por etapa del embudo.

    Columnas: `dt, stage, sessions, conversion_rate_from_previous, conversion_rate_overall`.
    """
    # Stage flags por sesión (al menos uno del tipo correspondiente)
    per_session = events.groupBy("dt", "session_id").agg(
        F.max(F.when(F.col("event_type") == "page_view", 1).otherwise(0)).alias("has_pv"),
        F.max(F.when(F.col("event_type") == "product_view", 1).otherwise(0)).alias("has_prod"),
        F.max(
            F.when((F.col("event_type") == "cart_event") & (F.col("action") == "add"), 1).otherwise(
                0
            )
        ).alias("has_cart"),
        F.max(
            F.when(
                (F.col("event_type") == "page_view") & (F.col("page_type") == "checkout"),
                1,
            ).otherwise(0)
        ).alias("has_purchase"),
    )

    aggregated = per_session.groupBy("dt").agg(
        F.sum("has_pv").alias("page_view"),
        F.sum("has_prod").alias("product_view"),
        F.sum("has_cart").alias("cart_event"),
        F.sum("has_purchase").alias("purchase"),
    )

    # Convertimos a formato largo (un row por etapa) para facilitar el análisis downstream
    stages_df = aggregated.selectExpr(
        "dt",
        "stack(4, "
        "'page_view', page_view, "
        "'product_view', product_view, "
        "'cart_event', cart_event, "
        "'purchase', purchase"
        ") as (stage, sessions)",
    )

    # Calculamos tasas referenciando la columna `page_view` como base
    base = aggregated.select("dt", "page_view").withColumnRenamed("page_view", "_base_pv")
    stages_df = stages_df.join(base, on="dt", how="left")

    # Orden lógico del embudo
    stage_order_expr = (
        F.when(F.col("stage") == "page_view", 1)
        .when(F.col("stage") == "product_view", 2)
        .when(F.col("stage") == "cart_event", 3)
        .when(F.col("stage") == "purchase", 4)
    )
    stages_df = stages_df.withColumn("stage_order", stage_order_expr)

    # Tasa global (etapa / page_view base)
    stages_df = stages_df.withColumn(
        "conversion_rate_overall",
        F.round(F.col("sessions") / F.col("_base_pv"), 4),
    ).drop("_base_pv")

    # Tasa vs etapa previa (window por dt ordenado por stage_order)
    from pyspark.sql import Window

    w_prev = Window.partitionBy("dt").orderBy("stage_order")
    stages_df = stages_df.withColumn("_prev", F.lag("sessions").over(w_prev))
    stages_df = stages_df.withColumn(
        "conversion_rate_from_previous",
        F.when(
            F.col("_prev").isNotNull(), F.round(F.col("sessions") / F.col("_prev"), 4)
        ).otherwise(F.lit(1.0)),
    ).drop("_prev")

    return stages_df.orderBy("dt", "stage_order").drop("stage_order")
