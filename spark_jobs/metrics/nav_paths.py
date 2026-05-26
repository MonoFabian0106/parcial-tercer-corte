"""Top 10 rutas de navegación: secuencias de `page_type` más comunes por sesión."""

from __future__ import annotations

from pyspark.sql import DataFrame
from pyspark.sql import functions as F


def compute(events: DataFrame, top_n: int = 10, max_path_length: int = 10) -> DataFrame:
    """Devuelve columnas: `dt, path, sessions, avg_path_length`.

    Limita la longitud de cada ruta a `max_path_length` para mantener el conteo
    interpretable (sesiones de bot-like generan rutas de 100+ pasos).
    """
    page_views = events.filter(F.col("event_type") == "page_view")

    # Ordenar por timestamp y armar la secuencia de page_types por sesión
    sequences = (
        page_views.groupBy("dt", "session_id")
        .agg(
            F.sort_array(F.collect_list(F.struct(F.col("event_ts"), F.col("page_type")))).alias(
                "ts_pt_list"
            )
        )
        .withColumn(
            "path_list",
            F.expr(f"slice(transform(ts_pt_list, x -> x.page_type), 1, {max_path_length})"),
        )
        .withColumn("path", F.concat_ws("->", F.col("path_list")))
        .withColumn("path_length", F.size(F.col("path_list")))
        .drop("ts_pt_list")
    )

    # Agrupar por ruta y contar
    from pyspark.sql import Window

    aggregated = sequences.groupBy("dt", "path").agg(
        F.count("*").alias("sessions"),
        F.avg("path_length").alias("avg_path_length"),
    )

    w = Window.partitionBy("dt").orderBy(F.desc("sessions"))
    return (
        aggregated.withColumn("rank", F.row_number().over(w))
        .filter(F.col("rank") <= top_n)
        .withColumn("avg_path_length", F.round(F.col("avg_path_length"), 2))
        .drop("rank")
        .orderBy("dt", F.desc("sessions"))
    )
