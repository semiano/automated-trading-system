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

set -a
if [ -f ./.env.docker ]; then
    . ./.env.docker
fi
if [ -f ./.env ]; then
    . ./.env
fi
set +a

docker compose --env-file .env.docker exec -T \
    -e EXCHANGE_API_KEY \
    -e EXCHANGE_API_SECRET \
    -e EXCHANGE_API_PASSWORD \
    -e EXCHANGE_SANDBOX \
    api python - <<'PY'
from __future__ import annotations

import json
import time
from typing import Any

from mdtas.config import get_config
from mdtas.trading.execution import CcxtExecutionAdapter, SymbolExecutionConstraints, round_down_to_step


def _price_from_ticker(ticker: dict[str, Any]) -> float:
    for key in ("last", "close", "bid", "ask"):
        value = ticker.get(key)
        if value is not None:
            price = float(value)
            if price > 0:
                return price
    raise ValueError("No usable price in ticker")


cfg = get_config()
symbol = "BTC/USD"
max_notional = 10.0

adapter = CcxtExecutionAdapter(
    venue=cfg.providers.ccxt.venue,
    rate_limit=cfg.providers.ccxt.rate_limit,
    api_key=cfg.providers.ccxt.api_key,
    api_secret=cfg.providers.ccxt.api_secret,
    api_password=cfg.providers.ccxt.api_password,
    sandbox=False,
    live_trading_enabled=True,
    live_allow_short=False,
    live_max_order_notional_usd=max_notional,
    live_allowed_symbols=[symbol],
    live_require_explicit_env_ack=False,
    live_ack_env_var_name="MDTAS_ENABLE_LIVE_TRADING",
    live_ack_env_var_value="YES_I_ACKNOWLEDGE_LIVE_TRADING_RISK",
)

constraints_cfg = cfg.trading.per_asset_constraints.get(symbol, cfg.trading.default_constraints)
constraints = SymbolExecutionConstraints(
    min_notional_usd=float(constraints_cfg.min_notional_usd),
    qty_step=float(constraints_cfg.qty_step),
    price_tick=float(constraints_cfg.price_tick) if constraints_cfg.price_tick is not None else None,
    fee_bps=float(constraints_cfg.fee_bps),
)

entry_ticker = adapter.exchange.fetch_ticker(symbol)
entry_raw = _price_from_ticker(entry_ticker)
target_notional = max_notional
qty = round_down_to_step(target_notional / entry_raw, float(constraints.qty_step))
if qty <= 0:
    raise SystemExit("Computed qty is zero after step rounding")

entry = adapter.submit_entry(
    symbol=symbol,
    raw_price=entry_raw,
    qty=float(qty),
    trade_side="long",
    constraints=constraints,
)

# Short pause so exit leg gets an independent market sample.
time.sleep(1.5)
exit_ticker = adapter.exchange.fetch_ticker(symbol)
exit_raw = _price_from_ticker(exit_ticker)
exit_fill = adapter.submit_exit(
    symbol=symbol,
    raw_price=exit_raw,
    qty=float(entry.qty),
    trade_side="long",
    constraints=constraints,
)

entry_slippage_bps = ((float(entry.price) - float(entry_raw)) / float(entry_raw)) * 10000.0
exit_slippage_bps = ((float(exit_raw) - float(exit_fill.price)) / float(exit_raw)) * 10000.0
entry_fee_bps = (float(entry.fee_usd) / float(entry.notional_usd) * 10000.0) if float(entry.notional_usd) > 0 else 0.0
exit_fee_bps = (float(exit_fill.fee_usd) / float(exit_fill.notional_usd) * 10000.0) if float(exit_fill.notional_usd) > 0 else 0.0

qty_f = float(entry.qty)
gross_pnl = (float(exit_fill.price) - float(entry.price)) * qty_f
fees_total = float(entry.fee_usd) + float(exit_fill.fee_usd)
net_pnl = gross_pnl - fees_total

result = {
    "config_path": "env+runtime_override",
    "symbol": symbol,
    "qty": qty_f,
    "target_notional": target_notional,
    "entry": {
        "raw_price": float(entry_raw),
        "fill_price": float(entry.price),
        "notional_usd": float(entry.notional_usd),
        "fee_usd": float(entry.fee_usd),
        "slippage_bps": float(entry_slippage_bps),
        "fee_bps_realized": float(entry_fee_bps),
    },
    "exit": {
        "raw_price": float(exit_raw),
        "fill_price": float(exit_fill.price),
        "notional_usd": float(exit_fill.notional_usd),
        "fee_usd": float(exit_fill.fee_usd),
        "slippage_bps": float(exit_slippage_bps),
        "fee_bps_realized": float(exit_fee_bps),
    },
    "roundtrip": {
        "gross_pnl_usd": float(gross_pnl),
        "fees_total_usd": float(fees_total),
        "net_pnl_usd": float(net_pnl),
    },
}
print(json.dumps(result, indent=2))
PY
'@ | Set-Content -Path $remoteScript -NoNewline

try {
    & $plink -batch -ssh -pw $pw -m $remoteScript ("root@" + $ip)
}
finally {
    Remove-Item $remoteScript -ErrorAction SilentlyContinue
}
