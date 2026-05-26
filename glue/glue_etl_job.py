"""ShopStream Glue ETL Job — S3 Parquet metrics → RDS PostgreSQL.

Este script es equivalente al Visual ETL de Glue Studio pero ejecutable
directamente vía spark-submit en Glue (y también como referencia para el job visual).

Parámetros del job (se pasan en --arguments al crear/lanzar el job):
    --RUN_DATE          YYYY-MM-DD o 'all'
    --DB_HOST           endpoint RDS
    --DB_NAME           nombre de la base de datos (shopstream_dwh)
    --DB_USER           usuario
    --DB_PASSWORD       contraseña
    --CATALOG_DB        nombre de la Glue Database (shopstream_metrics_db)
    --PROCESSED_BUCKET  nombre del bucket S3 procesado (sin s3://)
    --METRIC            (opcional) nombre de métrica específica para procesar solo una
"""

from __future__ import annotations

import sys

from awsglue.context import GlueContext
from awsglue.job import Job
from awsglue.transforms import ApplyMapping
from awsglue.utils import getResolvedOptions
from pyspark.context import SparkContext

args = getResolvedOptions(
    sys.argv,
    [
        "JOB_NAME",
        "RUN_DATE",
        "DB_HOST",
        "DB_NAME",
        "DB_USER",
        "DB_PASSWORD",
        "CATALOG_DB",
        "PROCESSED_BUCKET",
    ],
)

sc = SparkContext()
glueContext = GlueContext(sc)
spark = glueContext.spark_session
job = Job(glueContext)
job.init(args["JOB_NAME"], args)

RUN_DATE = args["RUN_DATE"]  # YYYY-MM-DD o 'all'
DB_HOST = args["DB_HOST"]
DB_NAME = args["DB_NAME"]
DB_USER = args["DB_USER"]
DB_PASSWORD = args["DB_PASSWORD"]
CATALOG_DB = args["CATALOG_DB"]
PROC_BUCKET = args["PROCESSED_BUCKET"]

JDBC_URL = f"jdbc:postgresql://{DB_HOST}:5432/{DB_NAME}"

# ── Configuración por métrica ───────────────────────────────
# catalog_table → (rds_table, mappings)
# Mappings: (source_col, source_type, target_col, target_type)

METRICS = {
    "top_pages": (
        "fact_top_pages",
        [
            ("dt", "string", "dt", "date"),
            ("page_url", "string", "page_url", "string"),
            ("page_type", "string", "page_type", "string"),
            ("views", "long", "views", "int"),
            ("avg_time_on_page", "double", "avg_time_on_page", "double"),
            ("p95_time_on_page", "double", "p95_time_on_page", "double"),
        ],
    ),
    "bounce_rate": (
        "fact_bounce_rate",
        [
            ("dt", "string", "dt", "date"),
            ("landing_page_type", "string", "landing_page_type", "string"),
            ("total_sessions", "long", "total_sessions", "int"),
            ("bounce_sessions", "long", "bounce_sessions", "int"),
            ("bounce_rate", "double", "bounce_rate", "double"),
        ],
    ),
    "funnel": (
        "fact_conversion_funnel",
        [
            ("dt", "string", "dt", "date"),
            ("stage", "string", "stage", "string"),
            ("sessions", "long", "sessions", "int"),
            ("conversion_rate_from_previous", "double", "conversion_rate_from_previous", "double"),
            ("conversion_rate_overall", "double", "conversion_rate_overall", "double"),
        ],
    ),
    "product_gap": (
        "fact_product_gap",
        [
            ("dt", "string", "dt", "date"),
            ("product_id", "string", "product_id", "string"),
            ("category", "string", "category", "string"),
            ("views", "long", "views", "int"),
            ("cart_adds", "long", "cart_adds", "int"),
            ("conversion", "double", "conversion", "double"),
            ("gap_score", "double", "gap_score", "double"),
        ],
    ),
    "nav_paths": (
        "fact_nav_paths",
        [
            ("dt", "string", "dt", "date"),
            ("path", "string", "path", "string"),
            ("sessions", "long", "sessions", "int"),
            ("avg_path_length", "double", "avg_path_length", "double"),
        ],
    ),
    "device_country": (
        "fact_device_country",
        [
            ("dt", "string", "dt", "date"),
            ("device_type", "string", "device_type", "string"),
            ("country", "string", "country", "string"),
            ("page_views", "long", "page_views", "int"),
            ("avg_time_on_page", "double", "avg_time_on_page", "double"),
            ("p95_time_on_page", "double", "p95_time_on_page", "double"),
            ("unique_sessions", "long", "unique_sessions", "int"),
        ],
    ),
    "anomalies": (
        "fact_anomalies",
        [
            ("dt", "string", "dt", "date"),
            ("session_id", "string", "session_id", "string"),
            ("user_id", "string", "user_id", "string"),
            ("total_events", "long", "total_events", "int"),
            ("session_duration_seconds", "double", "session_duration_seconds", "double"),
            ("unique_pages", "long", "unique_pages", "int"),
            ("events_per_minute", "double", "events_per_minute", "double"),
            ("z_total_events", "double", "z_total_events", "double"),
            ("z_session_duration_seconds", "double", "z_session_duration_seconds", "double"),
            ("z_unique_pages", "double", "z_unique_pages", "double"),
            ("z_events_per_minute", "double", "z_events_per_minute", "double"),
            ("total_flags", "long", "total_flags", "short"),
            ("anomaly_type", "string", "anomaly_type", "string"),
        ],
    ),
}

