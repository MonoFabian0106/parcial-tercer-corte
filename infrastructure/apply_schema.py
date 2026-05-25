"""apply_schema.py — Crea tablas DWH en RDS y puebla dim_date.

Uso:
    uv run python infrastructure/apply_schema.py

Variables de entorno necesarias (de .env.local):
    DB_HOST, DB_PORT (default 5432), DB_NAME, DB_USER, DB_PASSWORD
"""

from __future__ import annotations

import os
import sys
from datetime import date, timedelta
from pathlib import Path

import psycopg2
from psycopg2 import sql


def get_conn():
    return psycopg2.connect(
        host=os.environ["DB_HOST"],
        port=int(os.environ.get("DB_PORT", 5432)),
        dbname=os.environ["DB_NAME"],
        user=os.environ["DB_USER"],
        password=os.environ["DB_PASSWORD"],
        connect_timeout=10,
        sslmode="require",
    )


def apply_ddl(conn) -> None:
    schema_path = Path(__file__).parent / "dwh_schema.sql"
    ddl = schema_path.read_text(encoding="utf-8")
    with conn.cursor() as cur:
        cur.execute(ddl)
    conn.commit()
    print("[OK] DDL aplicado — tablas creadas/verificadas.")


def populate_dim_date(conn, start: date, end: date) -> int:
    """Inserta filas en dim_date para el rango [start, end]."""
    rows = []
    d = start
    while d <= end:
        rows.append((
            d.isoformat(),
            d.year,
            d.month,
            d.day,
            d.weekday(),            # 0=Mon … 6=Sun
            bool(d.weekday() >= 5), # is_weekend
            d.isocalendar()[1],    # week_of_year
        ))
        d += timedelta(days=1)

    with conn.cursor() as cur:
        cur.executemany(
            """
            INSERT INTO dim_date(dt, year, month, day, day_of_week, is_weekend, week_of_year)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (dt) DO NOTHING
            """,
            rows,
        )
    conn.commit()
    print(f"[OK] dim_date poblada: {len(rows)} filas ({start} -> {end}).")
    return len(rows)


def main() -> int:
    missing = [v for v in ("DB_HOST", "DB_NAME", "DB_USER", "DB_PASSWORD") if not os.environ.get(v)]
    if missing:
        print(f"[ERROR] Variables de entorno faltantes: {missing}")
        print("  Exporta desde .env.local o pasa como env vars.")
        return 1

    print(f"==> Conectando a {os.environ['DB_HOST']}:{os.environ.get('DB_PORT',5432)}/{os.environ['DB_NAME']}...")
    try:
        conn = get_conn()
    except Exception as e:
        print(f"[ERROR] No se pudo conectar: {e}")
        return 1

    print("[OK] Conexión exitosa.")
    apply_ddl(conn)

    # Puebla dim_date para 2026 completo (cubre todos los datos del proyecto)
    populate_dim_date(conn, date(2026, 1, 1), date(2026, 12, 31))

    conn.close()
    print("\n==> Schema listo. Próximo paso: ejecutar el Crawler Glue.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
