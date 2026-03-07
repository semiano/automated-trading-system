$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
$envPath = Join-Path $root ".env"

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

$droplets = doctl compute droplet list --output json | ConvertFrom-Json
$target = $droplets | Where-Object { $_.name -eq "ubuntu-s-1vcpu-1gb-nyc3-01" } | Select-Object -First 1
if (-not $target) {
    throw "Droplet not found"
}
$ip = ($target.networks.v4 | Where-Object { $_.type -eq "public" } | Select-Object -First 1).ip_address
$pw = Get-EnvValue -Path $envPath -Key "DIGITAL_OCEAN_VPS_ROOT_PW"

$remote = [System.IO.Path]::GetTempFileName()
@'
set -e
cd /opt/automated-trading-system
echo "=== config file ==="
grep '^MDTAS_CONFIG_FILE=' .env.docker || true

echo "=== momentum config ==="
grep -E '^(  bb_entry_mode|  momentum_swing_enabled|  momentum_pivot_left_bars|  momentum_pivot_right_bars|  momentum_lookback_bars|  momentum_roc_length|  momentum_min_roc)' config.yaml || true

echo "=== service status ==="
docker compose --env-file .env.docker ps api ingestion trader

echo "=== trader logs (5m) ==="
docker compose --env-file .env.docker logs --since 5m trader | tail -n 80 || true
'@ | Set-Content -Path $remote -NoNewline

try {
    & "C:\Program Files\PuTTY\plink.exe" -batch -ssh -pw $pw -m $remote ("root@" + $ip)
}
finally {
    Remove-Item $remote -ErrorAction SilentlyContinue
}
