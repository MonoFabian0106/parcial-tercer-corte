"""Detección de sesiones anómalas usando z-score e IQR.

Para cada sesión calculamos 4 indicadores:
- `total_events`: número total de eventos
- `session_duration_seconds`: duración entre el primer y el último evento
- `unique_pages`: páginas únicas vistas
- `events_per_minute`: ritmo del usuario

Para cada indicador computamos z-score (basado en media y desviación estándar
de TODAS las sesiones del día) y los límites IQR (Q1 - 1.5*IQR, Q3 + 1.5*IQR).
Una sesión se marca como anómala si **al menos 2 indicadores** la flagean en
cualquiera de los dos métodos.
"""

from __future__ import annotations

from pyspark.sql import DataFrame, Window
from pyspark.sql import functions as F


Z_THRESHOLD = 3.0


def _session_features(events: DataFrame) -> DataFrame:
    """Resumen por sesión con los 4 indicadores."""
    pv = F.when(F.col("event_type") == "page_view", F.col("page_url"))
    return (
        events.groupBy("dt", "session_id", "user_id")
        .agg(
            F.count("*").alias("total_events"),
            F.countDistinct(pv).alias("unique_pages"),
            ((F.max("event_ts").cast("long") - F.min("event_ts").cast("long")).cast("double"))
            .alias("session_duration_seconds"),
        )
        .withColumn(
            "events_per_minute",
            F.when(
                F.col("session_duration_seconds") > 0,
                F.col("total_events") * 60.0 / F.col("session_duration_seconds"),
            ).otherwise(F.lit(0.0)),
        )
    )


def _zscore_flags(df: DataFrame, metrics: list[str]) -> DataFrame:
    """Añade columnas `_z_<metric>` y `flag_z_<metric>` por día."""
    w = Window.partitionBy("dt")
    out = df
    for m in metrics:
        mean_col = F.avg(F.col(m)).over(w)
        std_col = F.stddev(F.col(m)).over(w)
        z = F.when(
            (std_col.isNotNull()) & (std_col > 0),
            (F.col(m) - mean_col) / std_col,
        ).otherwise(F.lit(0.0))
        out = out.withColumn(f"z_{m}", F.round(z, 3))
        out = out.withColumn(
            f"flag_z_{m}",
            (F.abs(F.col(f"z_{m}")) > F.lit(Z_THRESHOLD)).cast("int"),
        )
    return out


def _iqr_flags(df: DataFrame, metrics: list[str]) -> DataFrame:
    """Añade columnas `flag_iqr_<metric>` por día."""
    # percentile_approx con array param devuelve array
    bounds = df.groupBy("dt").agg(
        *[
            F.percentile_approx(F.col(m), [0.25, 0.75]).alias(f"_q_{m}")
            for m in metrics
        ]
    )
    for m in metrics:
        bounds = bounds.withColumn(f"_q1_{m}", F.col(f"_q_{m}").getItem(0))
        bounds = bounds.withColumn(f"_q3_{m}", F.col(f"_q_{m}").getItem(1))
        bounds = bounds.withColumn(
            f"_iqr_{m}", F.col(f"_q3_{m}") - F.col(f"_q1_{m}")
        )
        bounds = bounds.withColumn(
            f"_lo_{m}", F.col(f"_q1_{m}") - 1.5 * F.col(f"_iqr_{m}")
        )
        bounds = bounds.withColumn(
            f"_hi_{m}", F.col(f"_q3_{m}") + 1.5 * F.col(f"_iqr_{m}")
        )
        bounds = bounds.drop(f"_q_{m}", f"_q1_{m}", f"_q3_{m}", f"_iqr_{m}")

    out = df.join(bounds, on="dt", how="left")
    for m in metrics:
        out = out.withColumn(
            f"flag_iqr_{m}",
            (
                (F.col(m) < F.col(f"_lo_{m}")) | (F.col(m) > F.col(f"_hi_{m}"))
            ).cast("int"),
        )
        out = out.drop(f"_lo_{m}", f"_hi_{m}")
    return out


def _anomaly_type(df: DataFrame) -> DataFrame:
    """Etiqueta heurística según qué indicador disparó."""
    return df.withColumn(
        "anomaly_type",
        F.when(F.col("flag_z_events_per_minute") + F.col("flag_iqr_events_per_minute") > 0,
               F.lit("high_velocity"))
        .when(F.col("flag_z_session_duration_seconds") + F.col("flag_iqr_session_duration_seconds") > 0,
              F.lit("extreme_duration"))
        .when(F.col("flag_z_total_events") + F.col("flag_iqr_total_events") > 0,
              F.lit("high_volume"))
        .when(F.col("flag_z_unique_pages") + F.col("flag_iqr_unique_pages") > 0,
              F.lit("extreme_breadth"))
        .otherwise(F.lit("other")),
    )


def compute(events: DataFrame) -> DataFrame:
    """Pipeline completo de detección de anomalías. Devuelve solo sesiones anómalas."""
    metrics = ["total_events", "session_duration_seconds", "unique_pages", "events_per_minute"]
    features = _session_features(events)
    z = _zscore_flags(features, metrics)
    flagged = _iqr_flags(z, metrics)

    # Total de banderas (z + iqr) por sesión
    flag_cols = [f"flag_z_{m}" for m in metrics] + [f"flag_iqr_{m}" for m in metrics]
    flagged = flagged.withColumn(
        "total_flags", sum(F.col(c) for c in flag_cols)
    )

    anomalies = flagged.filter(F.col("total_flags") >= 2)
    anomalies = _anomaly_type(anomalies)

    return anomalies.select(
        "dt",
        "session_id",
        "user_id",
        "total_events",
        "session_duration_seconds",
        "unique_pages",
        "events_per_minute",
        "z_total_events",
        "z_session_duration_seconds",
        "z_unique_pages",
        "z_events_per_minute",
        "total_flags",
        "anomaly_type",
    )
