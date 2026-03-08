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

docker compose --env-file .env.docker exec -T api python - <<'PY'
from __future__ import annotations

import json
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

import pandas as pd

from mdtas.config import get_config
from mdtas.indicators.engine import compute
from mdtas.trading.execution import PaperExecutionAdapter, SymbolExecutionConstraints, gap_aware_raw_exit_price
from mdtas.trading.runtime import AssetParamResolver, compute_entry_sizing, evaluate_entry_guards

SYMBOL = "XRP/USD"
VENUE = "coinbase"
LTF = "1m"
LOOKBACK_DAYS = 5
THRESHOLDS = [0.04, 0.06, 0.08, 0.10, 0.12, 0.15]
FEE_BPS_OVERRIDE = 0.0
SLIPPAGE_BPS_OVERRIDE = 0.0


def fetch_json(path: str, query: dict[str, str]) -> list[dict]:
    qs = urllib.parse.urlencode(query)
    url = f"http://localhost:8000{path}?{qs}"
    with urllib.request.urlopen(url, timeout=40) as r:
        return json.loads(r.read().decode("utf-8"))


cfg = get_config()
resolver = AssetParamResolver(cfg)
params = resolver.for_symbol(SYMBOL)

controls = fetch_json("/api/v1/control-plane/assets", {})
asset = next((x for x in controls if x.get("symbol") == SYMBOL), None)
trade_side_mode = asset.get("trade_side") if isinstance(asset, dict) else "long_only"
if trade_side_mode not in {"long_only", "long_short", "short_only"}:
    trade_side_mode = "long_only"

end_utc = datetime.now(timezone.utc).replace(second=0, microsecond=0)
start_utc = end_utc - timedelta(days=LOOKBACK_DAYS)

rows = fetch_json(
    "/api/v1/candles",
    {
        "symbol": SYMBOL,
        "timeframe": LTF,
        "venue": VENUE,
        "start": start_utc.isoformat(),
        "end": end_utc.isoformat(),
        "limit": "12000",
    },
)
if len(rows) < 500:
    raise SystemExit(f"Not enough LTF candles returned: {len(rows)}")

ltf = pd.DataFrame(rows)
ltf["ts"] = pd.to_datetime(ltf["ts"], utc=True).dt.tz_localize(None)
ltf = ltf.sort_values("ts").reset_index(drop=True)

indicators = ["rsi", "atr", f"ema{params.ema_fast}", f"ema{params.ema_slow}"]
indicator_params = params.indicator_params()
if cfg.trading.bb_entry_mode != "off":
    indicators.append("bbands")
    indicator_params["bollinger"] = {
        "length": int(cfg.indicators.bollinger.length),
        "stdev": float(cfg.indicators.bollinger.stdev),
    }
if cfg.trading.momentum_swing_enabled:
    indicators.append("momentum_swing")
    indicator_params["momentum_swing"] = {
        "pivot_left_bars": int(cfg.trading.momentum_pivot_left_bars),
        "pivot_right_bars": int(cfg.trading.momentum_pivot_right_bars),
        "lookback_bars": int(cfg.trading.momentum_lookback_bars),
        "roc_length": int(cfg.trading.momentum_roc_length),
        "min_roc": float(cfg.trading.momentum_min_roc),
    }

work = compute(ltf, indicators, indicator_params)

constraints_cfg = cfg.trading.per_asset_constraints.get(SYMBOL, cfg.trading.default_constraints)
constraints = SymbolExecutionConstraints(
    min_notional_usd=float(constraints_cfg.min_notional_usd),
    qty_step=float(constraints_cfg.qty_step),
    price_tick=float(constraints_cfg.price_tick) if constraints_cfg.price_tick is not None else None,
    fee_bps=float(FEE_BPS_OVERRIDE),
)


