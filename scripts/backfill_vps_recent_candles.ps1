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
if (-not $ip) {
    throw "No public IP found"
}
$pw = Get-EnvValue -Path $envPath -Key "DIGITAL_OCEAN_VPS_ROOT_PW"

$remoteScript = [System.IO.Path]::GetTempFileName()
@'
set -e
cd /opt/automated-trading-system

echo "=== stopping ingestion ==="
docker compose --env-file .env.docker stop ingestion

echo "=== backfilling recent candles (12h) ==="
docker compose --env-file .env.docker exec -T api python - <<'PY'
from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import delete

from mdtas.config import get_config
from mdtas.db.models import Candle, UnresolvedGap
from mdtas.db.repo import CandleRepository
from mdtas.db.session import get_session
from mdtas.ingestion.live_updater import run_live_once
from mdtas.ingestion.scheduler import build_provider
from mdtas.utils.timeframes import align_to_candle_close, timeframe_to_timedelta

cfg = get_config()
cfg.ingestion.allow_gap_jump_to_recent = False

session = get_session()
repo = CandleRepository(session)
provider = build_provider(cfg)
venue = cfg.providers.ccxt.venue if cfg.providers.default_provider == "ccxt" else "mock"

symbols = ["XRP/USD", "HBAR/USD"]
end = datetime.utcnow().replace(second=0, microsecond=0)
start = end - timedelta(hours=12)

print(f"window_start={start.isoformat()} window_end={end.isoformat()}")

for symbol in symbols:
    print(f"--- {symbol} ---")
    for timeframe in cfg.timeframes:
        deleted_candles = (
            session.execute(
                delete(Candle).where(
                    Candle.symbol == symbol,
                    Candle.venue == venue,
                    Candle.timeframe == timeframe,
                    Candle.ts >= start,
                    Candle.ts <= end,
                )
            ).rowcount
            or 0
        )
        deleted_gaps = (
            session.execute(
                delete(UnresolvedGap).where(
                    UnresolvedGap.symbol == symbol,
                    UnresolvedGap.venue == venue,
                    UnresolvedGap.timeframe == timeframe,
                    UnresolvedGap.start_ts <= end,
                    UnresolvedGap.end_ts >= start,
                )
            ).rowcount
            or 0
        )
        print(f"deleted {timeframe}: candles={deleted_candles} gaps={deleted_gaps}")
    session.commit()

    for timeframe in cfg.timeframes:
        if timeframe == "1m":
            total_inserted = 0
            for i in range(1, 11):
                inserted = run_live_once(
                    repo=repo,
                    provider=provider,
                    cfg=cfg,
                    symbol=symbol,
                    timeframe=timeframe,
                    venue=venue,
                )
                total_inserted += inserted
                latest = repo.get_latest_candle_ts(symbol=symbol, timeframe=timeframe, venue=venue)
                now = datetime.utcnow().replace(microsecond=0)
                target = align_to_candle_close(now, timeframe) - timeframe_to_timedelta(timeframe)
                behind = None if latest is None else int((target - latest) / timeframe_to_timedelta(timeframe))
                print(f"backfilled {timeframe} pass={i}: inserted={inserted} latest={latest} target={target} behind={behind}")
                if inserted <= 0:
                    break
                if latest is not None and latest >= target:
                    break
            print(f"backfilled {timeframe}: total_inserted={total_inserted}")
        else:
            inserted = run_live_once(
                repo=repo,
                provider=provider,
                cfg=cfg,
                symbol=symbol,
                timeframe=timeframe,
                venue=venue,
            )
            print(f"backfilled {timeframe}: inserted={inserted}")

session.close()
PY

echo "=== starting ingestion ==="
docker compose --env-file .env.docker up -d ingestion
docker compose --env-file .env.docker ps ingestion
'@ | Set-Content -Path $remoteScript -NoNewline

try {
    & $plink -batch -ssh -pw $pw -m $remoteScript ("root@" + $ip)
}
finally {
    Remove-Item $remoteScript -ErrorAction SilentlyContinue
}
