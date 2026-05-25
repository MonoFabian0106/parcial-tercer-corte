# setup_glue_job.ps1 — Sube el script ETL a S3 y crea el Glue Job programáticamente
# Uso: .\infrastructure\setup_glue_job.ps1

param(
    [string]$ProcessedBucket = "shopstream-processed-mf0106",
    [string]$DbHost          = $env:DB_HOST,
    [string]$DbUser          = $env:DB_USER,
    [string]$DbPassword      = $env:DB_PASSWORD,
    [string]$DbName          = "shopstream_dwh"
)

$Region   = "us-east-1"
$JobName  = "shopstream-s3-to-rds"
$ScriptS3 = "s3://$ProcessedBucket/glue-scripts/glue_etl_job.py"

# ── 1. Subir script a S3 ─────────────────────────────────────
Write-Host "==> Subiendo script ETL a $ScriptS3..."
aws s3 cp glue\glue_etl_job.py $ScriptS3 --region $Region
Write-Host "    OK"

# ── 2. Crear (o actualizar) el Glue Job ──────────────────────
$ExistingJob = (aws glue get-job --job-name $JobName `
    --query "Job.Name" --output text --region $Region 2>$null)

$DefaultArgs = @{
    "--job-language"          = "python"
    "--job-bookmark-option"   = "job-bookmark-disable"
    "--enable-metrics"        = "true"
    "--enable-spark-ui"       = "true"
    "--spark-event-logs-path" = "s3://$ProcessedBucket/glue-spark-logs/"
    "--CATALOG_DB"            = "shopstream_metrics_db"
    "--PROCESSED_BUCKET"      = $ProcessedBucket
    "--DB_HOST"               = $DbHost
    "--DB_NAME"               = $DbName
    "--DB_USER"               = $DbUser
    "--DB_PASSWORD"           = $DbPassword
    "--RUN_DATE"              = "all"
} | ConvertTo-Json -Compress

if ($ExistingJob -eq $JobName) {
    Write-Host "==> Actualizando Job existente $JobName..."
    aws glue update-job --job-name $JobName --job-update `
        "{`"Role`":`"LabRole`",`"Command`":{`"Name`":`"glueetl`",`"ScriptLocation`":`"$ScriptS3`",`"PythonVersion`":`"3`"},`"GlueVersion`":`"4.0`",`"WorkerType`":`"G.1X`",`"NumberOfWorkers`":2,`"Timeout`":30,`"DefaultArguments`":$DefaultArgs}" `
        --region $Region | Out-Null
} else {
    Write-Host "==> Creando Job $JobName..."
    aws glue create-job `
        --name $JobName `
        --role LabRole `
        --command "{`"Name`":`"glueetl`",`"ScriptLocation`":`"$ScriptS3`",`"PythonVersion`":`"3`"}" `
        --glue-version "4.0" `
        --worker-type G.1X `
        --number-of-workers 2 `
        --timeout 30 `
        --default-arguments $DefaultArgs `
        --region $Region | Out-Null
}

Write-Host "    Job $JobName listo."
Write-Host ""
Write-Host "==> Para ejecutar manualmente un día específico:"
Write-Host "    aws glue start-job-run --job-name $JobName --arguments '{`"--RUN_DATE`":`"2026-05-22`"}' --region $Region"
