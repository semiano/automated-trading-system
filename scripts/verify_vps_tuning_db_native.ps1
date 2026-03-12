$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
$envPath = Join-Path $root ".env"
$envDockerPath = Join-Path $root ".env.docker"

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
$writeToken = Get-EnvValue -Path $envDockerPath -Key "MDTAS_API_WRITE_TOKEN"

$remote = [System.IO.Path]::GetTempFileName()
@'
set -e
cd /opt/automated-trading-system
WRITE_TOKEN="__WRITE_TOKEN__"
python3 - <<'PY'
import json
import urllib.parse
import urllib.request

base = "http://127.0.0.1:8000/api/v1"
token = "__WRITE_TOKEN__"
symbol = "XRP/USD"
timeframe = "5m"
q = urllib.parse.urlencode({"timeframe": timeframe})
encoded_symbol = urllib.parse.quote(symbol, safe="")

payload = {
    "bb_entry_deviation": 0.91,
    "note": "post-redeploy verify",
    "source": "manual_verify",
    "updated_by": "copilot",
}

put_req = urllib.request.Request(
    f"{base}/control-plane/asset-tuning/{encoded_symbol}?{q}",
    data=json.dumps(payload).encode("utf-8"),
    headers={"Content-Type": "application/json", "X-API-Key": token},
    method="PUT",
)
put_resp = urllib.request.urlopen(put_req, timeout=20)
print("PUT_STATUS", put_resp.status)

assets_req = urllib.request.Request(
    f"{base}/control-plane/assets?{q}",
    headers={"X-API-Key": token},
)
assets = json.loads(urllib.request.urlopen(assets_req, timeout=20).read().decode("utf-8"))
row = next(r for r in assets if r.get("symbol") == symbol and r.get("timeframe") == timeframe)
print("ASSET_TUNING_VERSION", row.get("tuning_version"))
print("ASSET_TUNING_SOURCE", row.get("tuning_source"))

history_req = urllib.request.Request(
    f"{base}/control-plane/asset-tuning/{encoded_symbol}?" + urllib.parse.urlencode({"timeframe": timeframe, "limit": 3}),
    headers={"X-API-Key": token},
)
history = json.loads(urllib.request.urlopen(history_req, timeout=20).read().decode("utf-8"))
latest = history[0]
print("HISTORY_TOP_VERSION", latest.get("version"))
print("HISTORY_TOP_SOURCE", latest.get("source"))
print("HISTORY_TOP_NOTE", latest.get("note"))
PY

echo "=== Recent API logs (tuning) ==="
docker compose --env-file .env.docker logs --since 3m api | grep -E "asset-tuning|AttributeError|Internal Server Error|latest_asset_tuning_version|create_asset_tuning_version" | tail -n 80 || true
'@ | Set-Content -Path $remote -NoNewline

(Get-Content $remote -Raw).Replace("__WRITE_TOKEN__", $writeToken) | Set-Content -Path $remote -NoNewline

try {
    & "C:\Program Files\PuTTY\plink.exe" -batch -ssh -pw $pw -m $remote ("root@" + $ip)
}
finally {
    Remove-Item $remote -ErrorAction SilentlyContinue
}
