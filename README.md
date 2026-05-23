# ShopStream Pipeline

Pipeline batch en AWS que procesa logs de comportamiento de usuarios de una tienda e-commerce ficticia (**ShopStream**): validacion con Lambda, transformaciones con PySpark sobre EMR, catalogacion y orquestacion con Glue, almacenamiento en RDS Postgres y exposicion via API REST con Lambda + Zappa.

## Arquitectura

```
[Generator] -> [S3 raw] -> [Lambda ingest] -> [S3 quarantine si invalido]
                  |
              [EMR Spark ETL] -> [S3 processed Parquet]
                  |
              [Glue Crawler] -> [Glue Catalog]
                  |
        [Glue Studio Visual Job + Data Quality]
                  |
              [RDS Postgres DWH]
                  |
        [Lambda Flask API (Zappa)] -> [API Gateway] -> [Cliente]
```

## Stack tecnologico

| Capa | Tecnologia |
|---|---|
| Lenguaje | Python 3.11 |
| Gestor de entorno | UV |
| Generacion datos | Faker, pandas, numpy |
| Ingesta | AWS Lambda + jsonschema |
| Procesamiento | PySpark 3.5.0 sobre EMR 7.0.0 |
| Catalogo / ETL | AWS Glue + Glue Studio (visual) |
| Datawarehouse | AWS RDS Postgres 15 |
| API | Flask + Zappa + API Gateway |
| Storage | S3 (raw, processed, quarantine) |
| Observabilidad | CloudWatch + SNS |
| Tests | pytest + moto |
| CI/CD | GitHub Actions |

## Prerrequisitos

- Python 3.11
- [UV](https://github.com/astral-sh/uv) >= 0.10
- AWS CLI v2 configurado con cuenta AWS Academy (Learner Lab activo)
- Git
- Cuenta GitHub
- (Opcional) Docker para empaquetar Lambdas

## Setup local

```powershell
git clone <repo-url>
cd shopstream-pipeline
uv sync --all-extras --group dev
Copy-Item .env.example .env.local
# Editar .env.local con valores reales
```

## Estructura del proyecto

```
shopstream-pipeline/
|-- .github/workflows/      # CI/CD (tests + deploy)
|-- data_generation/        # Punto 1: esquemas + generador sintetico
|-- lambda_ingest/          # Punto 2: validacion S3 events
|-- spark_jobs/             # Punto 3: ETL PySpark en EMR
|   |-- notebooks/          # Notebooks EMR Studio
|   `-- metrics/            # Calculo de metricas individuales
|-- glue/                   # Punto 4: configs Glue Studio + DQDL
|-- api/                    # Punto 5: Flask + Zappa
|   `-- endpoints/          # Blueprints de los 3 endpoints
|-- infrastructure/         # Scripts auxiliares para AWS (CLI)
|-- tests/                  # Tests unitarios pytest
|-- docs/                   # Diagramas y documentacion adicional
|-- pyproject.toml          # Definicion del proyecto + deps
`-- README.md
```

## Ejecucion por fases

Cada fase del pipeline esta documentada en `../PLAN.md` con los pasos detallados.

### Punto 1 - Generar datos sinteticos

```powershell
uv run python -m data_generation.generator --date 2026-05-22 --upload
```

### Punto 3 - ETL Spark (local para tests)

```powershell
uv run spark-submit spark_jobs/etl_main.py --input data/raw/ --output data/processed/ --date 2026-05-22
```

### Punto 5 - API local

```powershell
uv run flask --app api.app run --debug
```

### Despliegue API a AWS (Zappa)

```powershell
uv run zappa deploy dev
# Actualizaciones
uv run zappa update dev
```

## Tests

```powershell
uv run pytest
uv run pytest --cov
```

## Limitaciones conocidas

- **Cuenta AWS Academy**: las credenciales caducan cada 4 horas; el `Learner Lab` debe estar iniciado.
- **Roles IAM**: solo se usa el rol preconfigurado `LabRole`. No se crean roles nuevos.
- **EMR Cluster**: terminar manualmente despues de cada sesion para evitar gasto de creditos.
- **RDS publica**: el security group permite acceso 0.0.0.0/0 unicamente para fines del lab; restringir en produccion.

## Licencia

Proyecto academico - Big Data - Noveno Semestre - Universidad Sergio Arboleda.
