param(
    [string]$EnvFile = ".env.docker",
    [string]$Symbol = "BTC/USDT",
    [string]$Timeframe = "5m",
    [string]$Venue = "mock",
    [string]$ApiBase = "http://localhost:8000/api/v1",
    [int]$BackfillDays = 2,
    [int]$HealthTimeoutSeconds = 180
)

$ErrorActionPreference = "Stop"

function Write-SmokeLog {
    param([string]$Message)
    Write-Host "[smoke] $Message"
}

function Invoke-Compose {
    param([Parameter(ValueFromRemainingArguments = $true)][string[]]$Args)
    & docker compose --env-file $EnvFile @Args
}

function Show-Diagnostics {
    Write-SmokeLog "Diagnostic snapshot:"
    try { Invoke-Compose ps } catch {}
    try { Invoke-Compose logs --tail=120 api postgres ingestion trader web } catch {}
}

function Wait-ServiceHealthy {
    param(
        [string]$Service,
        [int]$TimeoutSeconds
    )

    $start = Get-Date
    while ($true) {
        $containerId = (Invoke-Compose ps -q $Service | Out-String).Trim()
        if (-not [string]::IsNullOrWhiteSpace($containerId)) {
            $state = (& docker inspect -f "{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}" $containerId | Out-String).Trim()
            if ($state -eq "healthy" -or $state -eq "running") {
                Write-SmokeLog "$Service status=$state"
                return
            }
            if ($state -eq "unhealthy" -or $state -eq "exited" -or $state -eq "dead") {
                throw "$Service entered bad state: $state"
            }
        }

        if (((Get-Date) - $start).TotalSeconds -gt $TimeoutSeconds) {
            throw "Timeout waiting for $Service to be healthy/running"
        }
        Start-Sleep -Seconds 2
    }
}

try {
    Write-SmokeLog "Starting compose stack with $EnvFile"
    Invoke-Compose up --build -d | Out-Null

    Wait-ServiceHealthy -Service "postgres" -TimeoutSeconds $HealthTimeoutSeconds
    Wait-ServiceHealthy -Service "api" -TimeoutSeconds $HealthTimeoutSeconds

    Write-SmokeLog "Validating /health"
    $health = Invoke-RestMethod -Method Get -Uri "$ApiBase/health" -TimeoutSec 10
    if ($null -eq $health) {
        throw "Health endpoint returned null"
    }

    Write-SmokeLog "Triggering backfill for $Symbol $Timeframe $Venue"
    $backfillBody = @{
        symbols      = @($Symbol)
        timeframes   = @($Timeframe)
        venue        = $Venue
        lookback_days = $BackfillDays
    } | ConvertTo-Json -Depth 5

    $backfill = Invoke-RestMethod -Method Post -Uri "$ApiBase/backfill" -ContentType "application/json" -Body $backfillBody -TimeoutSec 60
    if ($null -eq $backfill -or $backfill.Count -lt 1) {
        throw "Backfill response empty"
    }

    $escapedSymbol = [System.Uri]::EscapeDataString($Symbol)
    $query = "symbol=$escapedSymbol&timeframe=$Timeframe&venue=$Venue&limit=200"

    Write-SmokeLog "Asserting candles response"
    $candles = Invoke-RestMethod -Method Get -Uri "$ApiBase/candles?$query" -TimeoutSec 30
    if ($null -eq $candles -or $candles.Count -lt 1) {
        throw "Candles response empty"
    }
    $requiredCandleKeys = @("ts", "open", "high", "low", "close", "volume")
    foreach ($key in $requiredCandleKeys) {
        if (-not ($candles[0].PSObject.Properties.Name -contains $key)) {
            throw "Candles response missing key: $key"
        }
    }

    Write-SmokeLog "Asserting indicators response"
    $indicators = Invoke-RestMethod -Method Get -Uri "$ApiBase/indicators?$query&indicators=bbands,rsi,atr,ema20" -TimeoutSec 30
    if ($null -eq $indicators.rows -or $indicators.rows.Count -lt 1) {
        throw "Indicators rows empty"
    }

    Write-SmokeLog "Asserting features response"
    $features = Invoke-RestMethod -Method Get -Uri "$ApiBase/features?$query&indicators=bbands,rsi,atr,ema20,ema50" -TimeoutSec 30
    if ($null -eq $features.rows -or $features.rows.Count -lt 1) {
        throw "Features rows empty"
    }

    Write-SmokeLog "Smoke test passed ✅"
    exit 0
}
catch {
    Write-SmokeLog "Smoke test failed: $($_.Exception.Message)"
    Show-Diagnostics
    exit 1
}