# ── Reglas DQDL mínimas por métrica ─────────────────────────
DQ_RULES = {
    "top_pages": 'Rules = [ IsComplete "dt", IsComplete "page_url", ColumnValues "views" > 0 ]',
    "bounce_rate": 'Rules = [ IsComplete "dt", IsComplete "landing_page_type", ColumnValues "bounce_rate" between 0 and 1, ColumnValues "total_sessions" > 0 ]',
    "funnel": 'Rules = [ IsComplete "dt", IsComplete "stage", ColumnValues "sessions" >= 0 ]',
    "product_gap": 'Rules = [ IsComplete "dt", IsComplete "product_id", ColumnValues "views" >= 0 ]',
    "nav_paths": 'Rules = [ IsComplete "dt", IsComplete "path", ColumnValues "sessions" > 0 ]',
    "device_country": 'Rules = [ IsComplete "dt", IsComplete "device_type", IsComplete "country" ]',
    "anomalies": 'Rules = [ IsComplete "dt", IsComplete "session_id", ColumnValues "total_flags" >= 2 ]',
}

# ── Función de carga por métrica ─────────────────────────────


def load_metric(metric_name: str, rds_table: str, mappings: list) -> None:
    print(f"[{metric_name}] Leyendo desde Glue Catalog {CATALOG_DB}.{metric_name}...")

    dyf = glueContext.create_dynamic_frame.from_catalog(
        database=CATALOG_DB,
        table_name=metric_name,
        transformation_ctx=f"source_{metric_name}",
    )

    # Filtrar por fecha si se especificó
    if RUN_DATE and RUN_DATE != "all":
        dyf = dyf.filter(lambda r: r.get("dt") == RUN_DATE)

    row_count = dyf.count()
    print(f"[{metric_name}] Filas leídas: {row_count}")
    if row_count == 0:
        print(f"[{metric_name}] Sin datos para {RUN_DATE}. Saltando.")
        return

    # ── Nodo ChangeSchema (ApplyMapping) ────────────────────
    dyf_mapped = ApplyMapping.apply(
        frame=dyf,
        mappings=mappings,
        transformation_ctx=f"mapping_{metric_name}",
    )

    # ── Nodo Data Quality (EvaluateDataQuality) ─────────────
    dq_frame = glueContext.evaluate_data_quality(
        frame=dyf_mapped,
        ruleset=DQ_RULES[metric_name],
        publishing_options={
            "dataQualityEvaluationContext": f"dq_{metric_name}",
            "enableDataQualityResultsPublishing": True,
            "resultsS3Prefix": f"s3://{PROC_BUCKET}/glue-dq-results/",
        },
    )
    # evaluate_data_quality devuelve el frame original si pasa; lanza excepción si falla
    dyf_clean = dq_frame.select_from_dq_results(with_errors_frame=False)

    print(f"[{metric_name}] DQ OK. Escribiendo en RDS {rds_table}...")

    # ── Nodo Target PostgreSQL ───────────────────────────────
    glueContext.write_dynamic_frame.from_options(
        frame=dyf_clean,
        connection_type="jdbc",
        connection_options={
            "url": JDBC_URL,
            "dbtable": rds_table,
            "user": DB_USER,
            "password": DB_PASSWORD,
            "batchsize": "1000",
            # Truncate la partición dt antes de insertar (idempotente)
            "preactions": (
                f"DELETE FROM {rds_table} WHERE dt = '{RUN_DATE}'" if RUN_DATE != "all" else ""
            ),
        },
        transformation_ctx=f"sink_{metric_name}",
    )
    print(f"[{metric_name}] Cargado en {rds_table}. ✓")


# ── Main ─────────────────────────────────────────────────────
metric_filter = args.get("METRIC", "all") if "METRIC" in args else "all"

for name, (table, mapping) in METRICS.items():
    if metric_filter != "all" and name != metric_filter:
        continue
    try:
        load_metric(name, table, mapping)
    except Exception as exc:
        print(f"[ERROR] {name}: {exc}")
        raise  # Propaga para que Glue marque el job FAILED y dispare la alerta

job.commit()
print("==> Job completado exitosamente.")