def run_for_threshold(min_entry_atr_pct: float) -> dict:
    paper = PaperExecutionAdapter(slippage_bps=float(SLIPPAGE_BPS_OVERRIDE))
    position = None
    entries_ts: list[datetime] = []
    last_exit_ts = None
    last_exit_reason = None
    blocked_vol = 0
    candidate_pre_vol = 0
    trades: list[float] = []

    for i in range(1, len(work)):
        prev = work.iloc[i - 1]
        bar = work.iloc[i]
        decision_ts = pd.to_datetime(bar["ts"]).to_pydatetime().replace(tzinfo=None)

        fast_col = f"ema{params.ema_fast}"
        close = float(prev["close"]) if pd.notna(prev.get("close")) else None
        atr = float(prev["atr"]) if pd.notna(prev.get("atr")) else None

        if position is None:
            long_allowed = trade_side_mode in {"long_only", "long_short"}
            short_allowed = trade_side_mode in {"short_only", "long_short"}

            long_ok = False
            short_ok = False
            if close is not None and atr is not None and pd.notna(prev.get("rsi")) and pd.notna(prev.get(fast_col)):
                long_ok = float(prev["rsi"]) <= params.rsi_entry and close > float(prev[fast_col])
                short_ok = float(prev["rsi"]) >= params.rsi_exit and close < float(prev[fast_col])
                if cfg.trading.momentum_swing_enabled:
                    long_ok = long_ok and bool(prev.get("swing_long_ready"))
                    short_ok = short_ok and bool(prev.get("swing_short_ready"))

            chosen_side = None
            if long_allowed and long_ok:
                chosen_side = "long"
            elif short_allowed and short_ok:
                chosen_side = "short"

            if chosen_side is None:
                continue

            candidate_pre_vol += 1
            atr_pct = (atr / close) * 100.0 if close and close > 0 else float("nan")
            if not (pd.notna(atr_pct) and atr_pct >= min_entry_atr_pct):
                blocked_vol += 1
                continue

            entries_last_hour = sum(1 for ts in entries_ts if ts >= (decision_ts - timedelta(hours=1)))
            entries_last_day = sum(1 for ts in entries_ts if ts >= (decision_ts - timedelta(days=1)))
            guard = evaluate_entry_guards(
                decision_ts=decision_ts,
                timeframe=LTF,
                last_exit_ts=last_exit_ts,
                last_exit_reason=last_exit_reason,
                cooldown_bars_after_exit=int(cfg.trading.cooldown_bars_after_exit),
                cooldown_bars_after_stop=int(cfg.trading.cooldown_bars_after_stop),
                entries_last_hour=entries_last_hour,
                entries_last_day=entries_last_day,
                max_entries_per_hour=int(cfg.trading.max_entries_per_hour),
                max_entries_per_day=int(cfg.trading.max_entries_per_day),
            )
            if guard.blocked_reason is not None:
                continue

            sizing = compute_entry_sizing(
                sizing_mode=cfg.trading.sizing_mode,
                position_size_usd=float(cfg.trading.position_size_usd),
                risk_per_trade_usd=float(cfg.trading.risk_per_trade_usd),
                max_position_notional_usd=cfg.trading.max_position_notional_usd,
                raw_entry_price=float(bar["open"]),
                atr=atr,
                stop_atr=float(params.stop_atr),
                qty_step=float(constraints.qty_step),
            )
            if sizing.sizing_reason is not None or sizing.qty_final <= 0:
                continue

            entry_fill = paper.submit_entry(
                symbol=SYMBOL,
                raw_price=float(bar["open"]),
                qty=float(sizing.qty_final),
                trade_side=chosen_side,
                constraints=constraints,
            )
            atr_for_stops = float(prev["atr"])
            if chosen_side == "short":
                stop_price = float(entry_fill.price) + (params.stop_atr * atr_for_stops)
                tp_price = float(entry_fill.price) - (params.take_profit_atr * atr_for_stops)
            else:
                stop_price = float(entry_fill.price) - (params.stop_atr * atr_for_stops)
                tp_price = float(entry_fill.price) + (params.take_profit_atr * atr_for_stops)

            position = {
                "side": chosen_side,
                "entry_price": float(entry_fill.price),
                "qty": float(entry_fill.qty),
                "entry_fee": float(entry_fill.fee_usd),
                "stop_price": float(stop_price),
                "tp_price": float(tp_price),
                "hold_bars": 0,
            }
            entries_ts.append(decision_ts)
            continue

        side = position["side"]
        hold_bars = int(position["hold_bars"]) + 1
        if side == "short":
            stop_hit = float(bar["high"]) >= float(position["stop_price"])
            tp_hit = float(bar["low"]) <= float(position["tp_price"])
        else:
            stop_hit = float(bar["low"]) <= float(position["stop_price"])
            tp_hit = float(bar["high"]) >= float(position["tp_price"])

        indicator_exit = False
        if pd.notna(prev.get("rsi")) and pd.notna(prev.get(fast_col)) and pd.notna(prev.get("close")):
            if hold_bars >= int(cfg.trading.min_hold_bars_before_signal_exit):
                if side == "short":
                    indicator_exit = float(prev["rsi"]) <= params.rsi_entry or float(prev["close"]) > float(prev[fast_col])
                else:
                    indicator_exit = float(prev["rsi"]) >= params.rsi_exit or float(prev["close"]) < float(prev[fast_col])

        timed_exit = hold_bars >= params.max_hold_bars
        if not (stop_hit or tp_hit or indicator_exit or timed_exit):
            position["hold_bars"] = hold_bars
            continue

        reason = "stop" if stop_hit else ("take_profit" if tp_hit else ("signal" if indicator_exit else "max_hold"))
        raw_exit = gap_aware_raw_exit_price(
            trade_side=side,
            reason=reason,
            bar_open=float(bar["open"]),
            stop_price=float(position["stop_price"]),
            take_profit_price=float(position["tp_price"]),
        )
        exit_fill = paper.submit_exit(
            symbol=SYMBOL,
            raw_price=raw_exit,
            qty=float(position["qty"]),
            trade_side=side,
            constraints=constraints,
        )

        if side == "short":
            gross = (float(position["entry_price"]) - float(exit_fill.price)) * float(position["qty"])
        else:
            gross = (float(exit_fill.price) - float(position["entry_price"])) * float(position["qty"])
        fees = float(position["entry_fee"]) + float(exit_fill.fee_usd)
        trades.append(gross - fees)

        last_exit_ts = decision_ts
        last_exit_reason = reason
        position = None

    trade_count = len(trades)
    return {
        "min_entry_atr_pct": min_entry_atr_pct,
        "candidate_pre_vol": candidate_pre_vol,
        "blocked_by_vol": blocked_vol,
        "vol_block_rate": (blocked_vol / candidate_pre_vol) if candidate_pre_vol else 0.0,
        "trade_count": trade_count,
        "net_pnl_total": float(sum(trades)),
        "win_rate": (sum(1 for t in trades if t > 0) / trade_count) if trade_count else 0.0,
    }


summary = {
    "symbol": SYMBOL,
    "timeframe": LTF,
    "lookback_days": LOOKBACK_DAYS,
    "trade_side_mode": trade_side_mode,
    "results": [run_for_threshold(v) for v in THRESHOLDS],
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
