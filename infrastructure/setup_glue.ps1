# setup_glue.ps1 — Crea Glue Database, Crawler y Connection para ShopStream
# Requisito: credenciales AWS activas, .env.local con DB_HOST/DB_USER/DB_PASSWORD.
# Uso: .\infrastructure\setup_glue.ps1

param(
    [string]$ProcessedBucket = "shopstream-processed-mf0106",
    [string]$DbHost          = $env:DB_HOST,
    [string]$DbUser          = $env:DB_USER,
    [string]$DbPassword      = $env:DB_PASSWORD
)

$Region      = "us-east-1"
$GlueDb      = "shopstream_metrics_db"
$CrawlerName = "shopstream-metrics-crawler"
$ConnName    = "shopstream-rds-conn"
$DbName      = "shopstream_dwh"

# ── 1. Glue Database ────────────────────────────────────────
Write-Host "==> Creando Glue Database $GlueDb..."
aws glue create-database `
    --database-input "{`"Name`":`"$GlueDb`",`"Description`":`"ShopStream metrics catalogadas desde S3 Parquet`"}" `
    --region $Region 2>$null
Write-Host "    OK (si ya existía se ignora el error)"

# ── 2. Crawler ──────────────────────────────────────────────
Write-Host "==> Creando Crawler $CrawlerName..."
$CrawlerConfig = @{
    Name = $CrawlerName
    Role = "LabRole"
    DatabaseName = $GlueDb
    Targets = @{
        S3Targets = @(
            @{ Path = "s3://$ProcessedBucket/metrics/" }
        )
    }
    SchemaChangePolicy = @{
        UpdateBehavior = "UPDATE_IN_DATABASE"
        DeleteBehavior = "LOG"
    }
    RecrawlPolicy = @{ RecrawlBehavior = "CRAWL_EVERYTHING" }
    Configuration = '{"Version":1.0,"CrawlerOutput":{"Partitions":{"AddOrUpdateBehavior":"InheritFromTable"}}}'
} | ConvertTo-Json -Depth 10

$CrawlerConfig | Out-File -Encoding utf8 "$env:TEMP\crawler_config.json"

aws glue create-crawler --cli-input-json file://$env:TEMP\crawler_config.json `
    --region $Region 2>$null
Write-Host "    OK"

# ── 3. Glue Connection a RDS ─────────────────────────────────
if (-not $DbHost) {
    Write-Warning "DB_HOST no definido. Saltando creación de Connection."
} else {
    Write-Host "==> Buscando VPC/Subnet para Glue Connection..."
    $VpcId = (aws ec2 describe-vpcs --filters "Name=isDefault,Values=true" `
        --query "Vpcs[0].VpcId" --output text --region $Region)
    $SubnetId = (aws ec2 describe-subnets `
        --filters "Name=vpc-id,Values=$VpcId" "Name=defaultForAz,Values=true" `
        --query "Subnets[0].SubnetId" --output text --region $Region)
    $SgId = (aws ec2 describe-security-groups `
        --filters "Name=group-name,Values=shopstream-rds-sg" "Name=vpc-id,Values=$VpcId" `
        --query "SecurityGroups[0].GroupId" --output text --region $Region)

    $JdbcUrl = "jdbc:postgresql://${DbHost}:5432/$DbName"
    Write-Host "    JDBC: $JdbcUrl"
    Write-Host "    Subnet: $SubnetId  SG: $SgId"

    $ConnInput = @{
        Name = $ConnName
        ConnectionType = "JDBC"
        ConnectionProperties = @{
            JDBC_CONNECTION_URL = $JdbcUrl
            USERNAME = $DbUser
            PASSWORD = $DbPassword
        }
        PhysicalConnectionRequirements = @{
            SubnetId = $SubnetId
            SecurityGroupIdList = @($SgId)
            AvailabilityZone = "us-east-1a"
        }
    } | ConvertTo-Json -Depth 10

    $ConnInput | Out-File -Encoding utf8 "$env:TEMP\conn_input.json"

    aws glue create-connection `
        --connection-input file://$env:TEMP\conn_input.json `
        --region $Region 2>$null
    Write-Host "    Conexión $ConnName creada."
}

Write-Host ""
Write-Host "==> Siguiente paso manual:"
Write-Host "    1. AWS Console > Glue > Crawlers > $CrawlerName > Run"
Write-Host "    2. Esperar SUCCEEDED y verificar tablas en $GlueDb"
Write-Host "    3. AWS Console > Glue > Connections > $ConnName > Test connection"
