"""CLI del generador de datos sintéticos.

Uso:
    # Generar un día específico (sin subir)
    uv run python -m data_generation --date 2026-05-22

    # Generar y subir a S3
    uv run python -m data_generation --date 2026-05-22 --upload

    # Backfill de varios días
    uv run python -m data_generation --start 2026-05-16 --end 2026-05-22 --upload

    # Configuración adicional
    uv run python -m data_generation --date 2026-05-22 \
        --target-events 800000 --users 50000 --products 2000 --seed 42
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

from data_generation.catalog import build_or_load_catalog
from data_generation.generator import GeneratorConfig, generate_day
from data_generation.uploader import upload_day

logger = logging.getLogger(__name__)


def _parse_date(value: str) -> date:
    return datetime.strptime(value, "%Y-%m-%d").date()


def _daterange(start: date, end: date):
    cur = start
    while cur <= end:
        yield cur
        cur += timedelta(days=1)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="data_generation", description=__doc__)
    # Date selection (mutually exclusive: single date OR start+end range)
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--date", type=_parse_date, help="Fecha única YYYY-MM-DD")
    g.add_argument("--start", type=_parse_date, help="Inicio del backfill YYYY-MM-DD")
    p.add_argument("--end", type=_parse_date, help="Fin del backfill (inclusive) YYYY-MM-DD")

    p.add_argument("--target-events", type=int, default=800_000)
    p.add_argument("--users", type=int, default=50_000)
    p.add_argument("--products", type=int, default=2_000)
    p.add_argument("--active-fraction", type=float, default=0.50)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument(
        "--catalog-dir",
        type=Path,
        default=Path("data/catalog"),
        help="Carpeta para users.jsonl y products.jsonl",
    )
    p.add_argument(
        "--output-dir",
        type=Path,
        default=Path("data/raw"),
        help="Carpeta local de salida para los JSONL diarios",
    )
    p.add_argument(
        "--rebuild-catalog",
        action="store_true",
        help="Regenerar el catálogo aunque ya exista en disco",
    )
    p.add_argument(
        "--upload",
        action="store_true",
        help="Subir cada archivo generado a S3 (requiere S3_BUCKET_RAW)",
    )
    p.add_argument("--bucket", type=str, default=None, help="Bucket S3 (overrides env)")
    p.add_argument("--log-level", default="INFO")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=args.log_level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    if args.date:
        dates = [args.date]
    else:
        if not args.end:
            logger.error("--start requiere también --end")
            return 2
        if args.end < args.start:
            logger.error("--end debe ser >= --start")
            return 2
        dates = list(_daterange(args.start, args.end))

    logger.info("Construyendo/cargando catálogo (%d users, %d products)", args.users, args.products)
    catalog = build_or_load_catalog(
        args.catalog_dir,
        n_users=args.users,
        n_products=args.products,
        seed=args.seed,
        rebuild=args.rebuild_catalog,
    )

    cfg = GeneratorConfig(
        target_events=args.target_events,
        seed=args.seed,
        active_user_fraction=args.active_fraction,
    )

    summary = {"days": [], "totals": {"events": 0, "sessions": 0}}
    bucket = args.bucket or os.environ.get("S3_BUCKET_RAW")

    for run_date in dates:
        out_path = args.output_dir / f"events_{run_date.isoformat()}.jsonl"
        logger.info("Generando %s -> %s", run_date, out_path)
        metrics = generate_day(run_date, catalog, cfg, out_path)
        logger.info(
            "Día %s: %d eventos, %d sesiones (bounce=%d, anómalas=%d)",
            run_date,
            metrics["total_events"],
            metrics["total_sessions"],
            metrics["bounce_sessions"],
            metrics["anomalous_sessions"],
        )
        summary["days"].append(metrics)
        summary["totals"]["events"] += metrics["total_events"]
        summary["totals"]["sessions"] += metrics["total_sessions"]

        if args.upload:
            if not bucket:
                logger.error("--upload sin bucket: define S3_BUCKET_RAW o pasa --bucket")
                return 3
            upload_meta = upload_day(out_path, run_date, bucket=bucket)
            logger.info("Subido: s3://%s/%s (%.1f MB)",
                        upload_meta["bucket"],
                        upload_meta["key"],
                        upload_meta["size_bytes"] / 1e6)

    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
