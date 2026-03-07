$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
$envPath = Join-Path $root ".env"
$plink = "C:\Program Files\PuTTY\plink.exe"
$pscp = "C:\Program Files\PuTTY\pscp.exe"

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

$remoteRoot = "/opt/automated-trading-system"
$file = "src/mdtas/providers/coinbase_ws_provider.py"
$local = Join-Path $root $file
if (-not (Test-Path $local)) { throw "Missing local file: $file" }

Write-Host "Uploading ingestion WS provider file to $ip ..."
& $pscp -batch -pw $pw $local ("root@${ip}:${remoteRoot}/${file}")

$remoteScript = [System.IO.Path]::GetTempFileName()
@'
set -e
cd /opt/automated-trading-system
docker compose --env-file .env.docker up -d --build ingestion
docker compose --env-file .env.docker ps ingestion
'@ | Set-Content -Path $remoteScript -NoNewline

try {
    & $plink -batch -ssh -pw $pw -m $remoteScript ("root@" + $ip)
}
finally {
    Remove-Item $remoteScript -ErrorAction SilentlyContinue
}
