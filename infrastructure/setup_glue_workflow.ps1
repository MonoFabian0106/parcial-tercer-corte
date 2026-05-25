# setup_glue_workflow.ps1 — Crea el Workflow Glue con triggers condicionales y schedule
# Requiere: Crawler y Job ya creados, Lambda alert desplegada.
# Uso: .\infrastructure\setup_glue_workflow.ps1

param(
    [string]$AlertLambdaArn = $env:ALERT_LAMBDA_ARN
)

$Region       = "us-east-1"
$WorkflowName = "shopstream-daily-pipeline"
$CrawlerName  = "shopstream-metrics-crawler"
$JobName      = "shopstream-s3-to-rds"

# ── 1. Crear Workflow ────────────────────────────────────────
Write-Host "==> Creando Workflow $WorkflowName..."
aws glue create-workflow `
    --name $WorkflowName `
    --description "Pipeline diario ShopStream: Crawler -> ETL Job -> RDS" `
    --region $Region 2>$null
Write-Host "    OK"

# ── 2. Trigger Schedule (2 AM UTC) ──────────────────────────
Write-Host "==> Creando trigger Schedule (02:00 UTC diario)..."
aws glue create-trigger `
    --name "shopstream-schedule-trigger" `
    --workflow-name $WorkflowName `
    --type SCHEDULED `
    --schedule "cron(0 2 * * ? *)" `
    --actions "[{`"CrawlerName`":`"$CrawlerName`"}]" `
    --start-on-creation `
    --region $Region 2>$null
Write-Host "    OK"

# ── 3. Trigger condicional Crawler SUCCEEDED → Job ───────────
Write-Host "==> Creando trigger condicional CRAWLER_SUCCEEDED -> Job..."
$CondTrigger = @{
    Name = "shopstream-crawler-succeeded-trigger"
    WorkflowName = $WorkflowName
    Type = "CONDITIONAL"
    Predicate = @{
        Logical = "AND"
        Conditions = @(
            @{
                LogicalOperator = "EQUALS"
                CrawlerName = $CrawlerName
                CrawlState = "SUCCEEDED"
            }
        )
    }
    Actions = @(
        @{ JobName = $JobName }
    )
} | ConvertTo-Json -Depth 10

$CondTrigger | Out-File -Encoding utf8 "$env:TEMP\cond_trigger.json"
aws glue create-trigger --cli-input-json file://$env:TEMP\cond_trigger.json `
    --region $Region 2>$null
Write-Host "    OK"

# ── 4. Trigger ON_FAILURE → Lambda alerta ────────────────────
if (-not $AlertLambdaArn) {
    Write-Warning "ALERT_LAMBDA_ARN no definido. Saltando trigger de fallo."
} else {
    Write-Host "==> Creando trigger ON_FAILURE -> Lambda alerta..."
    $FailTrigger = @{
        Name = "shopstream-failure-alert-trigger"
        WorkflowName = $WorkflowName
        Type = "CONDITIONAL"
        Predicate = @{
            Logical = "ANY"
            Conditions = @(
                @{
                    LogicalOperator = "EQUALS"
                    JobName = $JobName
                    State = "FAILED"
                }
            )
        }
        Actions = @(
            @{
                JobName = ""
                Arguments = @{}
                NotificationProperty = @{ NotifyDelayAfter = 0 }
            }
        )
    }

    # Nota: Glue triggers no invocan Lambda directamente. Se usa EventBridge.
    # El trigger de fallo aquí notifica via SNS/EventBridge configurado aparte.
    Write-Host "    INFO: Glue Workflows no invocan Lambda directamente."
    Write-Host "    Configurar una regla EventBridge para capturar Glue FAILED state."
    Write-Host "    Ver: infrastructure/setup_eventbridge_alert.ps1"
}

Write-Host ""
Write-Host "==> Workflow creado. Para ejecutar manualmente:"
Write-Host "    aws glue start-workflow-run --name $WorkflowName --region $Region"
