$ErrorActionPreference = 'Stop'
$src = Join-Path $PSScriptRoot '..\market-data-ta-service'
$src = (Resolve-Path $src).Path
$dst = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path

function Merge-Directory {
  param(
    [Parameter(Mandatory = $true)]
    [string]$SourceDir,
    [Parameter(Mandatory = $true)]
    [string]$TargetDir
  )

  Get-ChildItem -LiteralPath $SourceDir -Force | ForEach-Object {
    $targetPath = Join-Path $TargetDir $_.Name

    if ($_.PSIsContainer -and (Test-Path -LiteralPath $targetPath) -and (Get-Item -LiteralPath $targetPath).PSIsContainer) {
      Merge-Directory -SourceDir $_.FullName -TargetDir $targetPath
      Remove-Item -LiteralPath $_.FullName -Recurse -Force -ErrorAction SilentlyContinue
      return
    }

    Move-Item -LiteralPath $_.FullName -Destination $targetPath -Force
  }
}

if (-not (Test-Path -LiteralPath $src)) {
  Write-Host "Source folder not found: $src"
  exit 0
}

Get-ChildItem -LiteralPath $src -Force | ForEach-Object {
  $targetPath = Join-Path $dst $_.Name

  if ($_.PSIsContainer -and (Test-Path -LiteralPath $targetPath) -and (Get-Item -LiteralPath $targetPath).PSIsContainer) {
    Merge-Directory -SourceDir $_.FullName -TargetDir $targetPath
    Remove-Item -LiteralPath $_.FullName -Recurse -Force -ErrorAction SilentlyContinue
  }
  else {
    Move-Item -LiteralPath $_.FullName -Destination $targetPath -Force
  }
}

Remove-Item -LiteralPath $src -Recurse -Force
Write-Host "Flatten complete."
