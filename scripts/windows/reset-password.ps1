$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
Set-Location -LiteralPath $projectRoot
$runtimePython = Join-Path $projectRoot '.runtime\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $runtimePython)) {
    $runtimePython = Join-Path $projectRoot '.venv\Scripts\python.exe'
}
if (-not (Test-Path -LiteralPath $runtimePython)) {
    throw 'No se encontró el entorno Python de PABLO OS. Inicia primero la aplicación.'
}
& $runtimePython (Join-Path $projectRoot 'scripts\local\reset_password.py')
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
