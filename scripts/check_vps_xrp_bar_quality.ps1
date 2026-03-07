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
from datetime import datetime, timedelta, timezone
import urllib.parse
import urllib.request


def fetch(symbol: str, lookback_minutes: int = 720):
    start = datetime.now(timezone.utc) - timedelta(minutes=lookback_minutes)
    q = urllib.parse.urlencode(
        {
            "symbol": symbol,
            "timeframe": "1m",
            "venue": "coinbase",
            "start": start.isoformat(),
            "limit": str(max(lookback_minutes + 30, 1000)),
        }
    )
    url = f"http://localhost:8000/api/v1/candles?{q}"
    with urllib.request.urlopen(url, timeout=20) as r:
        return json.loads(r.read().decode("utf-8"))


def summarize(symbol: str):
    rows = fetch(symbol)
    if not rows:
        print(symbol, "no_rows")
        return

    flat = [r for r in rows if r["open"] == r["high"] == r["low"] == r["close"]]
    zero_vol = [r for r in rows if float(r.get("volume", 0.0)) == 0.0]
    flat_zero = [r for r in rows if (r["open"] == r["high"] == r["low"] == r["close"]) and float(r.get("volume", 0.0)) == 0.0]

    longest_run = 0
    current_run = 0
    for r in rows:
        cond = (r["open"] == r["high"] == r["low"] == r["close"]) and float(r.get("volume", 0.0)) == 0.0
        if cond:
            current_run += 1
            longest_run = max(longest_run, current_run)
        else:
            current_run = 0

    print("===", symbol, "===")
    print("rows", len(rows))
    print("flat", len(flat), f"({len(flat)/len(rows):.1%})")
    print("zero_volume", len(zero_vol), f"({len(zero_vol)/len(rows):.1%})")
    print("flat_and_zero", len(flat_zero), f"({len(flat_zero)/len(rows):.1%})")
    print("longest_flat_zero_run", longest_run)
    print("first_ts", rows[0]["ts"], "last_ts", rows[-1]["ts"])

    tail = rows[-20:]
    print("tail_flat_zero_ts")
    for r in tail:
        cond = (r["open"] == r["high"] == r["low"] == r["close"]) and float(r.get("volume", 0.0)) == 0.0
        if cond:
            print(" ", r["ts"], "close", r["close"], "vol", r["volume"])

    print("tail_all_ts")
    for r in tail[-10:]:
        print(" ", r["ts"], "close", r["close"], "vol", r["volume"])

    non_zero_tail = [r for r in rows if float(r.get("volume", 0.0)) > 0.0]
    if non_zero_tail:
        last_non_zero = non_zero_tail[-1]
        print("last_non_zero_volume", last_non_zero["ts"], "close", last_non_zero["close"], "vol", last_non_zero["volume"])
    else:
        print("last_non_zero_volume none")

for sym in ("XRP/USD", "HBAR/USD"):
    summarize(sym)
PY

docker compose --env-file .env.docker logs --since 10m ingestion | grep -E "Heartbeat synthesized|Synthesized [0-9]+ missing 1m candles|Coinbase WS connected|queue full|WS error|WS closed" | tail -n 120 || true
'@ | Set-Content -Path $remote -NoNewline

try {
    & "C:\Program Files\PuTTY\plink.exe" -batch -ssh -pw $pw -m $remote ("root@" + $ip)
}
finally {
    Remove-Item $remote -ErrorAction SilentlyContinue
}
