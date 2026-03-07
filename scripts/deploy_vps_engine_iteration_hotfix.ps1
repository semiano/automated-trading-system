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
    if (-not $line) {
        throw "Missing key $Key in $Path"
    }
    return $line.Split("=", 2)[1]
}

if (-not (Test-Path $plink)) { throw "plink not found at $plink" }
if (-not (Test-Path $pscp)) { throw "pscp not found at $pscp" }

$droplets = doctl compute droplet list --output json | ConvertFrom-Json
$target = $droplets | Where-Object { $_.name -eq "ubuntu-s-1vcpu-1gb-nyc3-01" } | Select-Object -First 1
if (-not $target) { throw "Droplet not found" }
$ip = ($target.networks.v4 | Where-Object { $_.type -eq "public" } | Select-Object -First 1).ip_address
if (-not $ip) { throw "No public IP found" }
$pw = Get-EnvValue -Path $envPath -Key "DIGITAL_OCEAN_VPS_ROOT_PW"

$remoteRoot = "/opt/automated-trading-system"
$files = @(
    "config.yaml",
    "src/mdtas/config.py",
    "src/mdtas/trading/runtime.py",
    "src/mdtas/api/routes_trading.py",
    "web/src/components/ChartLayout.tsx",
    "web/src/app.tsx",
    "web/src/api/types.ts"
)

Write-Host "Uploading iteration hotfix files to $ip ..."
foreach ($f in $files) {
    $local = Join-Path $root $f
    if (-not (Test-Path $local)) { throw "Missing local file: $f" }
    & $pscp -batch -pw $pw $local ("root@${ip}:${remoteRoot}/${f}")
}

$remoteScript = [System.IO.Path]::GetTempFileName()
@'
set -e
cd /opt/automated-trading-system
if ! grep -q '^MDTAS_CONFIG_FILE=' .env.docker; then
  echo 'MDTAS_CONFIG_FILE=./config.yaml' >> .env.docker
else
  sed -i 's|^MDTAS_CONFIG_FILE=.*|MDTAS_CONFIG_FILE=./config.yaml|' .env.docker
fi

docker compose --env-file .env.docker up -d --build api trader web

echo "=== service status ==="
docker compose --env-file .env.docker ps api trader web
'@ | Set-Content -Path $remoteScript -NoNewline

try {
    & $plink -batch -ssh -pw $pw -m $remoteScript ("root@" + $ip)
}
finally {
    Remove-Item $remoteScript -ErrorAction SilentlyContinue
}
