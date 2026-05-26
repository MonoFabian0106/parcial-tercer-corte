# ShopStream Pipeline

Pipeline batch end-to-end en AWS que procesa logs de comportamiento de usuarios de una tienda e-commerce ficticia (**ShopStream**). El pipeline cubre los 5 puntos del parcial: generación sintética de datos, ingesta validada con Lambda, transformación distribuida con PySpark sobre EMR, catalogación y orquestación con Glue (incluyendo un job visual con Data Quality), carga a RDS Postgres como datawarehouse y exposición vía API REST con Flask + Zappa.

> **Volumen**: ≥ 800,000 eventos/día. Backfill validado: 7 días (2026-05-16 → 2026-05-22) = 5.6M eventos / 1.6 GiB en S3.

---

## Tabla de contenidos

1. [Arquitectura](#arquitectura)
2. [Stack tecnológico](#stack-tecnológico)
3. [Prerrequisitos](#prerrequisitos)
4. [Setup local](#setup-local)
5. [Estructura del proyecto](#estructura-del-proyecto)
6. [Ejecución por fases](#ejecución-por-fases)
7. [Despliegue en AWS](#despliegue-en-aws)
8. [API REST](#api-rest)
9. [Tests y CI/CD](#tests-y-cicd)
10. [Limitaciones conocidas](#limitaciones-conocidas)

---

## Arquitectura

Diagrama completo en [`docs/arquitectura.md`](docs/arquitectura.md) (Mermaid). Resumen del flujo:

```
[Generator Python]
       │ JSON Lines particionado por año/mes/día
       ▼
[S3 raw] ── ObjectCreated:Put ──► [Lambda ingest]
                                       │ validación jsonschema línea-a-línea
                                       ├──► [S3 quarantine] (líneas inválidas + metadata)
                                       └──► [CloudWatch] (7 métricas custom)
       ▼
[EMR 7.0.0 + Spark 3.5.0]
       │ limpieza · 6 métricas agregadas · anomalías (z-score + IQR)
       ▼
[S3 processed] (Parquet snappy, partitioned by dt=YYYY-MM-DD)
       │
       ▼
[Glue Crawler] ──► [Glue Data Catalog: shopstream_metrics_db]
       │
       ▼
[Glue Studio Visual ETL Job + Data Quality (DQDL)]
       │  schedule: 0 2 * * ? *  (2:00 AM UTC diario)
       │  trigger ON_FAILURE ──► [Lambda alert] ──► [SNS email]
       ▼
[RDS Postgres 15: shopstream_dwh]  ◄── 7 facts + 3 dims
       │
       ▼
[Lambda Flask API (Zappa)] ──► [API Gateway] ──► [Cliente]
       └─ 3 endpoints REST: /pages/top, /sessions/summary, /anomalies
```

---

## Stack tecnológico

| Capa | Tecnología |
|---|---|
| Lenguaje | Python 3.11 |
| Gestor de entorno | UV (lockfile reproducible) |
| Generación datos | Faker · pandas · numpy · boto3 |
| Ingesta | AWS Lambda · jsonschema · CloudWatch Metrics |
| Procesamiento | PySpark 3.5.0 sobre EMR 7.0.0 (Spark 3.5.0, Python 3.9) |
| Catálogo / ETL visual | AWS Glue · Glue Studio · Data Quality DQDL |
| Datawarehouse | AWS RDS Postgres 15 (db.t3.micro) |
| API | Flask · Zappa · API Gateway · SQLAlchemy |
| Storage | S3 (raw · processed · quarantine · zappa-deploys) |
| Alertas | EventBridge · SNS · Email |
| Observabilidad | CloudWatch Dashboards + Logs |
| Tests | pytest · pytest-cov · moto |
| Calidad | ruff · black · mypy |
| CI/CD | GitHub Actions (tests + deploy manual) |

---

## Prerrequisitos

- **Python 3.11** (no 3.12 — `pyproject.toml` limita la versión por compatibilidad con EMR).
- [**UV**](https://github.com/astral-sh/uv) ≥ 0.10 como gestor de entorno y dependencias.
- **AWS CLI v2** configurado con credenciales del AWS Academy Learner Lab.
- **Git** y cuenta GitHub.
- **PowerShell 7+** (Windows) o Bash (Linux/macOS) para los scripts en `infrastructure/`.
- (Opcional) Java 11 si quieres correr PySpark localmente — no es necesario porque el ETL corre en EMR real.

---

## Setup local

```powershell
# 1. Clonar e instalar dependencias
git clone https://github.com/MonoFabian0106/parcial-tercer-corte.git shopstream-pipeline
cd shopstream-pipeline
uv sync --all-extras --group dev

# 2. Variables de entorno
Copy-Item .env.example .env.local
# Editar .env.local con: endpoint de RDS, credenciales de DB, nombres reales de buckets

# 3. Verificar credenciales AWS
aws sts get-caller-identity
```

> Las dependencias se separan por extra (`generation`, `lambda-ingest`, `spark`, `api`) para mantener los paquetes Lambda livianos. `uv sync --all-extras` instala todo para desarrollo.

---

## Estructura del proyecto

```
shopstream-pipeline/
├── .github/workflows/         # CI/CD
│   ├── tests.yml              # lint + pytest en push/PR
│   └── deploy.yml             # workflow_dispatch manual (3 jobs)
├── data_generation/           # ─── Punto 1 ───
│   ├── schemas.py             # 5 esquemas JSON con jsonschema
│   ├── generator.py           # Faker + distribuciones realistas
│   └── uploader.py            # subida particionada año/mes/día a S3
├── lambda_ingest/             # ─── Punto 2 ───
│   ├── handler.py             # entry-point S3 PutObject trigger
│   └── validator.py           # streaming validation + quarantine logic
├── spark_jobs/                # ─── Punto 3 ───
│   ├── etl_main.py            # spark-submit entrypoint
│   ├── session.py             # SparkSession builder
│   ├── cleaning.py            # dedup · imputación · normalización
│   ├── metrics/               # 6 métricas agregadas + anomalías
│   └── notebooks/             # exploratory.ipynb (EMR Studio)
├── glue/                      # ─── Punto 4 ───
│   ├── glue_etl_job.py        # script ETL programático
│   ├── etl_visual_job.json    # nodos del Glue Studio visual
│   └── data_quality_rules.txt # reglas DQDL
├── api/                       # ─── Punto 5 ───
│   ├── app.py                 # Flask + blueprints
│   ├── db.py                  # SQLAlchemy + connection pooling
│   ├── validators.py          # input validation (400 handling)
│   └── endpoints/             # 3 endpoints (pages, sessions, anomalies)
├── infrastructure/            # Scripts PowerShell + SQL para AWS CLI
│   ├── dwh_schema.sql         # DDL: 7 facts + 3 dims + índices
│   ├── create_rds.ps1         # provisionar RDS Postgres
│   ├── setup_glue*.ps1        # crawler · connection · job · workflow
│   ├── package_lambda.ps1     # cross-compile linux x86_64
│   └── ...                    # ver carpeta completa
├── tests/                     # 99 tests (8 archivos)
├── docs/                      # ci_cd.md · arquitectura.md
├── pyproject.toml             # deps + ruff + black + pytest config
├── zappa_settings.json        # config Zappa (profile_name=null para CI)
├── .env.example               # template de variables
└── README.md
```

---

## Ejecución por fases

> El plan completo paso-a-paso (incluyendo *console steps* de AWS) está en `../PLAN.md`.

### Punto 1 — Generar datos sintéticos

```powershell
# Un día
uv run python -m data_generation.generator --date 2026-05-22 --upload

# Backfill (7-14 días)
uv run python -m data_generation.generator --start 2026-05-16 --end 2026-05-22 --upload
```

Sale 1 archivo `.jsonl` por día con ~800k eventos, subido a `s3://shopstream-raw-mf0106/events/year=2026/month=05/day=DD/`.

### Punto 2 — Lambda de ingesta

Se dispara automáticamente al subir un `.jsonl` a S3. Para re-desplegarla manualmente:

```powershell
.\infrastructure\package_lambda.ps1            # cross-compile linux x86_64 → dist/lambda.zip
aws lambda update-function-code `
  --function-name shopstream-ingest-validator `
  --zip-file fileb://dist/shopstream-ingest-validator.zip
```

### Punto 3 — ETL Spark en EMR

```powershell
# 1. Subir el script al bucket processed
aws s3 sync spark_jobs/ s3://shopstream-processed-mf0106/code/ --exclude "notebooks/*"

# 2. Lanzar como step en el cluster EMR
aws emr add-steps `
  --cluster-id j-1ZROIAA4M7P2Q `
  --steps file://infrastructure/emr_step_etl.json
```

El job genera 7 carpetas Parquet en `s3://shopstream-processed-mf0106/metrics/<metric>/dt=YYYY-MM-DD/`. Tiempo medido: **5m 53s** para 800k eventos / 1 día.

### Punto 4 — Glue + RDS

```powershell
# 1. Crear esquema DWH en RDS (idempotente)
uv run python infrastructure/apply_schema.py

# 2. Crear/actualizar Crawler, Connection, Job y Workflow
.\infrastructure\setup_glue.ps1
.\infrastructure\setup_glue_job.ps1
.\infrastructure\setup_glue_workflow.ps1
.\infrastructure\setup_sns_alert.ps1

# 3. Disparar el workflow manualmente (también corre por schedule)
aws glue start-workflow-run --name shopstream-daily-pipeline
```

### Punto 5 — API local (debug)

```powershell
$env:DB_HOST="<rds-endpoint>"; $env:DB_PASSWORD="..."
uv run flask --app api.app run --debug
# http://127.0.0.1:5000/health
```

---

## Despliegue en AWS

### API (Zappa)

```powershell
# Primer deploy
uv run zappa deploy dev

# Actualizaciones
uv run zappa update dev

# Status / URL de API Gateway
uv run zappa status dev
```

URL actual: `https://fc5asg19kf.execute-api.us-east-1.amazonaws.com/dev`

### CI/CD automatizado

Ver [`docs/ci_cd.md`](docs/ci_cd.md). Resumen:

- **CI**: `tests.yml` corre en cada `push`/`pull_request` (lint + pytest + coverage).
- **CD**: `deploy.yml` con trigger `workflow_dispatch` (manual). Inputs: `component = all | lambda-ingest | spark-script | api`.
- Branch protection activa en `main`: no se puede pushear directo, sólo vía PR con 3 status checks verdes.

---

## API REST

Base URL: `https://fc5asg19kf.execute-api.us-east-1.amazonaws.com/dev`

| Método | Path | Query params | Descripción |
|---|---|---|---|
| `GET` | `/health` | — | Liveness probe |
| `GET` | `/pages/top` | `metric=time_on_page\|bounce_rate` · `date=YYYY-MM-DD` · `limit=N` | Top páginas por métrica |
| `GET` | `/sessions/summary` | `date=YYYY-MM-DD` · `country?` · `device?` | Resumen agregado de sesiones |
| `GET` | `/anomalies` | `date=YYYY-MM-DD` | Sesiones marcadas como anómalas (z-score + IQR) |

Códigos de error: `400` en parámetros inválidos, `404` si no hay datos para esa fecha, `500` en errores de DB.

Ejemplo:

```bash
curl "https://fc5asg19kf.execute-api.us-east-1.amazonaws.com/dev/pages/top?metric=bounce_rate&date=2026-05-22&limit=5"
```

---

## Tests y CI/CD

### Ejecutar tests localmente

```powershell
uv run pytest                       # todos los tests
uv run pytest --cov                 # con coverage
uv run pytest tests/test_api.py -v  # módulo específico
```

### Cobertura por módulo (última corrida)

| Módulo | Tests | Coverage |
|---|---|---|
| `data_generation/` | 51 | 80% |
| `lambda_ingest/` | 13 | ~85% |
| `api/` | 21 | 86% (endpoints 100%) |
| `glue` + RDS (integración) | 14 | n/a |
| **Total** | **99** | **≥ 70%** ✅ |

### Lint

```powershell
uv run ruff check .
uv run black --check .
```

---

## Limitaciones conocidas

| Limitación | Workaround |
|---|---|
| Credenciales del AWS Academy Learner Lab caducan cada ~4h | Refrescar secretos de GitHub antes de cada deploy (`AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_SESSION_TOKEN`). Deploy CD es manual por esta razón. |
| No se pueden crear roles IAM nuevos | Todo el pipeline usa el rol preconfigurado `LabRole`. Zappa con `manage_roles: false`. |
| RDS expuesta a `0.0.0.0/0` | Aceptable sólo para el lab. En producción restringir el SG a las IPs/SGs de Glue y Lambda. |
| EMR cluster se factura por hora | Auto-terminate por idle 1h configurado. Igual conviene terminar manualmente al cerrar sesión. |
| Account ID y endpoint RDS hardcoded en `deploy.yml` y `infrastructure/` | Cambiarlos al hacer fork del proyecto. |
| `pyspark` no se testea en CI (requiere JDK) | Validado contra EMR real — ver PLAN.md §3.10. |
| `pandas` y `pyspark` excluidos del bundle Zappa | El paquete `api` no los necesita; se excluyen en `zappa_settings.json` para mantener el zip < 50 MiB. |

---

## Licencia

Proyecto académico — Big Data, Noveno Semestre, Universidad Sergio Arboleda.
