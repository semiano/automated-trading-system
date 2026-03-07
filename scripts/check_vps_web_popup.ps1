$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
$envPath = Join-Path $root ".env"

function Get-EnvValue {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$Key
    )
    $line = Get-Content $Path | Where-Object { $_ -match "^$([regex]::Escape($Key))=" } | Select-Object -First 1
    if (-not $line) { throw "Missing key $Key in $Path" }
    return $line.Split("=", 2)[1]
}

$droplets = doctl compute droplet list --output json | ConvertFrom-Json
$target = $droplets | Where-Object { $_.name -eq "ubuntu-s-1vcpu-1gb-nyc3-01" } | Select-Object -First 1
if (-not $target) { throw "Droplet not found" }
$ip = ($target.networks.v4 | Where-Object { $_.type -eq "public" } | Select-Object -First 1).ip_address
$pw = Get-EnvValue -Path $envPath -Key "DIGITAL_OCEAN_VPS_ROOT_PW"

$remote = [System.IO.Path]::GetTempFileName()
@'
set -e
cd /opt/automated-trading-system
echo "=== source check ==="
grep -n "Engine Inputs @" web/src/components/ChartLayout.tsx || true
grep -n "Runtime evaluates previous closed bar" web/src/components/ChartLayout.tsx || true
grep -n "Open Long" web/src/components/ChartLayout.tsx || true
grep -n "Open Short" web/src/components/ChartLayout.tsx || true
grep -n "BinarySubplot" web/src/components/ChartLayout.tsx || true
grep -n "assetControl=" web/src/app.tsx || true
echo "=== web service ==="
docker compose --env-file .env.docker ps web
'@ | Set-Content -Path $remote -NoNewline

try {
    & "C:\Program Files\PuTTY\plink.exe" -batch -ssh -pw $pw -m $remote ("root@" + $ip)
}
finally {
    Remove-Item $remote -ErrorAction SilentlyContinue
}
