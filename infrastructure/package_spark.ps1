# Empaqueta el código PySpark y lo sube a S3 para que EMR lo consuma.
#
# Resultado:
#   s3://<bucket>/code/spark_jobs.zip   <- paquete completo (para --py-files)
#   s3://<bucket>/code/etl_main.py      <- entry point (para spark-submit)
#   s3://<bucket>/code/notebooks/...    <- notebook para EMR Studio
#
# Uso:
#     pwsh ./infrastructure/package_spark.ps1
#     pwsh ./infrastructure/package_spark.ps1 -Bucket shopstream-processed-mf0106

param(
    [string]$Bucket = "shopstream-processed-mf0106",
    [string]$BuildDir = "build/spark"
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

Write-Host "==> Empaquetando spark_jobs/ -> $BuildDir/spark_jobs.zip" -ForegroundColor Cyan

if (Test-Path $BuildDir) { Remove-Item -Recurse -Force $BuildDir }
New-Item -ItemType Directory -Path $BuildDir | Out-Null

# Copiar el paquete spark_jobs sin notebooks ni __pycache__
$staging = "$BuildDir/staging"
New-Item -ItemType Directory -Path $staging | Out-Null
Copy-Item -Recurse "spark_jobs" "$staging/spark_jobs"

# Limpiar
Get-ChildItem -Recurse -Path $staging -Filter "__pycache__" -Directory | ForEach-Object { Remove-Item -Recurse -Force $_.FullName }
Get-ChildItem -Recurse -Path $staging -Filter "*.pyc" | ForEach-Object { Remove-Item -Force $_.FullName }
# Excluir notebooks del zip (van al bucket aparte)
if (Test-Path "$staging/spark_jobs/notebooks") {
    Remove-Item -Recurse -Force "$staging/spark_jobs/notebooks"
}

$zipPath = Join-Path (Get-Location).Path "$BuildDir/spark_jobs.zip"
Push-Location $staging
try {
    Compress-Archive -Path "spark_jobs" -DestinationPath $zipPath -Force
} finally {
    Pop-Location
}
$size = (Get-Item $zipPath).Length
Write-Host ("==> Zip creado: $zipPath ({0:N1} KB)" -f ($size / 1KB)) -ForegroundColor Green

# Subir a S3
Write-Host "==> Subiendo a s3://$Bucket/code/" -ForegroundColor Cyan
aws s3 cp $zipPath "s3://$Bucket/code/spark_jobs.zip" | Out-Null
aws s3 cp "spark_jobs/etl_main.py" "s3://$Bucket/code/etl_main.py" | Out-Null
aws s3 cp "spark_jobs/notebooks/exploratory.ipynb" "s3://$Bucket/code/notebooks/exploratory.ipynb" | Out-Null

Write-Host "==> Listo. Recursos en S3:" -ForegroundColor Green
aws s3 ls "s3://$Bucket/code/" --recursive --human-readable
