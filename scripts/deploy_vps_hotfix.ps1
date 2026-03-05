$ErrorActionPreference = 'Stop'

function Get-EnvValue {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path,
        [Parameter(Mandatory = $true)]
        [string]$Key
    )

    $line = Get-Content $Path | Where-Object { $_ -match "^$([regex]::Escape($Key))=" } | Select-Object -First 1
    if (-not $line) {
        throw "Missing required key in ${Path}: $Key"
    }

    return $line.Split('=', 2)[1]
}

$repoRoot = Split-Path -Parent $PSScriptRoot
$envPath = Join-Path $repoRoot '.env'
$envDockerPath = Join-Path $repoRoot '.env.docker'
$appPath = Join-Path $repoRoot 'src/mdtas/api/app.py'
$plink = 'C:\Program Files\PuTTY\plink.exe'
$pscp = 'C:\Program Files\PuTTY\pscp.exe'

if (-not (Test-Path $plink)) { throw "plink not found at $plink" }
if (-not (Test-Path $pscp)) { throw "pscp not found at $pscp" }
if (-not (Test-Path $envDockerPath)) { throw "Missing $envDockerPath" }
if (-not (Test-Path $appPath)) { throw "Missing $appPath" }

$droplets = doctl compute droplet list --output json | ConvertFrom-Json
$target = $droplets | Where-Object { $_.name -eq 'ubuntu-s-1vcpu-1gb-nyc3-01' } | Select-Object -First 1
if (-not $target) { throw 'Target droplet not found: ubuntu-s-1vcpu-1gb-nyc3-01' }
$ip = ($target.networks.v4 | Where-Object { $_.type -eq 'public' } | Select-Object -First 1).ip_address
if (-not $ip) { throw 'No public IP found for target droplet' }

$rootPassword = Get-EnvValue -Path $envPath -Key 'DIGITAL_OCEAN_VPS_ROOT_PW'
$apiKey = Get-EnvValue -Path $envPath -Key 'EXCHANGE_API_KEY'
$apiSecret = Get-EnvValue -Path $envPath -Key 'EXCHANGE_API_SECRET'

$tmpEnv = [System.IO.Path]::GetTempFileName()
try {
    $lines = Get-Content $envDockerPath | Where-Object {
        ($_ -notmatch '^EXCHANGE_API_KEY=') -and
        ($_ -notmatch '^EXCHANGE_API_SECRET=') -and
        ($_ -notmatch '^MDTAS_CONFIG_FILE=')
    }

    $lines += 'MDTAS_CONFIG_FILE=./config.yaml'
    $lines += "EXCHANGE_API_KEY=$apiKey"
    $lines += "EXCHANGE_API_SECRET=$apiSecret"
    Set-Content -Path $tmpEnv -Value ($lines -join "`n") -NoNewline

    & $pscp -batch -pw $rootPassword $tmpEnv ("root@" + $ip + ":/opt/automated-trading-system/.env.docker")
    & $pscp -batch -pw $rootPassword $appPath ("root@" + $ip + ":/opt/automated-trading-system/src/mdtas/api/app.py")

    $remoteScriptPath = [System.IO.Path]::GetTempFileName()
    $remoteScript = @"
set -e
cd /opt/automated-trading-system
docker compose --env-file .env.docker up -d --build api ingestion trader
docker compose --env-file .env.docker ps api ingestion trader
grep -E '^(MDTAS_CONFIG_FILE|EXCHANGE_API_KEY|EXCHANGE_API_SECRET)=' .env.docker | sed 's/=.*//'
"@
    Set-Content -Path $remoteScriptPath -Value $remoteScript -NoNewline
    try {
        & $plink -batch -ssh -pw $rootPassword -m $remoteScriptPath ("root@" + $ip)
    }
    finally {
        Remove-Item $remoteScriptPath -ErrorAction SilentlyContinue
    }
}
finally {
    Remove-Item $tmpEnv -ErrorAction SilentlyContinue
}
