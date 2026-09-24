$ErrorActionPreference = "Stop"

$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$launcher = Join-Path $projectRoot "scripts\windows\launch.ps1"

if (-not (Test-Path -LiteralPath $launcher -PathType Leaf)) {
    throw "No se encuentra scripts\windows\launch.ps1 en $projectRoot"
}

$desktop = [Environment]::GetFolderPath("Desktop")
if ([string]::IsNullOrWhiteSpace($desktop)) {
    throw "Windows no ha podido localizar el escritorio del usuario."
}

$shortcutPaths = @((Join-Path $desktop "PABLO OS.lnk"))
$startup = [Environment]::GetFolderPath("Startup")
if ($startup) {
    $startupShortcut = Join-Path $startup "PABLO OS.lnk"
    # Repair an existing automatic start after a folder move; do not enable it implicitly.
    if (Test-Path -LiteralPath $startupShortcut -PathType Leaf) {
        $shortcutPaths += $startupShortcut
    }
}
$shell = New-Object -ComObject WScript.Shell
foreach ($shortcutPath in $shortcutPaths) {
    $shortcut = $shell.CreateShortcut($shortcutPath)
    $shortcut.TargetPath = "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe"
    $shortcut.Arguments = '-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File "' + $launcher + '"'
    $shortcut.WorkingDirectory = $projectRoot
    $shortcut.Description = "Abrir PABLO OS"
    $shortcut.IconLocation = (Join-Path $projectRoot "public\pablo-os-transparent.ico") + ',0'
    $shortcut.WindowStyle = 7
    $shortcut.Save()
    if (-not (Test-Path -LiteralPath $shortcutPath -PathType Leaf)) {
        throw "El acceso directo no se ha creado: $shortcutPath"
    }
    Write-Host "Actualizado: $shortcutPath"
}
