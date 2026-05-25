# run_phase4.ps1 — Orquestador completo de la Fase 4 (Glue + RDS)
#
# Pre-requisito ÚNICO manual: haber creado la instancia RDS desde la consola
# (o via create_rds.ps1) y tener el endpoint en .env.local.
#
# Uso:
#   1. Copia .env.example → .env.local y rellena DB_HOST, DB_USER, DB_PASSWORD
#   2. .\infrastructure\run_phase4.ps1 -Email tu@email.com
#
# Qué hace en orden:
#   Step 1 — Carga .env.local
#   Step 2 — Aplica DDL al RDS y puebla dim_date (apply_schema.py)
#   Step 3 — Crea Glue Database + Crawler + Connection (setup_glue.ps1)
#   Step 4 — Sube script ETL a S3 y crea el Glue Job (setup_glue_job.ps1)
#   Step 5 — Crea SNS topic + Lambda alert + EventBridge rule (setup_sns_alert.ps1)
#   Step 6 — Crea Workflow Glue con triggers condicionales (setup_glue_workflow.ps1)
#   Step 7 — Ejecuta el Crawler para poblar el Glue Catalog
#   Step 8 — Verifica que todo esté en pie

param(
    [Parameter(Mandatory=$true)]
    [string]$Email,
    [string]$ProcessedBucket = "shopstream-processed-mf0106",
    [string]$EnvFile         = ".env.local"
)

$ErrorActionPreference = "Stop"
$Region = "us-east-1"

function Step($n, $msg) { Write-Host "`n━━━ Step $n — $msg ━━━" -ForegroundColor Cyan }
function OK($msg)   { Write-Host "    [OK] $msg" -ForegroundColor Green }
function WARN($msg) { Write-Host "    [WARN] $msg" -ForegroundColor Yellow }
function ERR($msg)  { Write-Host "    [ERR] $msg" -ForegroundColor Red; exit 1 }

# ── Step 1: Cargar .env.local ────────────────────────────────
Step 1 "Cargando variables de entorno desde $EnvFile"

if (-not (Test-Path $EnvFile)) {
    ERR "$EnvFile no encontrado. Copia .env.example → .env.local y rellena los valores."
}

foreach ($line in Get-Content $EnvFile) {
    $line = $line.Trim()
    if ($line -match '^#' -or $line -eq '') { continue }
    if ($line -match '^([^=]+)=(.*)$') {
        [System.Environment]::SetEnvironmentVariable($Matches[1], $Matches[2], "Process")
    }
}

$required = @("DB_HOST","DB_NAME","DB_USER","DB_PASSWORD")
foreach ($v in $required) {
    if (-not [System.Environment]::GetEnvironmentVariable($v)) {
        ERR "Variable $v no definida en $EnvFile"
    }
}
OK "Variables cargadas (DB_HOST=$env:DB_HOST)"

# ── Step 2: Aplicar DDL al RDS ───────────────────────────────
Step 2 "Aplicando schema DWH y poblando dim_date"

.\.venv\Scripts\python.exe infrastructure\apply_schema.py
if ($LASTEXITCODE -ne 0) { ERR "apply_schema.py falló." }
OK "Schema DWH aplicado."

# ── Step 3: Glue Database + Crawler + Connection ─────────────
Step 3 "Creando recursos Glue (Database, Crawler, Connection)"

.\infrastructure\setup_glue.ps1 `
    -ProcessedBucket $ProcessedBucket `
    -DbHost  $env:DB_HOST `
    -DbUser  $env:DB_USER `
    -DbPassword $env:DB_PASSWORD
OK "Glue Database / Crawler / Connection creados."

# ── Step 4: Glue Job (script Python) ─────────────────────────
Step 4 "Subiendo script ETL a S3 y creando Glue Job"

.\infrastructure\setup_glue_job.ps1 `
    -ProcessedBucket $ProcessedBucket `
    -DbHost  $env:DB_HOST `
    -DbUser  $env:DB_USER `
    -DbPassword $env:DB_PASSWORD
OK "Glue Job shopstream-s3-to-rds listo."

# ── Step 5: SNS + Lambda alerta ──────────────────────────────
Step 5 "Creando SNS topic, Lambda alert y regla EventBridge"

.\infrastructure\setup_sns_alert.ps1 -Email $Email
OK "SNS + Lambda alerta configurados. Confirma el email de suscripción."

# ── Step 6: Glue Workflow + Triggers ─────────────────────────
Step 6 "Creando Workflow Glue con triggers (schedule + condicional)"

.\infrastructure\setup_glue_workflow.ps1
OK "Workflow shopstream-daily-pipeline creado."

# ── Step 7: Ejecutar Crawler ─────────────────────────────────
Step 7 "Iniciando Crawler para poblar el Glue Catalog"

aws glue start-crawler --name shopstream-metrics-crawler --region $Region 2>$null
Write-Host "    Crawler iniciado. Esperando hasta READY (puede tardar 2-5 min)..."

$maxWait = 360   # segundos
$waited  = 0
$interval = 15
do {
    Start-Sleep -Seconds $interval
    $waited += $interval
    $state = (aws glue get-crawler --name shopstream-metrics-crawler `
        --query "Crawler.State" --output text --region $Region)
    Write-Host "    [$waited s] Estado: $state"
} while ($state -ne "READY" -and $waited -lt $maxWait)

if ($state -eq "READY") {
    $lastStatus = (aws glue get-crawler --name shopstream-metrics-crawler `
        --query "Crawler.LastCrawl.Status" --output text --region $Region)
    if ($lastStatus -eq "SUCCEEDED") {
        OK "Crawler completó exitosamente."
    } else {
        WARN "Crawler terminó con estado: $lastStatus. Revisa la consola de Glue."
    }
} else {
    WARN "Crawler aún en estado $state después de $maxWait s. Verifica manualmente."
}

# ── Step 8: Verificación final ───────────────────────────────
Step 8 "Verificación final"

Write-Host "    Tablas en Glue Catalog:"
aws glue get-tables --database-name shopstream_metrics_db `
    --query "TableList[].Name" --output table --region $Region 2>$null

Write-Host "    Estado del Workflow:"
aws glue get-workflow --name shopstream-daily-pipeline `
    --query "Workflow.Name" --output text --region $Region 2>$null

Write-Host ""
Write-Host "╔══════════════════════════════════════════════════════════╗" -ForegroundColor Green
Write-Host "║  Fase 4 automatizada completada.                        ║" -ForegroundColor Green
Write-Host "║                                                          ║" -ForegroundColor Green
Write-Host "║  Pendiente SOLO en consola AWS:                         ║" -ForegroundColor Green
Write-Host "║  1. Glue Studio → crear Job Visual (usar etl_visual_    ║" -ForegroundColor Green
Write-Host "║     job.json como guía de nodos)                        ║" -ForegroundColor Green
Write-Host "║  2. Confirmar email de suscripción SNS                  ║" -ForegroundColor Green
Write-Host "║  3. Probar conexión: Glue > Connections > Test          ║" -ForegroundColor Green
Write-Host "╚══════════════════════════════════════════════════════════╝" -ForegroundColor Green
