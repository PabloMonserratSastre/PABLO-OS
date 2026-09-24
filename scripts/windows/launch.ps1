param([switch]$NoBrowser, [switch]$Stop)
$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
Set-Location -LiteralPath $projectRoot
$localDir = Join-Path $projectRoot '.local'
New-Item -ItemType Directory -Path $localDir -Force | Out-Null
$logFile = Join-Path $localDir 'launcher.log'
try {
    $runtimePython = $null
    foreach ($candidate in @((Join-Path $projectRoot '.runtime\Scripts\python.exe'), (Join-Path $projectRoot '.venv\Scripts\python.exe'))) {
        if (Test-Path -LiteralPath $candidate) {
            & $candidate -c 'import sys; assert sys.version_info >= (3, 12)' 2>$null
            if ($LASTEXITCODE -eq 0) { $runtimePython = $candidate; break }
        }
    }
    if (-not $runtimePython) {
        $basePython = Join-Path $env:USERPROFILE '.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
        if (Test-Path -LiteralPath $basePython) {
            & $basePython -m venv (Join-Path $projectRoot '.runtime')
        } else {
            & py -3.12 -m venv (Join-Path $projectRoot '.runtime')
        }
        if ($LASTEXITCODE -ne 0) { throw 'Instala Python 3.12 o superior y vuelve a iniciar PABLO OS.' }
        $runtimePython = Join-Path $projectRoot '.runtime\Scripts\python.exe'
    }
    & $runtimePython -c 'import fastapi, uvicorn, sqlalchemy, alembic, cryptography, tzdata, pypdf, pdfplumber, docx, multipart, httpx' 2>$null
    if ($LASTEXITCODE -ne 0) {
        & $runtimePython -m pip install -r (Join-Path $projectRoot 'backend\requirements.txt') *>> $logFile
        if ($LASTEXITCODE -ne 0) { throw "No se pudieron instalar las dependencias. Detalles: $logFile" }
    }
    $runScript = Join-Path $projectRoot 'scripts\local\run.py'
    if ($Stop) {
        & $runtimePython $runScript --stop
        exit $LASTEXITCODE
    }
    & $runtimePython (Join-Path $projectRoot 'scripts\local\setup.py') *>> $logFile
    if ($LASTEXITCODE -ne 0) { throw 'No se pudo preparar la configuracion local.' }
    # Start the installed local AI service without downloading on everyday launch.
    try {
        $null = Invoke-RestMethod 'http://127.0.0.1:11434/api/tags' -TimeoutSec 2
    } catch {
        $ollamaExe = Join-Path $env:LOCALAPPDATA 'Programs\Ollama\ollama.exe'
        if (-not (Test-Path -LiteralPath $ollamaExe)) {
            $ollamaCommand = Get-Command ollama -ErrorAction SilentlyContinue
            if ($ollamaCommand) { $ollamaExe = $ollamaCommand.Source }
        }
        if (Test-Path -LiteralPath $ollamaExe) {
            Start-Process -FilePath $ollamaExe -ArgumentList 'serve' -WindowStyle Hidden
        } else {
            'Ollama no instalado. Ejecuta PREPARAR-IA-GRATIS.bat para habilitar IA local.' | Add-Content -LiteralPath $logFile
        }
    }
    $runtimeLog = Join-Path $localDir 'runtime.log'
    $runtimeErr = Join-Path $localDir 'runtime-error.log'
    $readyUrl = 'http://127.0.0.1:8000/ready'
    $ready = $false
    $installation = [System.BitConverter]::ToString([System.Security.Cryptography.SHA256]::Create().ComputeHash([System.Text.Encoding]::UTF8.GetBytes($projectRoot.ToLowerInvariant()))).Replace('-','').ToLowerInvariant().Substring(0,20)
    try { $health = Invoke-RestMethod -Uri $readyUrl -TimeoutSec 2; $ready = $health.application -eq 'pablo-os' -and $health.installation -eq $installation } catch {}
    if (-not $ready) {
        $process = Start-Process -FilePath $runtimePython -ArgumentList @(('"' + $runScript + '"')) -WorkingDirectory $projectRoot -WindowStyle Hidden -RedirectStandardOutput $runtimeLog -RedirectStandardError $runtimeErr -PassThru
        for ($attempt = 0; $attempt -lt 60; $attempt++) {
            try { $health = Invoke-RestMethod -Uri $readyUrl -TimeoutSec 2; $ready = $health.application -eq 'pablo-os' -and $health.installation -eq $installation } catch {}
            if ($ready) { break }
            if ($process.HasExited -and $process.ExitCode -ne 0) { throw "El programa no pudo iniciar. Revisa $runtimeErr" }
            Start-Sleep -Milliseconds 500
        }
    }
    if (-not $ready) { throw "El programa no respondio a tiempo. Revisa $runtimeErr" }
    if (-not $NoBrowser) {
        $edge = Join-Path ${env:ProgramFiles(x86)} 'Microsoft\Edge\Application\msedge.exe'
        if (Test-Path -LiteralPath $edge) {
            Start-Process -FilePath $edge -ArgumentList '--app=http://localhost:8000'

        } else {
            Start-Process 'http://localhost:8000'
        }
    }
    Write-Output 'PABLO OS listo: http://localhost:8000'
} catch {
    $_.Exception.Message | Add-Content -LiteralPath $logFile
    if (-not $NoBrowser) {
        Add-Type -AssemblyName PresentationFramework
        [System.Windows.MessageBox]::Show($_.Exception.Message, 'No se pudo iniciar PABLO OS') | Out-Null
    }
    Write-Error $_
    exit 1
}
