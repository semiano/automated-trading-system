$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
$envPath = Join-Path $root ".env"
$plink = "C:\Program Files\PuTTY\plink.exe"

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
$writeToken = Get-EnvValue -Path $envPath -Key "MDTAS_API_WRITE_TOKEN"

$remote = [System.IO.Path]::GetTempFileName()
@'
set -e
python3 - <<'PY'
import json
import urllib.parse
import urllib.request

base = "http://127.0.0.1:8000/api/v1"
token = "__WRITE_TOKEN__"
symbol = "HBAR/USD"
for timeframe in ["1m", "5m"]:
    q = urllib.parse.urlencode({"timeframe": timeframe})
    req = urllib.request.Request(f"{base}/control-plane/assets?{q}", headers={"X-API-Key": token})
    rows = json.loads(urllib.request.urlopen(req, timeout=20).read().decode("utf-8"))
    row = next(r for r in rows if r.get("symbol") == symbol and r.get("timeframe") == timeframe)
    print("ASSET", timeframe, "version", row.get("tuning_version"), "source", row.get("tuning_source"))

for timeframe in ["1m", "5m"]:
    encoded_symbol = urllib.parse.quote(symbol, safe="")
    q = urllib.parse.urlencode({"timeframe": timeframe, "limit": 1})
    req = urllib.request.Request(f"{base}/control-plane/asset-tuning/{encoded_symbol}?{q}", headers={"X-API-Key": token})
    top = json.loads(urllib.request.urlopen(req, timeout=20).read().decode("utf-8"))[0]
    p = top.get("params_json", {})
    print("TOP", timeframe, top.get("version"), p.get("ema_fast"), p.get("ema_slow"), p.get("atr_length"), p.get("stop_atr"), p.get("take_profit_atr"), p.get("max_hold_bars"))
PY
'@ | Set-Content -Path $remote -NoNewline

(Get-Content $remote -Raw).Replace("__WRITE_TOKEN__", $writeToken) | Set-Content -Path $remote -NoNewline

try {
    & $plink -batch -ssh -pw $pw -m $remote ("root@" + $ip)
}
finally {
    Remove-Item $remote -ErrorAction SilentlyContinue
}
