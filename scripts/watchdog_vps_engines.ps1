param(
    [int]$LookbackMinutes = 3
)

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
$remoteBody = @'
set -e
cd /opt/automated-trading-system

required_services="api ingestion trader trader_5m trader_1h web"
running_services=$(docker compose --env-file .env.docker ps --status running --services || true)

for svc in $required_services; do
  if ! echo "$running_services" | grep -qx "$svc"; then
    echo "watchdog: restarting missing service=$svc"
    docker compose --env-file .env.docker up -d "$svc"
  fi
done

ingestion_log_count=$(docker compose --env-file .env.docker logs --since __LOOKBACK_MINUTES__m ingestion 2>/dev/null | wc -l | tr -d ' ')
if [ "$ingestion_log_count" = "0" ]; then
  echo "watchdog: ingestion produced no logs in __LOOKBACK_MINUTES__m; restarting ingestion"
  docker compose --env-file .env.docker restart ingestion
fi

trader_log_count=$(docker compose --env-file .env.docker logs --since __LOOKBACK_MINUTES__m trader 2>/dev/null | grep -c "decision_event" || true)
if [ "$trader_log_count" = "0" ]; then
  echo "watchdog: trader produced no decision_event in __LOOKBACK_MINUTES__m; restarting trader"
  docker compose --env-file .env.docker restart trader
fi

trader_5m_log_count=$(docker compose --env-file .env.docker logs --since __LOOKBACK_MINUTES__m trader_5m 2>/dev/null | grep -c "decision_event" || true)
if [ "$trader_5m_log_count" = "0" ]; then
  echo "watchdog: trader_5m produced no decision_event in __LOOKBACK_MINUTES__m; restarting trader_5m"
  docker compose --env-file .env.docker restart trader_5m
fi

trader_1h_log_count=$(docker compose --env-file .env.docker logs --since __LOOKBACK_MINUTES__m trader_1h 2>/dev/null | grep -c "decision_event" || true)
if [ "$trader_1h_log_count" = "0" ]; then
  echo "watchdog: trader_1h produced no decision_event in __LOOKBACK_MINUTES__m; restarting trader_1h"
  docker compose --env-file .env.docker restart trader_1h
fi

echo "=== watchdog final status ==="
docker compose --env-file .env.docker ps api ingestion trader trader_5m trader_1h web
'@
$remoteBody = $remoteBody.Replace("__LOOKBACK_MINUTES__", [string]$LookbackMinutes)
$remoteBody | Set-Content -Path $remote -NoNewline

try {
    & "C:\Program Files\PuTTY\plink.exe" -batch -ssh -pw $pw -m $remote ("root@" + $ip)
}
finally {
    Remove-Item $remote -ErrorAction SilentlyContinue
}
