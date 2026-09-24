param(
    [Parameter(Mandatory=$true)][string]$Url,
    [Parameter(Mandatory=$true)][string]$LocalProject
)
$ErrorActionPreference = 'Stop'
$origin = [Uri]$Url
if ($origin.Scheme -ne 'https' -or -not $origin.Host.EndsWith('.onrender.com') -or $origin.AbsolutePath -ne '/' -or $origin.Query -or $origin.Fragment -or $origin.UserInfo) {
    throw 'Escribe solo la dirección HTTPS de tu aplicación en Render.'
}
$root = (Resolve-Path -LiteralPath $LocalProject).Path
if (-not (Test-Path -LiteralPath (Join-Path $root 'scripts/windows/launch.ps1'))) { throw 'No es una instalación de PABLO OS.' }
$health = Invoke-RestMethod -Uri ($origin.AbsoluteUri.TrimEnd('/') + '/ready') -TimeoutSec 120
if ($health.application -ne 'pablo-os') { throw 'La dirección no corresponde a PABLO OS.' }
$edge = Join-Path ([Environment]::GetFolderPath('ProgramFilesX86')) 'Microsoft/Edge/Application/msedge.exe'
if (-not (Test-Path -LiteralPath $edge)) { throw 'No se encuentra Microsoft Edge.' }
$backup = Join-Path $root ('.local/shortcuts-before-cloud-' + (Get-Date -Format 'yyyyMMdd-HHmmss'))
New-Item -ItemType Directory -Path $backup | Out-Null
$shell = New-Object -ComObject WScript.Shell
foreach ($name in @('Desktop','Startup')) {
    $folder = [Environment]::GetFolderPath($name)
    $path = Join-Path $folder 'PABLO OS.lnk'
    if ($name -eq 'Startup' -and -not (Test-Path -LiteralPath $path)) { continue }
    if (Test-Path -LiteralPath $path) { Copy-Item -LiteralPath $path -Destination (Join-Path $backup ($name + '.lnk')) }
    $link = $shell.CreateShortcut($path)
    $link.TargetPath = $edge
    $link.Arguments = '--app=' + $origin.AbsoluteUri
    $link.WorkingDirectory = $root
    $link.IconLocation = (Join-Path $root 'public/pablo-os-transparent.ico') + ',0'
    $link.Description = 'PABLO OS: los mismos datos que en el iPhone'
    $link.Save()
}
Write-Output 'Accesos preparados para la nube. Conserva la copia local apagada tras migrar.'
