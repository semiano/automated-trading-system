$ErrorActionPreference = 'Stop'

Write-Warning "'flatten_project_root.ps1' is deprecated. Use 'maint_flatten_project_root.ps1' instead."

$target = Join-Path $PSScriptRoot 'maint_flatten_project_root.ps1'
if (-not (Test-Path -LiteralPath $target)) {
  throw "Missing target script: $target"
}

& $target
