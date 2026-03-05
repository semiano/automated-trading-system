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
$plink = 'C:\Program Files\PuTTY\plink.exe'

if (-not (Test-Path $plink)) {
    throw "PuTTY plink not found at: $plink"
}

$droplets = doctl compute droplet list --output json | ConvertFrom-Json
$target = $droplets | Where-Object { $_.name -eq 'ubuntu-s-1vcpu-1gb-nyc3-01' } | Select-Object -First 1
if (-not $target) {
    throw 'Target droplet not found: ubuntu-s-1vcpu-1gb-nyc3-01'
}

$ip = ($target.networks.v4 | Where-Object { $_.type -eq 'public' } | Select-Object -First 1).ip_address
if (-not $ip) {
    throw 'No public IP found for target droplet'
}

$rootPassword = Get-EnvValue -Path $envPath -Key 'DIGITAL_OCEAN_VPS_ROOT_PW'
$apiKey = Get-EnvValue -Path $envPath -Key 'EXCHANGE_API_KEY'
$apiSecret = Get-EnvValue -Path $envPath -Key 'EXCHANGE_API_SECRET'

$k64 = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($apiKey))
$s64 = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($apiSecret))

$remoteScriptPath = [System.IO.Path]::GetTempFileName()

$remoteScript = @"
set -e
cd /opt/automated-trading-system
[ -f .env.docker ] || touch .env.docker
KEY=`$(printf %s '$k64' | base64 -d)
SECRET=`$(printf %s '$s64' | base64 -d)
sed -i '/^EXCHANGE_API_KEY=/d' .env.docker
sed -i '/^EXCHANGE_API_SECRET=/d' .env.docker
if grep -q '^MDTAS_CONFIG_FILE=' .env.docker; then
    sed -i 's|^MDTAS_CONFIG_FILE=.*|MDTAS_CONFIG_FILE=./config.yaml|' .env.docker
else
    echo 'MDTAS_CONFIG_FILE=./config.yaml' >> .env.docker
fi
printf '\nEXCHANGE_API_KEY=%s\nEXCHANGE_API_SECRET=%s\n' "\$KEY" "\$SECRET" >> .env.docker
docker compose --env-file .env.docker up -d api ingestion trader
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
