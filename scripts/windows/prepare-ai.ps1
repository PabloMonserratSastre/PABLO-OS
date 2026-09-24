$ErrorActionPreference = 'Stop'
try {
    $ollamaExe = Join-Path $env:LOCALAPPDATA 'Programs\Ollama\ollama.exe'
    if (-not (Test-Path -LiteralPath $ollamaExe)) {
        $installed = Get-Command ollama -ErrorAction SilentlyContinue
        if ($installed) { $ollamaExe = $installed.Source }
        else {
            Start-Process 'https://ollama.com/download/windows'
            throw 'Instala Ollama desde la pagina oficial abierta y vuelve a ejecutar este archivo.'
        }
    }
    $ready = $false
    try { $null = Invoke-RestMethod 'http://127.0.0.1:11434/api/tags' -TimeoutSec 3; $ready = $true } catch {}
    if (-not $ready) {
        Start-Process -FilePath $ollamaExe -ArgumentList 'serve' -WindowStyle Hidden
        for ($attempt = 0; $attempt -lt 30; $attempt++) {
            try { $null = Invoke-RestMethod 'http://127.0.0.1:11434/api/tags' -TimeoutSec 2; $ready = $true; break } catch {}
            Start-Sleep -Milliseconds 500
        }
    }
    if (-not $ready) { throw 'Ollama no responde. Abre Ollama desde Inicio y vuelve a intentarlo.' }
    $models = Invoke-RestMethod 'http://127.0.0.1:11434/api/tags' -TimeoutSec 3
    if ('llama3.2:1b' -notin $models.models.name) {
        Write-Host 'Descargando el modelo local gratuito. Solo esta descarga necesita Internet.'
        & $ollamaExe pull llama3.2:1b
        if ($LASTEXITCODE -ne 0) { throw 'No se pudo descargar el modelo. Comprueba Internet y el espacio libre.' }
    }
    Write-Host 'IA preparada. En PABLO OS: Ajustes > Detectar IA local gratuita > llama3.2:1b > Guardar proveedor.'
} catch {
    Write-Host $_.Exception.Message -ForegroundColor Red
    exit 1
}
