$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
$destination = Join-Path $root '.local/pablo-os-cloud.zip'
New-Item -ItemType Directory -Path (Join-Path $root '.local') -Force | Out-Null
$folders = @('backend','frontend','app','components','hooks','lib','public','vendor','scripts')
$files = @('Dockerfile','.dockerignore','.gitignore','render.yaml','package.json','package-lock.json','tsconfig.json','vite.local.config.ts','index.html','eslint.config.mjs','next-env.d.ts','postcss.config.mjs','components.json','IPHONE.md')
Add-Type -AssemblyName System.IO.Compression
$stream = [IO.File]::Open($destination, [IO.FileMode]::Create)
$archive = [IO.Compression.ZipArchive]::new($stream, [IO.Compression.ZipArchiveMode]::Create)
try {
    $paths = @()
    foreach ($folder in $folders) {
        $path = Join-Path $root $folder
        if (Test-Path -LiteralPath $path) { $paths += Get-ChildItem -LiteralPath $path -File -Recurse }
    }
    foreach ($file in $files) {
        $path = Join-Path $root $file
        if (Test-Path -LiteralPath $path) { $paths += Get-Item -LiteralPath $path }
    }
    foreach ($file in $paths) {
        $relative = $file.FullName.Substring($root.Length + 1).Replace('\','/')
        if ($relative -match '(^|/)(__pycache__|\.pytest_cache|screenshots)(/|$)' -or $file.Extension -in @('.pyc','.db','.key','.pem') -or $file.Name.StartsWith('.env')) { continue }
        $entry = $archive.CreateEntry($relative)
        $output = $entry.Open()
        $inputFile = [IO.File]::OpenRead($file.FullName)
        try { $inputFile.CopyTo($output) } finally { $inputFile.Dispose(); $output.Dispose() }
    }
} finally { $archive.Dispose(); $stream.Dispose() }
Write-Output $destination
