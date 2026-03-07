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
python3 - <<'PY'
import json
import urllib.request

rows = json.loads(urllib.request.urlopen('http://localhost:8000/api/v1/ingestion/catchup-status', timeout=10).read().decode('utf-8'))
for row in rows:
    if row.get('timeframe') == '1m' and row.get('symbol') in ('XRP/USD', 'HBAR/USD'):
        print(row['symbol'], 'latest=', row['latest_ts'], 'target=', row['target_end_ts'], 'behind=', row['bars_behind_before_jump'])
PY

docker compose --env-file .env.docker logs --since 20m ingestion | grep -E "Coinbase WS connected|Coinbase WS reconnect|Coinbase WS error|Coinbase WS closed|queue full|Heartbeat synthesized" | tail -n 220 || true
'@ | Set-Content -Path $remote -NoNewline

try {
    & "C:\Program Files\PuTTY\plink.exe" -batch -ssh -pw $pw -m $remote ("root@" + $ip)
}
finally {
    Remove-Item $remote -ErrorAction SilentlyContinue
}
