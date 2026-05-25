# setup_sns_alert.ps1 — Crea SNS topic, Lambda alert y regla EventBridge para fallos Glue
# Uso: .\infrastructure\setup_sns_alert.ps1 -Email tu@email.com

param(
    [Parameter(Mandatory=$true)]
    [string]$Email,
    [string]$ProcessedBucket = "shopstream-processed-mf0106"
)

$Region    = "us-east-1"
$TopicName = "shopstream-alerts"
$FnName    = "shopstream-alert-lambda"
$RuleName  = "shopstream-glue-failure-rule"

# ── 1. SNS Topic ─────────────────────────────────────────────
Write-Host "==> Creando SNS Topic $TopicName..."
$TopicArn = (aws sns create-topic --name $TopicName `
    --query "TopicArn" --output text --region $Region)
Write-Host "    ARN: $TopicArn"

Write-Host "==> Suscribiendo $Email..."
aws sns subscribe --topic-arn $TopicArn `
    --protocol email --notification-endpoint $Email `
    --region $Region | Out-Null
Write-Host "    Confirma el email de suscripción que llegará a $Email"

# ── 2. Empaquetar y desplegar Lambda alert ───────────────────
Write-Host "==> Empaquetando Lambda alert..."
$ZipPath = "$env:TEMP\shopstream_alert.zip"
Compress-Archive -Path ".\lambda_ingest\alert_handler.py" `
    -DestinationPath $ZipPath -Force

Write-Host "==> Desplegando Lambda $FnName..."
$ExistingFn = (aws lambda get-function --function-name $FnName `
    --region $Region --query "Configuration.FunctionName" `
    --output text 2>$null)

if ($ExistingFn -eq $FnName) {
    aws lambda update-function-code --function-name $FnName `
        --zip-file fileb://$ZipPath --region $Region | Out-Null
    aws lambda update-function-configuration --function-name $FnName `
        --environment "Variables={SNS_TOPIC_ARN=$TopicArn}" `
        --region $Region | Out-Null
    Write-Host "    Lambda actualizada."
} else {
    $LambdaArn = (aws lambda create-function `
        --function-name $FnName `
        --runtime python3.11 `
        --role "arn:aws:iam::$(aws sts get-caller-identity --query Account --output text):role/LabRole" `
        --handler "alert_handler.handler" `
        --zip-file fileb://$ZipPath `
        --timeout 30 `
        --environment "Variables={SNS_TOPIC_ARN=$TopicArn}" `
        --region $Region `
        --query "FunctionArn" --output text)
    Write-Host "    Lambda creada: $LambdaArn"
}

$LambdaArn = (aws lambda get-function --function-name $FnName `
    --query "Configuration.FunctionArn" --output text --region $Region)

# ── 3. EventBridge rule para Glue job FAILED ─────────────────
Write-Host "==> Creando regla EventBridge $RuleName..."
aws events put-rule `
    --name $RuleName `
    --event-pattern '{\"source\":[\"aws.glue\"],\"detail-type\":[\"Glue Job State Change\"],\"detail\":{\"state\":[\"FAILED\",\"TIMEOUT\",\"ERROR\"]}}' `
    --state ENABLED `
    --region $Region | Out-Null

aws lambda add-permission `
    --function-name $FnName `
    --statement-id "EventBridgeGlueFailure" `
    --action "lambda:InvokeFunction" `
    --principal "events.amazonaws.com" `
    --source-arn "arn:aws:events:${Region}:$(aws sts get-caller-identity --query Account --output text):rule/$RuleName" `
    --region $Region 2>$null | Out-Null

aws events put-targets `
    --rule $RuleName `
    --targets "[{`"Id`":`"AlertLambda`",`"Arn`":`"$LambdaArn`"}]" `
    --region $Region | Out-Null

Write-Host "    EventBridge -> Lambda configurado."
Write-Host ""
Write-Host "==> Resumen:"
Write-Host "    SNS Topic ARN : $TopicArn"
Write-Host "    Lambda ARN    : $LambdaArn"
Write-Host ""
Write-Host "==> Agrega a .env.local:"
Write-Host "    ALERT_LAMBDA_ARN=$LambdaArn"
Write-Host "    SNS_TOPIC_ARN=$TopicArn"
