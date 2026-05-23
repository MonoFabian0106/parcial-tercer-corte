# Empaqueta la Lambda de ingesta en un zip listo para desplegar.
#
# Estrategia:
# 1. Crea una carpeta build/ limpia.
# 2. Instala las dependencias runtime (jsonschema) con uv pip install --target.
# 3. Copia el código fuente (lambda_ingest/ + data_generation/schemas.py + __init__).
# 4. Crea el zip eliminando archivos .pyc y __pycache__.
#
# Uso:
#     pwsh ./infrastructure/package_lambda.ps1
#
# Output: dist/shopstream-ingest-validator.zip

param(
    [string]$BuildDir = "build/lambda",
    [string]$OutZip = "dist/shopstream-ingest-validator.zip",
    [string]$Python = "3.11"
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

Write-Host "==> Empaquetando Lambda en $OutZip" -ForegroundColor Cyan

# Limpiar build
if (Test-Path $BuildDir) {
    Remove-Item -Recurse -Force $BuildDir
}
New-Item -ItemType Directory -Path $BuildDir | Out-Null

# Instalar dependencias runtime para la plataforma Lambda (linux x86_64)
# IMPORTANTE: --python-platform asegura que se descarguen wheels para manylinux,
# no los de Windows (que tienen C extensions incompatibles con AWS Lambda).
Write-Host "==> Instalando dependencias runtime (target: linux x86_64)" -ForegroundColor Cyan
uv pip install `
    --python-version $Python `
    --python-platform x86_64-manylinux2014 `
    --target $BuildDir `
    jsonschema | Out-Null

# Copiar código del proyecto. Solo lo estrictamente necesario para Lambda.
Write-Host "==> Copiando código fuente" -ForegroundColor Cyan
Copy-Item -Recurse -Force "lambda_ingest" "$BuildDir/lambda_ingest"
# data_generation/schemas.py es necesario (lo importa el validator)
New-Item -ItemType Directory -Path "$BuildDir/data_generation" | Out-Null
Copy-Item "data_generation/__init__.py" "$BuildDir/data_generation/__init__.py"
Copy-Item "data_generation/schemas.py" "$BuildDir/data_generation/schemas.py"

# Limpieza: eliminar __pycache__, .pyc, archivos de tests embebidos en deps
Write-Host "==> Limpiando cachés" -ForegroundColor Cyan
Get-ChildItem -Recurse -Path $BuildDir -Filter "__pycache__" -Directory |
    ForEach-Object { Remove-Item -Recurse -Force $_.FullName }
Get-ChildItem -Recurse -Path $BuildDir -Filter "*.pyc" |
    ForEach-Object { Remove-Item -Force $_.FullName }
Get-ChildItem -Recurse -Path $BuildDir -Filter "*.dist-info" -Directory |
    ForEach-Object { Remove-Item -Recurse -Force $_.FullName }
Get-ChildItem -Recurse -Path $BuildDir -Filter "tests" -Directory |
    Where-Object { $_.FullName -notlike "*/lambda_ingest/*" } |
    ForEach-Object { Remove-Item -Recurse -Force $_.FullName }

# Crear zip
$distDir = Split-Path -Parent $OutZip
if (-not (Test-Path $distDir)) {
    New-Item -ItemType Directory -Path $distDir | Out-Null
}
if (Test-Path $OutZip) {
    Remove-Item $OutZip
}

Write-Host "==> Comprimiendo a $OutZip" -ForegroundColor Cyan
$absOut = Join-Path (Get-Location).Path $OutZip
Push-Location $BuildDir
try {
    Compress-Archive -Path * -DestinationPath $absOut -Force
} finally {
    Pop-Location
}

$size = (Get-Item $OutZip).Length
Write-Host ("==> Zip creado: $OutZip ({0:N2} MB)" -f ($size / 1MB)) -ForegroundColor Green
