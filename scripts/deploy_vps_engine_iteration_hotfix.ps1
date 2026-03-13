$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
$envPath = Join-Path $root ".env"
$envDockerPath = Join-Path $root ".env.docker"
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

function Get-OptionalEnvValue {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$Key
    )
    if (-not (Test-Path $Path)) {
        return $null
    }
    $line = Get-Content $Path | Where-Object { $_ -match "^$([regex]::Escape($Key))=" } | Select-Object -First 1
    if (-not $line) {
        return $null
    }
    return $line.Split("=", 2)[1]
}

function Set-EnvValueInFile {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$Key,
        [Parameter(Mandatory = $true)][string]$Value
    )

    $lines = @()
    if (Test-Path $Path) {
        $lines = Get-Content $Path
    }
    $updated = $false
    for ($i = 0; $i -lt $lines.Count; $i++) {
        if ($lines[$i] -match "^$([regex]::Escape($Key))=") {
            $lines[$i] = "${Key}=${Value}"
            $updated = $true
            break
        }
    }
    if (-not $updated) {
        $lines += "${Key}=${Value}"
    }
    Set-Content -Path $Path -Value ($lines -join "`n") -NoNewline
}

if (-not (Test-Path $plink)) { throw "plink not found at $plink" }
if (-not (Test-Path $pscp)) { throw "pscp not found at $pscp" }
if (-not (Test-Path $envDockerPath)) { throw "Missing .env.docker at $envDockerPath" }

$droplets = doctl compute droplet list --output json | ConvertFrom-Json
$target = $droplets | Where-Object { $_.name -eq "ubuntu-s-1vcpu-1gb-nyc3-01" } | Select-Object -First 1
if (-not $target) { throw "Droplet not found" }
$ip = ($target.networks.v4 | Where-Object { $_.type -eq "public" } | Select-Object -First 1).ip_address
if (-not $ip) { throw "No public IP found" }
$pw = Get-EnvValue -Path $envPath -Key "DIGITAL_OCEAN_VPS_ROOT_PW"

$remoteRoot = "/opt/automated-trading-system"
$files = @(
    "docker-compose.yml",
    "config.yaml",
    "src/mdtas/config.py",
    "src/mdtas/db/models.py",
    "src/mdtas/db/session.py",
    "src/mdtas/db/trading_repo.py",
    "src/mdtas/trading/execution.py",
    "src/mdtas/trading/runtime.py",
    "src/mdtas/indicators/engine.py",
    "src/mdtas/trading/runtime_1m_simple.py",
    "src/mdtas/trading/runtime_5m_simple.py",
    "src/mdtas/api/auth.py",
    "src/mdtas/api/app.py",
    "src/mdtas/api/routes_indicators.py",
    "src/mdtas/api/routes_features.py",
    "src/mdtas/api/schemas.py",
    "src/mdtas/api/routes_trading.py",
    "src/services/trader_5m_main.py",
    "src/services/trader_1h_main.py",
    "src/services/trader_main.py",
    "src/mdtas_worker_5m.py",
    "artifacts/xrp_engine_v3_1h_for_runtime.yaml",
    "web/src/components/CandleChart.tsx",
    "web/src/components/IndicatorPanels.tsx",
    "web/src/components/ChartLayout.tsx",
    "web/src/components/SymbolTimeframePicker.tsx",
    "web/src/components/PortfolioPage.tsx",
    "web/src/app.tsx",
    "web/tsconfig.json",
    "web/src/api/types.ts",
    "web/src/api/client.ts"
)

$readToken = Get-OptionalEnvValue -Path $envPath -Key "MDTAS_API_READ_TOKEN"
$writeToken = Get-OptionalEnvValue -Path $envPath -Key "MDTAS_API_WRITE_TOKEN"
${exchangeApiKey} = Get-OptionalEnvValue -Path $envPath -Key "EXCHANGE_API_KEY"
${exchangeApiSecret} = Get-OptionalEnvValue -Path $envPath -Key "EXCHANGE_API_SECRET"
${exchangeApiPassword} = Get-OptionalEnvValue -Path $envPath -Key "EXCHANGE_API_PASSWORD"
${exchangeSandbox} = Get-OptionalEnvValue -Path $envPath -Key "EXCHANGE_SANDBOX"
${liveAck} = Get-OptionalEnvValue -Path $envPath -Key "MDTAS_ENABLE_LIVE_TRADING"
if ($readToken) {
    Set-EnvValueInFile -Path $envDockerPath -Key "MDTAS_API_READ_TOKEN" -Value $readToken
    Set-EnvValueInFile -Path $envDockerPath -Key "VITE_API_READ_TOKEN" -Value $readToken
}
if ($writeToken) {
    Set-EnvValueInFile -Path $envDockerPath -Key "MDTAS_API_WRITE_TOKEN" -Value $writeToken
    Set-EnvValueInFile -Path $envDockerPath -Key "VITE_API_WRITE_TOKEN" -Value $writeToken
}
if ($exchangeApiKey) {
    Set-EnvValueInFile -Path $envDockerPath -Key "EXCHANGE_API_KEY" -Value $exchangeApiKey
}
if ($exchangeApiSecret) {
    Set-EnvValueInFile -Path $envDockerPath -Key "EXCHANGE_API_SECRET" -Value $exchangeApiSecret
}
if ($exchangeApiPassword) {
    Set-EnvValueInFile -Path $envDockerPath -Key "EXCHANGE_API_PASSWORD" -Value $exchangeApiPassword
}
if ($exchangeSandbox) {
    Set-EnvValueInFile -Path $envDockerPath -Key "EXCHANGE_SANDBOX" -Value $exchangeSandbox
}
if ($liveAck) {
    Set-EnvValueInFile -Path $envDockerPath -Key "MDTAS_ENABLE_LIVE_TRADING" -Value $liveAck
}

Write-Host "Uploading .env.docker to $ip ..."
& $pscp -batch -pw $pw $envDockerPath ("root@${ip}:${remoteRoot}/.env.docker")

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

# Remove stale TypeScript emit artifacts that can shadow .ts sources in Vite.
rm -f web/src/api/client.js web/src/api/types.js

docker compose --env-file .env.docker up -d --build api trader trader_5m trader_1h web

echo "=== service status ==="
docker compose --env-file .env.docker ps api trader trader_5m trader_1h web
'@ | Set-Content -Path $remoteScript -NoNewline

try {
    & $plink -batch -ssh -pw $pw -m $remoteScript ("root@" + $ip)
}
finally {
    Remove-Item $remoteScript -ErrorAction SilentlyContinue
}
