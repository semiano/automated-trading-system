$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$patterns = @(
    "*uvicorn mdtas.api.app:app*",
    "*-m mdtas_worker*",
    "*vite*",
    "*npm --prefix web run dev*"
)

$targets = Get-CimInstance Win32_Process | Where-Object {
    $cmd = $_.CommandLine
    if (-not $cmd) { return $false }
    foreach ($pattern in $patterns) {
        if ($cmd -like $pattern) { return $true }
    }
    return $false
}

foreach ($proc in $targets) {
    Stop-Process -Id $proc.ProcessId -Force -ErrorAction SilentlyContinue
}

Write-Host "Stopped dev processes: $(@($targets).Count)"
