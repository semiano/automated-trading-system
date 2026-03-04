$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

function Stop-ByPattern([string[]]$Patterns) {
    $targets = Get-CimInstance Win32_Process | Where-Object {
        $cmd = $_.CommandLine
        if (-not $cmd) { return $false }
        foreach ($pattern in $Patterns) {
            if ($cmd -like $pattern) { return $true }
        }
        return $false
    }

    foreach ($proc in $targets) {
        Stop-Process -Id $proc.ProcessId -Force -ErrorAction SilentlyContinue
    }

    return @($targets).Count
}

$killed = Stop-ByPattern @(
    "*uvicorn mdtas.api.app:app*",
    "*-m mdtas_worker*",
    "*vite*",
    "*npm --prefix web run dev*"
)

Write-Host "Stopped stale dev processes: $killed"

Start-Process -FilePath ".\\.venv\\Scripts\\python.exe" -ArgumentList "-m","uvicorn","mdtas.api.app:app","--host","0.0.0.0","--port","8000" -WorkingDirectory $root -WindowStyle Minimized
Start-Process -FilePath ".\\.venv\\Scripts\\python.exe" -ArgumentList "-m","mdtas_worker" -WorkingDirectory $root -WindowStyle Minimized
Start-Process -FilePath "cmd.exe" -ArgumentList "/c","npm --prefix web run dev" -WorkingDirectory $root -WindowStyle Minimized

Write-Host "Started API on http://localhost:8000"
Write-Host "Started worker"
Write-Host "Started web on http://localhost:5173 (strict port)"
