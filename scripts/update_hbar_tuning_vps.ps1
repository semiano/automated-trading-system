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

if (-not (Test-Path $plink)) {
    throw "plink not found at $plink"
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
cd /opt/automated-trading-system
python3 - <<'PY'
import json
import urllib.parse
import urllib.request

base = "http://127.0.0.1:8000/api/v1"
token = "__WRITE_TOKEN__"
symbol = "HBAR/USD"
encoded_symbol = urllib.parse.quote(symbol, safe="")

updates = [
    (
        "1m",
        {
            "atr_length": 20,
            "ema_fast": 7,
            "ema_slow": 71,
            "stop_atr": 1.1,
            "take_profit_atr": 2.9,
            "max_hold_bars": 250,
            "note": "hbar retune seed11 rollout",
            "source": "hbar_retune_sweep",
            "updated_by": "copilot",
        },
    ),
    (
        "5m",
        {
            "atr_length": 14,
            "ema_fast": 7,
            "ema_slow": 142,
            "stop_atr": 1.7,
            "take_profit_atr": 3.4,
            "max_hold_bars": 480,
            "note": "hbar retune seed11 rollout",
            "source": "hbar_retune_sweep",
            "updated_by": "copilot",
        },
    ),
]

for timeframe, payload in updates:
    q = urllib.parse.urlencode({"timeframe": timeframe})
    req = urllib.request.Request(
        f"{base}/control-plane/asset-tuning/{encoded_symbol}?{q}",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "X-API-Key": token},
        method="PUT",
    )
    resp = urllib.request.urlopen(req, timeout=20)
    body = json.loads(resp.read().decode("utf-8"))
    print("PUT", timeframe, resp.status, body.get("symbol"), body.get("timeframe"), body.get("tuning_version"), body.get("tuning_source"))

for timeframe in ["1m", "5m"]:
    q = urllib.parse.urlencode({"timeframe": timeframe, "limit": 1})
    req = urllib.request.Request(
        f"{base}/control-plane/asset-tuning/{encoded_symbol}?{q}",
        headers={"X-API-Key": token},
    )
    rows = json.loads(urllib.request.urlopen(req, timeout=20).read().decode("utf-8"))
    top = rows[0]
    p = top.get("params_json", {})
    print(
        "TOP",
        timeframe,
        "v",
        top.get("version"),
        "ema",
        p.get("ema_fast"),
        p.get("ema_slow"),
        "atr",
        p.get("atr_length"),
        "stop",
        p.get("stop_atr"),
        "take",
        p.get("take_profit_atr"),
        "hold",
        p.get("max_hold_bars"),
        "source",
        top.get("source"),
    )
PY
'@ | Set-Content -Path $remote -NoNewline

(Get-Content $remote -Raw).Replace("__WRITE_TOKEN__", $writeToken) | Set-Content -Path $remote -NoNewline

try {
    & $plink -batch -ssh -pw $pw -m $remote ("root@" + $ip)
}
finally {
    Remove-Item $remote -ErrorAction SilentlyContinue
}
