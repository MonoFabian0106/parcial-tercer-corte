# create_rds.ps1 — Crea la instancia RDS PostgreSQL para ShopStream DWH
# Requisito: credenciales AWS activas (LabRole), región us-east-1.
# Uso: .\infrastructure\create_rds.ps1

param(
    [string]$DbPassword = $env:DB_PASSWORD
)

if (-not $DbPassword) {
    Write-Error "Falta DB_PASSWORD. Pásalo como env var o -DbPassword."
    exit 1
}

$Region      = "us-east-1"
$DbInstance  = "shopstream-dwh"
$DbName      = "shopstream_dwh"
$DbUser      = "shopstream_admin"
$SgName      = "shopstream-rds-sg"

Write-Host "==> Buscando VPC default..."
$VpcId = (aws ec2 describe-vpcs --filters "Name=isDefault,Values=true" `
    --query "Vpcs[0].VpcId" --output text --region $Region)
Write-Host "    VPC: $VpcId"

Write-Host "==> Creando Security Group $SgName..."
$SgId = (aws ec2 create-security-group `
    --group-name $SgName `
    --description "RDS PostgreSQL para ShopStream DWH" `
    --vpc-id $VpcId `
    --query "GroupId" --output text --region $Region 2>$null)

if (-not $SgId) {
    # El SG ya existe, obtener su ID
    $SgId = (aws ec2 describe-security-groups `
        --filters "Name=group-name,Values=$SgName" "Name=vpc-id,Values=$VpcId" `
        --query "SecurityGroups[0].GroupId" --output text --region $Region)
    Write-Host "    SG ya existe: $SgId"
} else {
    Write-Host "    SG creado: $SgId"
    # Abrir puerto 5432 (lab: 0.0.0.0/0; en producción restringir)
    aws ec2 authorize-security-group-ingress `
        --group-id $SgId `
        --protocol tcp --port 5432 --cidr 0.0.0.0/0 `
        --region $Region | Out-Null
    Write-Host "    Regla inbound TCP/5432 añadida."
}

Write-Host "==> Creando RDS PostgreSQL $DbInstance..."
aws rds create-db-instance `
    --db-instance-identifier $DbInstance `
    --db-instance-class db.t3.micro `
    --engine postgres `
    --engine-version "15" `
    --master-username $DbUser `
    --master-user-password $DbPassword `
    --db-name $DbName `
    --allocated-storage 20 `
    --storage-type gp3 `
    --no-multi-az `
    --publicly-accessible `
    --vpc-security-group-ids $SgId `
    --backup-retention-period 1 `
    --no-deletion-protection `
    --region $Region | Out-Null

Write-Host "==> Esperando a que la instancia esté disponible (puede tardar ~5 min)..."
aws rds wait db-instance-available `
    --db-instance-identifier $DbInstance `
    --region $Region

$Endpoint = (aws rds describe-db-instances `
    --db-instance-identifier $DbInstance `
    --query "DBInstances[0].Endpoint.Address" `
    --output text --region $Region)

Write-Host ""
Write-Host "==> RDS disponible:"
Write-Host "    Endpoint : $Endpoint"
Write-Host "    Puerto   : 5432"
Write-Host "    DB       : $DbName"
Write-Host "    Usuario  : $DbUser"
Write-Host ""
Write-Host "==> Guarda esto en .env.local (NO en git):"
Write-Host "    DB_HOST=$Endpoint"
Write-Host "    DB_PORT=5432"
Write-Host "    DB_NAME=$DbName"
Write-Host "    DB_USER=$DbUser"
Write-Host "    DB_PASSWORD=<tu-password>"
