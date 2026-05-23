"""ETL principal de ShopStream para ejecutar en EMR (spark-submit).

Uso local:
    uv run spark-submit spark_jobs/etl_main.py \\
        --input data/raw/ \\
        --output data/processed/metrics/ \\
        --date 2026-05-22

Uso en EMR Step:
    spark-submit s3://<bucket>/code/etl_main.py \\
        --input s3://shopstream-raw-mf0106/events/ \\
        --output s3://shopstream-processed-mf0106/metrics/ \\
        --date 2026-05-22

Si `--date all`, procesa todos los días encontrados.
"""

from __future__ import annotations

import argparse
import logging
import sys

from pyspark.sql import DataFrame
from pyspark.sql import functions as F

from spark_jobs.cleaning import clean_events
from spark_jobs.metrics import (
    anomalies,
    bounce_rate,
    device_country,
    funnel,
    nav_paths,
    product_gap,
    top_pages,
)
from spark_jobs.session import build_spark_session, read_events

logger = logging.getLogger(__name__)


METRIC_PIPELINE = {
    "top_pages": top_pages.compute,
    "bounce_rate": bounce_rate.compute,
    "funnel": funnel.compute,
    "product_gap": product_gap.compute,
    "nav_paths": nav_paths.compute,
    "device_country": device_country.compute,
    "anomalies": anomalies.compute,
}


def _input_glob(input_base: str, run_date: str | None) -> str:
    """Construye el path con glob para el día especificado o todos."""
    base = input_base.rstrip("/")
    if run_date and run_date != "all":
        y, m, d = run_date.split("-")
        return f"{base}/year={y}/month={m}/day={d}/*.jsonl"
    return f"{base}/year=*/month=*/day=*/*.jsonl"


def _write_metric(df: DataFrame, output_base: str, metric_name: str) -> None:
    """Escribe la métrica como Parquet particionado por `dt`."""
    output_path = f"{output_base.rstrip('/')}/{metric_name}"
    logger.info("Writing %s -> %s", metric_name, output_path)
    (
        df.coalesce(1)  # 1 archivo por partición (volumen bajo en métricas)
        .write.mode("overwrite")
        .partitionBy("dt")
        .parquet(output_path)
    )


def run(input_base: str, output_base: str, run_date: str | None) -> dict:
    spark = build_spark_session("shopstream-etl")
    spark.sparkContext.setLogLevel("WARN")

    input_path = _input_glob(input_base, run_date)
    logger.info("Reading events from %s", input_path)

    raw = read_events(spark, input_path)
    # Filtra por dt si se pasó --date (defensa adicional al glob)
    if run_date and run_date != "all":
        raw = raw.filter(F.col("dt") == F.lit(run_date))

    n_raw = raw.count()
    logger.info("Raw events: %d", n_raw)
    if n_raw == 0:
        logger.warning("No events to process. Exiting.")
        return {"events_processed": 0}

    clean = clean_events(raw).persist()  # reuso para múltiples métricas
    n_clean = clean.count()
    logger.info("After cleaning: %d events (deduped/imputed)", n_clean)

    summary = {"events_raw": n_raw, "events_clean": n_clean, "metrics": {}}

    for name, fn in METRIC_PIPELINE.items():
        logger.info("Computing %s", name)
        df = fn(clean)
        rows = df.count()
        summary["metrics"][name] = rows
        _write_metric(df, output_base, name)

    clean.unpersist()
    spark.stop()
    logger.info("Done. Summary: %s", summary)
    return summary


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--input", required=True, help="Base path de eventos raw (S3 o local)")
    p.add_argument("--output", required=True, help="Base path de salida para Parquet")
    p.add_argument(
        "--date",
        default="all",
        help="YYYY-MM-DD o 'all' (default: all)",
    )
    p.add_argument("--log-level", default="INFO")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=args.log_level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    run(args.input, args.output, args.date)
    return 0


if __name__ == "__main__":
    sys.exit(main())
