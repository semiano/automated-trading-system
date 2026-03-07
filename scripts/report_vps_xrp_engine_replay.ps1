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
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import urllib.parse
import urllib.request

import pandas as pd

from mdtas.config import get_config
from mdtas.indicators.engine import compute
from mdtas.trading.execution import PaperExecutionAdapter, SymbolExecutionConstraints, gap_aware_raw_exit_price
from mdtas.trading.regime import compute_htf_regime
from mdtas.trading.runtime import AssetParamResolver, compute_entry_sizing, evaluate_entry_guards
from mdtas.utils.timeframes import timeframe_to_timedelta

SYMBOL = "XRP/USD"
VENUE = "coinbase"
LTF = "1m"
LOOKBACK_HOURS = 12


def fetch_json(path: str, query: dict[str, str]) -> list[dict]:
    qs = urllib.parse.urlencode(query)
    url = f"http://localhost:8000{path}?{qs}"
    with urllib.request.urlopen(url, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


@dataclass
class Position:
    side: str
    entry_ts: datetime
    entry_price: float
    qty: float
    entry_fee: float
    stop_price: float | None
    take_profit_price: float | None
    hold_bars: int


def parse_dt(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00")).replace(tzinfo=None)


cfg = get_config()
resolver = AssetParamResolver(cfg)
params = resolver.for_symbol(SYMBOL)

controls = fetch_json("/api/v1/control-plane/assets", {})
asset = next((x for x in controls if x.get("symbol") == SYMBOL), None)
trade_side_mode = asset.get("trade_side") if isinstance(asset, dict) else "long_only"
if trade_side_mode not in {"long_only", "long_short", "short_only"}:
    trade_side_mode = "long_only"

end_utc = datetime.now(timezone.utc).replace(second=0, microsecond=0)
start_utc = end_utc - timedelta(hours=LOOKBACK_HOURS)

ltf_rows = fetch_json(
    "/api/v1/candles",
    {
        "symbol": SYMBOL,
        "timeframe": LTF,
        "venue": VENUE,
        "start": start_utc.isoformat(),
        "end": end_utc.isoformat(),
        "limit": "5000",
    },
)
if len(ltf_rows) < 20:
    raise SystemExit(f"Not enough LTF candles returned: {len(ltf_rows)}")

ltf = pd.DataFrame(ltf_rows)
ltf["ts"] = pd.to_datetime(ltf["ts"], utc=True).dt.tz_localize(None)
ltf = ltf.sort_values("ts").reset_index(drop=True)

htf = None
if cfg.trading.use_regime_filter:
    htf_start_utc = end_utc - timedelta(days=30)
    htf_rows = fetch_json(
        "/api/v1/candles",
        {
            "symbol": SYMBOL,
            "timeframe": cfg.trading.htf_timeframe,
            "venue": VENUE,
            "start": htf_start_utc.isoformat(),
            "end": end_utc.isoformat(),
            "limit": "5000",
        },
    )
    htf = pd.DataFrame(htf_rows)
    if len(htf) > 0:
        htf["ts"] = pd.to_datetime(htf["ts"], utc=True).dt.tz_localize(None)
        htf = htf.sort_values("ts").reset_index(drop=True)

indicators = ["rsi", "atr", f"ema{params.ema_fast}", f"ema{params.ema_slow}"]
indicator_params = params.indicator_params()
bb_mode = str(cfg.trading.bb_entry_mode)
if bb_mode != "off":
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
    fee_bps=float(constraints_cfg.fee_bps),
)
paper = PaperExecutionAdapter(slippage_bps=float(cfg.trading.slippage_bps))

blocked = Counter()
candidate = Counter()
entries_ts: list[datetime] = []
position: Position | None = None
last_exit_ts: datetime | None = None
last_exit_reason: str | None = None

trades: list[dict] = []


def entry_diag_long(prev: pd.Series) -> tuple[bool, str]:
    fast_col = f"ema{params.ema_fast}"
    miss = []
    if pd.isna(prev.get("rsi")):
        miss.append("rsi")
    if pd.isna(prev.get("atr")):
        miss.append("atr")
    if pd.isna(prev.get(fast_col)):
        miss.append(fast_col)
    if pd.isna(prev.get("close")):
        miss.append("close")
    if bb_mode != "off" and pd.isna(prev.get("bb_lower")):
        miss.append("bb_lower")
    if bb_mode == "range_revert" and pd.isna(prev.get("bb_upper")):
        miss.append("bb_upper")
    if cfg.trading.momentum_swing_enabled and pd.isna(prev.get("swing_long_ready")):
        miss.append("swing_long_ready")
    if miss:
        return False, f"missing={','.join(miss)}"

    rsi = float(prev["rsi"])
    close = float(prev["close"])
    ema_fast = float(prev[fast_col])
    pass_rsi = rsi <= params.rsi_entry
    pass_trend = close > ema_fast
    pass_bb = True
    if bb_mode == "touch_revert":
        pass_bb = close <= float(prev["bb_lower"])
    elif bb_mode == "range_revert":
        bb_lower = float(prev["bb_lower"])
        bb_upper = float(prev["bb_upper"])
        bb_range = bb_upper - bb_lower
        thr = min(max(float(cfg.trading.bb_range_threshold_pct), 0.0), 1.0)
        pass_bb = bb_range > 0 and close <= (bb_lower + thr * bb_range)

    pass_mom = True
    if cfg.trading.momentum_swing_enabled:
        pass_mom = bool(prev["swing_long_ready"])

    return pass_rsi and pass_trend and pass_bb and pass_mom, "long"


def entry_diag_short(prev: pd.Series) -> tuple[bool, str]:
    fast_col = f"ema{params.ema_fast}"
    miss = []
    if pd.isna(prev.get("rsi")):
        miss.append("rsi")
    if pd.isna(prev.get("atr")):
        miss.append("atr")
    if pd.isna(prev.get(fast_col)):
        miss.append(fast_col)
    if pd.isna(prev.get("close")):
        miss.append("close")
    if bb_mode != "off" and pd.isna(prev.get("bb_upper")):
        miss.append("bb_upper")
    if bb_mode == "range_revert" and pd.isna(prev.get("bb_lower")):
        miss.append("bb_lower")
    if cfg.trading.momentum_swing_enabled and pd.isna(prev.get("swing_short_ready")):
        miss.append("swing_short_ready")
    if miss:
        return False, f"missing={','.join(miss)}"

    rsi = float(prev["rsi"])
    close = float(prev["close"])
    ema_fast = float(prev[fast_col])
    pass_rsi = rsi >= params.rsi_exit
    pass_trend = close < ema_fast
    pass_bb = True
    if bb_mode == "touch_revert":
        pass_bb = close >= float(prev["bb_upper"])
    elif bb_mode == "range_revert":
        bb_lower = float(prev["bb_lower"])
        bb_upper = float(prev["bb_upper"])
        bb_range = bb_upper - bb_lower
        thr = min(max(float(cfg.trading.bb_range_threshold_pct), 0.0), 1.0)
        pass_bb = bb_range > 0 and close >= (bb_upper - thr * bb_range)

    pass_mom = True
    if cfg.trading.momentum_swing_enabled:
        pass_mom = bool(prev["swing_short_ready"])

    return pass_rsi and pass_trend and pass_bb and pass_mom, "short"


def count_entries_since(ts_start: datetime) -> int:
    return sum(1 for ts in entries_ts if ts >= ts_start)


for i in range(1, len(work)):
    prev = work.iloc[i - 1]
    bar = work.iloc[i]
    decision_ts = parse_dt(str(bar["ts"]))

    if position is None:
        long_allowed = trade_side_mode in {"long_only", "long_short"}
        short_allowed = trade_side_mode in {"short_only", "long_short"}

        long_ok, _ = entry_diag_long(prev)
        short_ok, _ = entry_diag_short(prev)
        if long_ok:
            candidate["long_signal"] += 1
        if short_ok:
            candidate["short_signal"] += 1

        chosen: str | None = None
        if long_allowed and long_ok:
            chosen = "long"
        elif short_allowed and short_ok:
            chosen = "short"

        if chosen is None:
            blocked["no_entry_signal_or_side_mode"] += 1
            continue

        if cfg.trading.use_regime_filter and htf is not None and len(htf) > 0:
            aligned = htf[htf["ts"] <= decision_ts].copy()
            regime = compute_htf_regime(aligned, cfg)
            if regime.get("chop_state") == "chop":
                blocked["blocked_by_chop_filter"] += 1
                continue
            trend = regime.get("trend_state")
            trend_ok = (chosen == "long" and trend == "bull") or (chosen == "short" and trend == "bear")
            if not trend_ok:
                blocked["blocked_by_regime_trend"] += 1
                continue

        guard = evaluate_entry_guards(
            decision_ts=decision_ts,
            timeframe=LTF,
            last_exit_ts=last_exit_ts,
            last_exit_reason=last_exit_reason,
            cooldown_bars_after_exit=int(cfg.trading.cooldown_bars_after_exit),
            cooldown_bars_after_stop=int(cfg.trading.cooldown_bars_after_stop),
            entries_last_hour=count_entries_since(decision_ts - timeframe_to_timedelta("1h")),
            entries_last_day=count_entries_since(decision_ts - timeframe_to_timedelta("1d")),
            max_entries_per_hour=int(cfg.trading.max_entries_per_hour),
            max_entries_per_day=int(cfg.trading.max_entries_per_day),
        )
        if guard.blocked_reason is not None:
            blocked[guard.blocked_reason] += 1
            continue

        raw_entry = float(bar["open"])
        atr = float(prev["atr"]) if pd.notna(prev.get("atr")) else None
        sizing = compute_entry_sizing(
            sizing_mode=cfg.trading.sizing_mode,
            position_size_usd=float(cfg.trading.position_size_usd),
            risk_per_trade_usd=float(cfg.trading.risk_per_trade_usd),
            max_position_notional_usd=cfg.trading.max_position_notional_usd,
            raw_entry_price=raw_entry,
            atr=atr,
            stop_atr=float(params.stop_atr),
            qty_step=float(constraints.qty_step),
        )
        if sizing.sizing_reason is not None or sizing.qty_final <= 0:
            blocked["sizing_invalid"] += 1
            continue

        entry_fill = paper.submit_entry(
            symbol=SYMBOL,
            raw_price=raw_entry,
            qty=float(sizing.qty_final),
            trade_side=chosen,
            constraints=constraints,
        )
        entry_notional = float(entry_fill.price) * float(entry_fill.qty)

        if cfg.trading.max_position_notional_usd is not None and cfg.trading.max_position_notional_usd > 0:
            if entry_notional > float(cfg.trading.max_position_notional_usd):
                blocked["max_notional_blocked"] += 1
                continue

        if constraints.min_notional_usd > 0 and entry_notional < constraints.min_notional_usd:
            blocked["min_notional_blocked"] += 1
            continue

        atr_for_stops = float(prev["atr"])
        if chosen == "short":
            stop_price = entry_fill.price + (params.stop_atr * atr_for_stops)
            tp_price = entry_fill.price - (params.take_profit_atr * atr_for_stops)
        else:
            stop_price = entry_fill.price - (params.stop_atr * atr_for_stops)
            tp_price = entry_fill.price + (params.take_profit_atr * atr_for_stops)

        position = Position(
            side=chosen,
            entry_ts=decision_ts,
            entry_price=float(entry_fill.price),
            qty=float(entry_fill.qty),
            entry_fee=float(entry_fill.fee_usd),
            stop_price=float(stop_price),
            take_profit_price=float(tp_price),
            hold_bars=0,
        )
        entries_ts.append(decision_ts)
        continue

    fast_col = f"ema{params.ema_fast}"
    is_short = position.side == "short"
    hold_bars = int(position.hold_bars) + 1

    if is_short:
        stop_hit = position.stop_price is not None and float(bar["high"]) >= float(position.stop_price)
        tp_hit = position.take_profit_price is not None and float(bar["low"]) <= float(position.take_profit_price)
    else:
        stop_hit = position.stop_price is not None and float(bar["low"]) <= float(position.stop_price)
        tp_hit = position.take_profit_price is not None and float(bar["high"]) >= float(position.take_profit_price)

    indicator_exit = False
    if pd.notna(prev.get("rsi")) and pd.notna(prev.get(fast_col)) and pd.notna(prev.get("close")):
        if is_short:
            indicator_exit = float(prev["rsi"]) <= params.rsi_entry or float(prev["close"]) > float(prev[fast_col])
        else:
            indicator_exit = float(prev["rsi"]) >= params.rsi_exit or float(prev["close"]) < float(prev[fast_col])

    timed_exit = hold_bars >= params.max_hold_bars
    should_exit = stop_hit or tp_hit or indicator_exit or timed_exit

    if not should_exit:
        position.hold_bars = hold_bars
        continue

    if stop_hit:
        reason = "stop"
    elif tp_hit:
        reason = "take_profit"
    elif indicator_exit:
        reason = "signal"
    else:
        reason = "max_hold"

    raw_exit = gap_aware_raw_exit_price(
        trade_side=position.side,
        reason=reason,
        bar_open=float(bar["open"]),
        stop_price=float(position.stop_price) if position.stop_price is not None else None,
        take_profit_price=float(position.take_profit_price) if position.take_profit_price is not None else None,
    )
    exit_fill = paper.submit_exit(
        symbol=SYMBOL,
        raw_price=raw_exit,
        qty=float(position.qty),
        trade_side=position.side,
        constraints=constraints,
    )

    if position.side == "short":
        gross = (position.entry_price - float(exit_fill.price)) * float(position.qty)
    else:
        gross = (float(exit_fill.price) - position.entry_price) * float(position.qty)
    fees = float(position.entry_fee) + float(exit_fill.fee_usd)
    net = gross - fees
    ret_pct = (net / (position.entry_price * position.qty)) * 100.0 if position.entry_price > 0 and position.qty > 0 else 0.0

    trades.append(
        {
            "side": position.side,
            "entry_ts": position.entry_ts.isoformat(),
            "exit_ts": decision_ts.isoformat(),
            "entry_price": position.entry_price,
            "exit_price": float(exit_fill.price),
            "qty": float(position.qty),
            "reason": reason,
            "hold_bars": hold_bars,
            "gross_pnl": gross,
            "fees": fees,
            "net_pnl": net,
            "return_pct": ret_pct,
        }
    )

    last_exit_ts = decision_ts
    last_exit_reason = reason
    position = None

summary = {
    "symbol": SYMBOL,
    "venue": VENUE,
    "lookback_hours": LOOKBACK_HOURS,
    "rows_used": int(len(work)),
    "window_start": str(work.iloc[0]["ts"]),
    "window_end": str(work.iloc[-1]["ts"]),
    "trade_side_mode": trade_side_mode,
    "bb_entry_mode": bb_mode,
    "momentum_swing_enabled": bool(cfg.trading.momentum_swing_enabled),
    "params": {
        "rsi_length": params.rsi_length,
        "atr_length": params.atr_length,
        "ema_fast": params.ema_fast,
        "ema_slow": params.ema_slow,
        "rsi_entry": params.rsi_entry,
        "rsi_exit": params.rsi_exit,
        "stop_atr": params.stop_atr,
        "take_profit_atr": params.take_profit_atr,
        "max_hold_bars": params.max_hold_bars,
    },
    "candidate_signals": dict(candidate),
    "blocked_counts": dict(blocked),
    "trade_count": len(trades),
    "gross_pnl_total": float(sum(t["gross_pnl"] for t in trades)),
    "fees_total": float(sum(t["fees"] for t in trades)),
    "net_pnl_total": float(sum(t["net_pnl"] for t in trades)),
    "wins": int(sum(1 for t in trades if t["net_pnl"] > 0)),
    "losses": int(sum(1 for t in trades if t["net_pnl"] <= 0)),
}

print("=== XRP ENGINE REPLAY (VPS DATA) ===")
print(json.dumps(summary, indent=2))
print("=== TRADE REPORT ===")
if not trades:
    print("no_trades")
else:
    for idx, t in enumerate(trades, start=1):
        print(
            f"{idx:02d} side={t['side']} entry={t['entry_ts']} @ {t['entry_price']:.6f} "
            f"exit={t['exit_ts']} @ {t['exit_price']:.6f} reason={t['reason']} hold={t['hold_bars']} "
            f"qty={t['qty']:.6f} gross={t['gross_pnl']:.6f} fees={t['fees']:.6f} net={t['net_pnl']:.6f} ret%={t['return_pct']:.4f}"
        )

if position is not None:
    print("=== OPEN POSITION AT END ===")
    print(
        json.dumps(
            {
                "side": position.side,
                "entry_ts": position.entry_ts.isoformat(),
                "entry_price": position.entry_price,
                "qty": position.qty,
                "hold_bars": position.hold_bars,
            },
            indent=2,
        )
    )
PY
'@ | Set-Content -Path $remoteScript -NoNewline

try {
    & $plink -batch -ssh -pw $pw -m $remoteScript ("root@" + $ip)
}
finally {
    Remove-Item $remoteScript -ErrorAction SilentlyContinue
}
