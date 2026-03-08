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
from statistics import mean
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


def _mk_adapter(symbol: str, max_notional: float) -> CcxtExecutionAdapter:
    cfg = get_config()
    return CcxtExecutionAdapter(
        venue=cfg.providers.ccxt.venue,
        rate_limit=cfg.providers.ccxt.rate_limit,
        api_key=cfg.providers.ccxt.api_key,
        api_secret=cfg.providers.ccxt.api_secret,
        api_password=cfg.providers.ccxt.api_password,
        sandbox=False,
        live_trading_enabled=True,
        live_allow_short=True,
        live_max_order_notional_usd=max_notional,
        live_allowed_symbols=[symbol],
        live_require_explicit_env_ack=False,
        live_ack_env_var_name="MDTAS_ENABLE_LIVE_TRADING",
        live_ack_env_var_value="YES_I_ACKNOWLEDGE_LIVE_TRADING_RISK",
    )


def _constraints(symbol: str) -> SymbolExecutionConstraints:
    cfg = get_config()
    c = cfg.trading.per_asset_constraints.get(symbol, cfg.trading.default_constraints)
    return SymbolExecutionConstraints(
        min_notional_usd=float(c.min_notional_usd),
        qty_step=float(c.qty_step),
        price_tick=float(c.price_tick) if c.price_tick is not None else None,
        fee_bps=float(c.fee_bps),
    )


def _leg_metrics(raw: float, fill_price: float, fee: float, notional: float, is_buy: bool) -> dict[str, float]:
    if is_buy:
        slip_bps = ((fill_price - raw) / raw) * 10000.0
    else:
        slip_bps = ((raw - fill_price) / raw) * 10000.0
    fee_bps = (fee / notional * 10000.0) if notional > 0 else 0.0
    return {"slippage_bps": float(slip_bps), "fee_bps": float(fee_bps)}


symbol = "BTC/USD"
notionals = [10.0, 25.0]
all_roundtrips: list[dict[str, float]] = []
short_style_runs: list[dict[str, Any]] = []

for target_notional in notionals:
    adapter = _mk_adapter(symbol, target_notional)
    constraints = _constraints(symbol)

    ticker_entry = adapter.exchange.fetch_ticker(symbol)
    raw_entry = _price_from_ticker(ticker_entry)
    qty = round_down_to_step(target_notional / raw_entry, constraints.qty_step)
    if qty <= 0:
        continue

    entry = adapter.submit_entry(symbol=symbol, raw_price=raw_entry, qty=qty, trade_side="long", constraints=constraints)
    time.sleep(1.5)
    ticker_exit = adapter.exchange.fetch_ticker(symbol)
    raw_exit = _price_from_ticker(ticker_exit)
    exit_fill = adapter.submit_exit(symbol=symbol, raw_price=raw_exit, qty=float(entry.qty), trade_side="long", constraints=constraints)

    em = _leg_metrics(raw_entry, float(entry.price), float(entry.fee_usd), float(entry.notional_usd), is_buy=True)
    xm = _leg_metrics(raw_exit, float(exit_fill.price), float(exit_fill.fee_usd), float(exit_fill.notional_usd), is_buy=False)

    all_roundtrips.append(
        {
            "target_notional": target_notional,
            "qty": float(entry.qty),
            "entry_slippage_bps": em["slippage_bps"],
            "entry_fee_bps": em["fee_bps"],
            "exit_slippage_bps": xm["slippage_bps"],
            "exit_fee_bps": xm["fee_bps"],
            "entry_fee_usd": float(entry.fee_usd),
            "exit_fee_usd": float(exit_fill.fee_usd),
            "entry_notional": float(entry.notional_usd),
            "exit_notional": float(exit_fill.notional_usd),
        }
    )

# Try short-style cycle on spot: sell then buy same qty.
# If no base inventory exists, bootstrap a tiny inventory and flatten at the end.
adapter = _mk_adapter(symbol, 25.0)
constraints = _constraints(symbol)
bal = adapter.exchange.fetch_balance()
base = symbol.split("/")[0]
free_base = float((bal.get(base) or {}).get("free") or 0.0)

ticker = adapter.exchange.fetch_ticker(symbol)
raw1 = _price_from_ticker(ticker)
qty_short = round_down_to_step(min(max(free_base * 0.95, 0.0), 25.0 / raw1), constraints.qty_step)

bootstrap_fill = None
if qty_short <= 0:
    qty_short = round_down_to_step(10.0 / raw1, constraints.qty_step)
    if qty_short > 0:
        bootstrap_fill = adapter.submit_entry(symbol=symbol, raw_price=raw1, qty=qty_short, trade_side="long", constraints=constraints)
        time.sleep(1.0)

if qty_short > 0:
    ticker = adapter.exchange.fetch_ticker(symbol)
    raw1 = _price_from_ticker(ticker)
    sell_fill = adapter.submit_entry(symbol=symbol, raw_price=raw1, qty=qty_short, trade_side="short", constraints=constraints)
    time.sleep(1.5)
    ticker2 = adapter.exchange.fetch_ticker(symbol)
    raw2 = _price_from_ticker(ticker2)
    buy_fill = adapter.submit_exit(symbol=symbol, raw_price=raw2, qty=float(sell_fill.qty), trade_side="short", constraints=constraints)

    sm = _leg_metrics(raw1, float(sell_fill.price), float(sell_fill.fee_usd), float(sell_fill.notional_usd), is_buy=False)
    bm = _leg_metrics(raw2, float(buy_fill.price), float(buy_fill.fee_usd), float(buy_fill.notional_usd), is_buy=True)

    short_style_runs.append(
        {
            "qty": float(sell_fill.qty),
            "sell_slippage_bps": sm["slippage_bps"],
            "sell_fee_bps": sm["fee_bps"],
            "buy_slippage_bps": bm["slippage_bps"],
            "buy_fee_bps": bm["fee_bps"],
            "sell_fee_usd": float(sell_fill.fee_usd),
            "buy_fee_usd": float(buy_fill.fee_usd),
            "bootstrap_used": bootstrap_fill is not None,
        }
    )

    if bootstrap_fill is not None:
        time.sleep(1.0)
        ticker3 = adapter.exchange.fetch_ticker(symbol)
        raw3 = _price_from_ticker(ticker3)
        adapter.submit_exit(symbol=symbol, raw_price=raw3, qty=float(bootstrap_fill.qty), trade_side="long", constraints=constraints)

summary = {
    "symbol": symbol,
    "roundtrips": all_roundtrips,
    "short_style_spot_sell_buy": short_style_runs,
    "recommended_paper_calibration": {
        "fee_bps": float(mean([x["entry_fee_bps"] for x in all_roundtrips] + [x["exit_fee_bps"] for x in all_roundtrips])) if all_roundtrips else None,
        "slippage_bps": float(mean([abs(x["entry_slippage_bps"]) for x in all_roundtrips] + [abs(x["exit_slippage_bps"]) for x in all_roundtrips])) if all_roundtrips else None,
    },
    "notes": [
        "short entry in this engine is a spot SELL when trade_side='short' in ccxt adapter",
        "on spot, this requires base inventory; it is not a margin borrow short",
    ],
}
print(json.dumps(summary, indent=2))
PY
'@ | Set-Content -Path $remoteScript -NoNewline

try {
    & $plink -batch -ssh -pw $pw -m $remoteScript ("root@" + $ip)
}
finally {
    Remove-Item $remoteScript -ErrorAction SilentlyContinue
}
