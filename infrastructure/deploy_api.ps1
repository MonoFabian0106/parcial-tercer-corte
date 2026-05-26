# Despliegue de la API ShopStream con Zappa.
# Uso:
#   .\infrastructure\deploy_api.ps1 deploy     # primera vez
#   .\infrastructure\deploy_api.ps1 update     # actualizaciones
#
# Lee DB_PASSWORD desde .env.local y lo inyecta como variable de entorno
# de la Lambda DESPUES del deploy (para no commitearlo en zappa_settings.json).

param(
    [Parameter(Position = 0)]
    [ValidateSet("deploy", "update")]
    [string]$Action = "deploy",

    [string]$Stage = "dev",
    [string]$FunctionName = "shopstream-api-dev",
    [string]$Region = "us-east-1"
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot

# Usamos un venv slim dedicado a Zappa para que el zip de la Lambda no
# incluya pyspark/pandas/pyarrow/moto/etc. (.venv principal pesa ~800MB).
$zappaVenvLocal = Join-Path $repoRoot ".venv-zappa"
if (-not (Test-Path (Join-Path $zappaVenvLocal "Scripts\zappa.exe"))) {
    throw "Falta .venv-zappa. Crealo con: uv venv .venv-zappa --python 3.11; uv pip install --python .venv-zappa/Scripts/python.exe flask sqlalchemy psycopg2-binary zappa"
}

# 1. Cargar .env.local
$envFile = Join-Path $repoRoot ".env.local"
if (-not (Test-Path $envFile)) {
    throw "Falta .env.local en $repoRoot. Copia .env.example y completa los valores."
}
$envMap = @{}
Get-Content $envFile | ForEach-Object {
    $line = $_.Trim()
    if ($line -and -not $line.StartsWith("#") -and $line.Contains("=")) {
        $key, $value = $line -split "=", 2
        $envMap[$key.Trim()] = $value.Trim().Trim('"')
    }
}

$required = @("DB_HOST", "DB_USER", "DB_PASSWORD", "DB_NAME", "DB_PORT")
foreach ($k in $required) {
    if (-not $envMap.ContainsKey($k) -or [string]::IsNullOrWhiteSpace($envMap[$k])) {
        throw "Variable $k requerida en .env.local"
    }
}

# Zappa ignora 'exclude' para rutas con '\' en Windows y empaqueta TODO lo
# que esta dentro del project root -> movemos las carpetas pesadas FUERA del
# repo durante el deploy y las restauramos al terminar (try/finally).
# .venv-zappa NO se mueve: el zappa.exe es un shim que hardcodea la ruta del
# python de la venv y se rompe si la movemos. Lo excluimos via patron en
# zappa_settings.json (substring ".venv-zappa").
# Hideamos fisicamente las carpetas con nombres genericos ("data", "tests",
# "docs", "build", "dist") porque Zappa aplica 'exclude' por nombre de dir
# en cualquier nivel -> excluirlos rompe dependencias como botocore/data,
# botocore/docs o pkgs con subdir tests/.
$hideDirs = @(".venv", "data", "tests", "docs", "build", "dist", ".pytest_cache", ".ruff_cache", ".mypy_cache", "data_samples")
$stashRoot = Join-Path (Split-Path -Parent $repoRoot) ".zappa-stash"
if (-not (Test-Path $stashRoot)) { New-Item -ItemType Directory -Path $stashRoot | Out-Null }
$hiddenList = @()
foreach ($d in $hideDirs) {
    $src = Join-Path $repoRoot $d
    if (Test-Path $src) {
        $bak = Join-Path $stashRoot $d
        if (Test-Path $bak) { Remove-Item $bak -Recurse -Force }
        Move-Item -Path $src -Destination $bak
        $hiddenList += @{ Src = $src; Bak = $bak }
        Write-Host ">> Movido temporalmente fuera del repo: $d"
    }
}

# Activamos la venv-zappa (sigue en el repo; excluida via patron en zappa_settings).
$zappaVenv = $zappaVenvLocal
$zappaExe  = Join-Path $zappaVenv "Scripts\zappa.exe"
$env:VIRTUAL_ENV = $zappaVenv
$env:PATH = (Join-Path $zappaVenv "Scripts") + ";" + $env:PATH

try {
    Write-Host ">> Ejecutando 'zappa $Action $Stage' desde venv slim..."
    & $zappaExe $Action $Stage
    if ($LASTEXITCODE -ne 0) { throw "Zappa $Action fallo (exit $LASTEXITCODE)" }
}
finally {
    foreach ($h in $hiddenList) {
        if (Test-Path $h.Bak) {
            if (Test-Path $h.Src) { Remove-Item $h.Src -Recurse -Force }
            Move-Item -Path $h.Bak -Destination $h.Src
            Write-Host ">> Restaurado: $(Split-Path -Leaf $h.Src)"
        }
    }
    if ((Test-Path $stashRoot) -and -not (Get-ChildItem -Force $stashRoot)) {
        Remove-Item $stashRoot -Force
    }
}

Write-Host ">> Inyectando DB_PASSWORD y otras vars en la Lambda $FunctionName..."
$envJson = @{
    Variables = @{
        DB_HOST     = $envMap["DB_HOST"]
        DB_PORT     = $envMap["DB_PORT"]
        DB_NAME     = $envMap["DB_NAME"]
        DB_USER     = $envMap["DB_USER"]
        DB_PASSWORD = $envMap["DB_PASSWORD"]
        LOG_LEVEL   = "INFO"
    }
} | ConvertTo-Json -Compress -Depth 4

# AWS CLI on Windows needs the JSON written to a temp file (escaping is painful)
$tmpFile = [System.IO.Path]::GetTempFileName()
Set-Content -Path $tmpFile -Value $envJson -Encoding ASCII -NoNewline
try {
    & aws lambda update-function-configuration `
        --function-name $FunctionName `
        --region $Region `
        --environment "file://$tmpFile" | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "update-function-configuration fallo (exit $LASTEXITCODE)" }
}
finally {
    Remove-Item $tmpFile -ErrorAction SilentlyContinue
}

Write-Host ">> Esperando a que la Lambda quede Active..."
& aws lambda wait function-updated --function-name $FunctionName --region $Region

Write-Host ""
Write-Host "Despliegue listo. URL:"
& $zappaExe status $Stage | Select-String "API Gateway URL"
