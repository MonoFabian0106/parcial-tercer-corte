"""Cambia las columnas dt de DATE a VARCHAR(10) en todas las tablas fact_*
para que el Glue Visual Job pueda escribir directamente sin conversión.

Glue ApplyMapping en visual editor no convierte string -> date correctamente
con los datos particionados de Parquet.
"""

import os
from pathlib import Path

import psycopg2

# Cargar .env.local
env_file = Path(__file__).parent.parent / ".env.local"
for line in env_file.read_text().splitlines():
    line = line.strip()
    if line and not line.startswith("#") and "=" in line:
        k, v = line.split("=", 1)
        os.environ[k] = v

conn = psycopg2.connect(
    host=os.environ["DB_HOST"],
    port=int(os.environ.get("DB_PORT", 5432)),
    dbname=os.environ["DB_NAME"],
    user=os.environ["DB_USER"],
    password=os.environ["DB_PASSWORD"],
    sslmode="require",
)

fact_tables = [
    "fact_top_pages",
    "fact_bounce_rate",
    "fact_conversion_funnel",
    "fact_product_gap",
    "fact_nav_paths",
    "fact_device_country",
    "fact_anomalies",
]

with conn.cursor() as cur:
    # 1. Drop FKs hacia dim_date
    for tbl in fact_tables:
        fk_name_query = f"""
            SELECT conname FROM pg_constraint
            WHERE conrelid = '{tbl}'::regclass AND contype = 'f'
        """
        cur.execute(fk_name_query)
        for (fk,) in cur.fetchall():
            print(f"[{tbl}] DROP CONSTRAINT {fk}")
            cur.execute(f"ALTER TABLE {tbl} DROP CONSTRAINT {fk}")

    # 2. Alter dt columns to VARCHAR(10)
    for tbl in fact_tables:
        print(f"[{tbl}] ALTER dt TYPE VARCHAR(10)")
        cur.execute(f"ALTER TABLE {tbl} ALTER COLUMN dt TYPE VARCHAR(10) USING dt::text")

conn.commit()
conn.close()
print("\n[OK] Todas las columnas dt convertidas a VARCHAR(10).")
print("     Las FKs se eliminaron — la integridad referencial se valida en Spark.")
