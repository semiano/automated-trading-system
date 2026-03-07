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
from datetime import datetime, timedelta
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


def fetch_json(path: str, query: dict[str, str]):
    qs = urllib.parse.urlencode(query)
    url = f"http://localhost:8000{path}?{qs}"
    with urllib.request.urlopen(url, timeout=45) as r:
        return json.loads(r.read().decode("utf-8"))


def parse_dt(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00")).replace(tzinfo=None)


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


def run_replay(
    df: pd.DataFrame,
    htf: pd.DataFrame,
    *,
    scenario_name: str,
    params: dict,
    cfg,
    constraints: SymbolExecutionConstraints,
    trade_side_mode: str,
):
    effective_trade_side_mode = str(params.get("override_trade_side_mode", trade_side_mode))
    indicators = ["rsi", "atr", f"ema{int(params['ema_fast'])}", f"ema{int(params['ema_slow'])}"]
    indicator_params = {
        "rsi": {"length": int(params["rsi_length"])},
        "atr": {"length": int(params["atr_length"])},
        "ema_lengths": [int(params["ema_fast"]), int(params["ema_slow"])],
    }

    bb_mode = str(params["bb_entry_mode"])
    if bb_mode != "off":
        indicators.append("bbands")
        indicator_params["bollinger"] = {
            "length": int(cfg.indicators.bollinger.length),
            "stdev": float(cfg.indicators.bollinger.stdev),
        }

    if bool(params["momentum_swing_enabled"]):
        indicators.append("momentum_swing")
        indicator_params["momentum_swing"] = {
            "pivot_left_bars": int(params["momentum_pivot_left_bars"]),
            "pivot_right_bars": int(params["momentum_pivot_right_bars"]),
            "lookback_bars": int(params["momentum_lookback_bars"]),
            "roc_length": int(params["momentum_roc_length"]),
            "min_roc": float(params["momentum_min_roc"]),
        }

    work = compute(df, indicators, indicator_params)
    paper = PaperExecutionAdapter(slippage_bps=float(cfg.trading.slippage_bps))

    candidate = Counter()
    blocked = Counter()
    trend_candidate = Counter()
    chop_candidate = Counter()
    trend_entries = Counter()
    chop_entries = Counter()
    entries_ts = []

    position = None
    last_exit_ts = None
    last_exit_reason = None
    trades = []

    def regime_for_ts(ts: datetime):
        if len(htf) == 0:
            return {"trend_state": "unknown", "chop_state": "unknown", "bb_width_norm": None, "atr_pct": None}
        aligned = htf[htf["ts"] <= ts].copy()
        if len(aligned) == 0:
            return {"trend_state": "unknown", "chop_state": "unknown", "bb_width_norm": None, "atr_pct": None}
        return compute_htf_regime(aligned, cfg)

    def count_entries_since(ts_start: datetime):
        return sum(1 for ts in entries_ts if ts >= ts_start)

    def entry_diag_long(prev: pd.Series):
        fast_col = f"ema{int(params['ema_fast'])}"
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
        if bool(params["momentum_swing_enabled"]) and pd.isna(prev.get("swing_long_ready")):
            miss.append("swing_long_ready")
        if miss:
            return False

        rsi = float(prev["rsi"])
        close = float(prev["close"])
        ema_fast = float(prev[fast_col])
        pass_rsi = rsi <= float(params["rsi_entry"])
        pass_trend = close > ema_fast
        pass_bb = True
        if bb_mode == "touch_revert":
            pass_bb = close <= float(prev["bb_lower"])
        elif bb_mode == "range_revert":
            bb_lower = float(prev["bb_lower"])
            bb_upper = float(prev["bb_upper"])
            bb_range = bb_upper - bb_lower
            thr = min(max(float(params["bb_range_threshold_pct"]), 0.0), 1.0)
            pass_bb = bb_range > 0 and close <= (bb_lower + thr * bb_range)

        pass_mom = True
        if bool(params["momentum_swing_enabled"]):
            pass_mom = bool(prev["swing_long_ready"])

        return pass_rsi and pass_trend and pass_bb and pass_mom

    def entry_diag_short(prev: pd.Series):
        fast_col = f"ema{int(params['ema_fast'])}"
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
        if bool(params["momentum_swing_enabled"]) and pd.isna(prev.get("swing_short_ready")):
            miss.append("swing_short_ready")
        if miss:
            return False

        rsi = float(prev["rsi"])
        close = float(prev["close"])
        ema_fast = float(prev[fast_col])
        pass_rsi = rsi >= float(params["rsi_exit"])
        pass_trend = close < ema_fast
        pass_bb = True
        if bb_mode == "touch_revert":
            pass_bb = close >= float(prev["bb_upper"])
        elif bb_mode == "range_revert":
            bb_lower = float(prev["bb_lower"])
            bb_upper = float(prev["bb_upper"])
            bb_range = bb_upper - bb_lower
            thr = min(max(float(params["bb_range_threshold_pct"]), 0.0), 1.0)
            pass_bb = bb_range > 0 and close >= (bb_upper - thr * bb_range)

        pass_mom = True
        if bool(params["momentum_swing_enabled"]):
            pass_mom = bool(prev["swing_short_ready"])

        return pass_rsi and pass_trend and pass_bb and pass_mom

    for i in range(1, len(work)):
        prev = work.iloc[i - 1]
        bar = work.iloc[i]
        decision_ts = parse_dt(str(bar["ts"]))

        if position is None:
            long_allowed = effective_trade_side_mode in {"long_only", "long_short"}
            short_allowed = effective_trade_side_mode in {"short_only", "long_short"}

            long_ok = entry_diag_long(prev)
            short_ok = entry_diag_short(prev)

            if long_ok:
                candidate["long_signal"] += 1
            if short_ok:
                candidate["short_signal"] += 1

            chosen = None
            if long_allowed and long_ok:
                chosen = "long"
            elif short_allowed and short_ok:
                chosen = "short"

            if chosen is None:
                blocked["no_entry_signal_or_side_mode"] += 1
                continue

            regime = regime_for_ts(decision_ts)
            trend_candidate[str(regime.get("trend_state"))] += 1
            chop_candidate[str(regime.get("chop_state"))] += 1

            if bool(params["use_regime_filter"]):
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
                cooldown_bars_after_exit=int(params["cooldown_bars_after_exit"]),
                cooldown_bars_after_stop=int(params["cooldown_bars_after_stop"]),
                entries_last_hour=count_entries_since(decision_ts - timeframe_to_timedelta("1h")),
                entries_last_day=count_entries_since(decision_ts - timeframe_to_timedelta("1d")),
                max_entries_per_hour=int(params["max_entries_per_hour"]),
                max_entries_per_day=int(params["max_entries_per_day"]),
            )
            if guard.blocked_reason is not None:
                blocked[guard.blocked_reason] += 1
                continue

            raw_entry = float(bar["open"])
            atr = float(prev["atr"]) if pd.notna(prev.get("atr")) else None
            sizing = compute_entry_sizing(
                sizing_mode=str(params["sizing_mode"]),
                position_size_usd=float(params["position_size_usd"]),
                risk_per_trade_usd=float(params["risk_per_trade_usd"]),
                max_position_notional_usd=float(params["max_position_notional_usd"]) if params["max_position_notional_usd"] is not None else None,
                raw_entry_price=raw_entry,
                atr=atr,
                stop_atr=float(params["stop_atr"]),
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
            max_notional = params["max_position_notional_usd"]
            if max_notional is not None and float(max_notional) > 0 and entry_notional > float(max_notional):
                blocked["max_notional_blocked"] += 1
                continue
            if constraints.min_notional_usd > 0 and entry_notional < constraints.min_notional_usd:
                blocked["min_notional_blocked"] += 1
                continue

            atr_for_stops = float(prev["atr"])
            if chosen == "short":
                stop_price = entry_fill.price + (float(params["stop_atr"]) * atr_for_stops)
                tp_price = entry_fill.price - (float(params["take_profit_atr"]) * atr_for_stops)
            else:
                stop_price = entry_fill.price - (float(params["stop_atr"]) * atr_for_stops)
                tp_price = entry_fill.price + (float(params["take_profit_atr"]) * atr_for_stops)

            trend_entries[str(regime.get("trend_state"))] += 1
            chop_entries[str(regime.get("chop_state"))] += 1

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

        fast_col = f"ema{int(params['ema_fast'])}"
        is_short = position.side == "short"
        hold_bars = int(position.hold_bars) + 1

        if is_short:
            stop_hit = position.stop_price is not None and float(bar["high"]) >= float(position.stop_price)
            tp_hit = position.take_profit_price is not None and float(bar["low"]) <= float(position.take_profit_price)
        else:
            stop_hit = position.stop_price is not None and float(bar["low"]) <= float(position.stop_price)
            tp_hit = position.take_profit_price is not None and float(bar["high"]) >= float(position.take_profit_price)

        indicator_exit = False
        min_hold_before_signal = int(params.get("min_hold_bars_before_signal_exit", 0))
        if pd.notna(prev.get("rsi")) and pd.notna(prev.get(fast_col)) and pd.notna(prev.get("close")):
            if hold_bars >= min_hold_before_signal:
                if is_short:
                    indicator_exit = float(prev["rsi"]) <= float(params["rsi_entry"]) or float(prev["close"]) > float(prev[fast_col])
                else:
                    indicator_exit = float(prev["rsi"]) >= float(params["rsi_exit"]) or float(prev["close"]) < float(prev[fast_col])

        timed_exit = hold_bars >= int(params["max_hold_bars"])
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

    return {
        "scenario": scenario_name,
        "trade_side_mode_used": effective_trade_side_mode,
        "rows_used": int(len(work)),
        "window_start": str(work.iloc[0]["ts"]) if len(work) else None,
        "window_end": str(work.iloc[-1]["ts"]) if len(work) else None,
        "trade_count": len(trades),
        "gross_pnl_total": float(sum(t["gross_pnl"] for t in trades)),
        "fees_total": float(sum(t["fees"] for t in trades)),
        "net_pnl_total": float(sum(t["net_pnl"] for t in trades)),
        "wins": int(sum(1 for t in trades if t["net_pnl"] > 0)),
        "losses": int(sum(1 for t in trades if t["net_pnl"] <= 0)),
        "candidate_signals": dict(candidate),
        "blocked_counts": dict(blocked),
        "htf_candidate_trend": dict(trend_candidate),
        "htf_candidate_chop": dict(chop_candidate),
        "htf_entry_trend": dict(trend_entries),
        "htf_entry_chop": dict(chop_entries),
        "trades": trades,
    }


cfg = get_config()
resolver = AssetParamResolver(cfg)
resolved = resolver.for_symbol(SYMBOL)

controls = fetch_json("/api/v1/control-plane/assets", {})
asset = next((x for x in controls if x.get("symbol") == SYMBOL), None)
trade_side_mode = asset.get("trade_side") if isinstance(asset, dict) else "long_only"
if trade_side_mode not in {"long_only", "long_short", "short_only"}:
    trade_side_mode = "long_only"

base_params = {
    "rsi_length": int(resolved.rsi_length),
    "atr_length": int(resolved.atr_length),
    "ema_fast": int(resolved.ema_fast),
    "ema_slow": int(resolved.ema_slow),
    "rsi_entry": float(resolved.rsi_entry),
    "rsi_exit": float(resolved.rsi_exit),
    "stop_atr": float(resolved.stop_atr),
    "take_profit_atr": float(resolved.take_profit_atr),
    "max_hold_bars": int(resolved.max_hold_bars),
    "bb_entry_mode": str(cfg.trading.bb_entry_mode),
    "bb_range_threshold_pct": float(cfg.trading.bb_range_threshold_pct),
    "momentum_swing_enabled": bool(cfg.trading.momentum_swing_enabled),
    "momentum_pivot_left_bars": int(cfg.trading.momentum_pivot_left_bars),
    "momentum_pivot_right_bars": int(cfg.trading.momentum_pivot_right_bars),
    "momentum_lookback_bars": int(cfg.trading.momentum_lookback_bars),
    "momentum_roc_length": int(cfg.trading.momentum_roc_length),
    "momentum_min_roc": float(cfg.trading.momentum_min_roc),
    "cooldown_bars_after_exit": int(cfg.trading.cooldown_bars_after_exit),
    "cooldown_bars_after_stop": int(cfg.trading.cooldown_bars_after_stop),
    "max_entries_per_hour": int(cfg.trading.max_entries_per_hour),
    "max_entries_per_day": int(cfg.trading.max_entries_per_day),
    "sizing_mode": str(cfg.trading.sizing_mode),
    "position_size_usd": float(cfg.trading.position_size_usd),
    "risk_per_trade_usd": float(cfg.trading.risk_per_trade_usd),
    "max_position_notional_usd": cfg.trading.max_position_notional_usd,
    "use_regime_filter": bool(cfg.trading.use_regime_filter),
    "min_hold_bars_before_signal_exit": 0,
}

scenarios = [
    ("baseline_current", dict(base_params)),
    (
        "tweak_looser_bb_longer_hold",
        {
            **base_params,
            "rsi_entry": 42.0,
            "rsi_exit": 58.0,
            "max_hold_bars": 180,
            "bb_entry_mode": "range_revert",
            "bb_range_threshold_pct": 0.85,
            "momentum_swing_enabled": True,
            "momentum_pivot_left_bars": 1,
            "momentum_pivot_right_bars": 1,
            "momentum_lookback_bars": 20,
            "momentum_roc_length": 3,
            "momentum_min_roc": 0.0001,
            "cooldown_bars_after_exit": 3,
            "cooldown_bars_after_stop": 10,
            "max_entries_per_hour": 12,
            "max_entries_per_day": 80,
            "use_regime_filter": False,
        },
    ),
    (
        "tweak_plus_htf_filter",
        {
            **base_params,
            "rsi_entry": 42.0,
            "rsi_exit": 58.0,
            "max_hold_bars": 180,
            "bb_entry_mode": "range_revert",
            "bb_range_threshold_pct": 0.85,
            "momentum_swing_enabled": True,
            "momentum_pivot_left_bars": 1,
            "momentum_pivot_right_bars": 1,
            "momentum_lookback_bars": 20,
            "momentum_roc_length": 3,
            "momentum_min_roc": 0.0001,
            "cooldown_bars_after_exit": 3,
            "cooldown_bars_after_stop": 10,
            "max_entries_per_hour": 12,
            "max_entries_per_day": 80,
            "use_regime_filter": True,
        },
    ),
    (
        "churn_reduction_v1",
        {
            **base_params,
            "ema_fast": 20,
            "ema_slow": 90,
            "rsi_entry": 36.0,
            "rsi_exit": 64.0,
            "stop_atr": 1.8,
            "take_profit_atr": 2.5,
            "max_hold_bars": 240,
            "bb_entry_mode": "range_revert",
            "bb_range_threshold_pct": 0.75,
            "momentum_swing_enabled": True,
            "momentum_pivot_left_bars": 1,
            "momentum_pivot_right_bars": 2,
            "momentum_lookback_bars": 20,
            "momentum_roc_length": 5,
            "momentum_min_roc": 0.0,
            "cooldown_bars_after_exit": 2,
            "cooldown_bars_after_stop": 8,
            "max_entries_per_hour": 8,
            "max_entries_per_day": 50,
            "use_regime_filter": False,
        },
    ),
    (
        "churn_reduction_v2",
        {
            **base_params,
            "ema_fast": 20,
            "ema_slow": 72,
            "rsi_entry": 35.0,
            "rsi_exit": 66.0,
            "stop_atr": 2.0,
            "take_profit_atr": 2.8,
            "max_hold_bars": 300,
            "bb_entry_mode": "range_revert",
            "bb_range_threshold_pct": 0.7,
            "momentum_swing_enabled": False,
            "momentum_pivot_left_bars": 1,
            "momentum_pivot_right_bars": 1,
            "momentum_lookback_bars": 12,
            "momentum_roc_length": 3,
            "momentum_min_roc": 0.0,
            "cooldown_bars_after_exit": 0,
            "cooldown_bars_after_stop": 5,
            "max_entries_per_hour": 10,
            "max_entries_per_day": 80,
            "use_regime_filter": False,
        },
    ),
    (
        "churn_reduction_v3_signal_grace",
        {
            **base_params,
            "ema_fast": 12,
            "ema_slow": 72,
            "rsi_entry": 40.0,
            "rsi_exit": 60.0,
            "stop_atr": 1.5,
            "take_profit_atr": 2.2,
            "max_hold_bars": 220,
            "bb_entry_mode": "off",
            "momentum_swing_enabled": True,
            "cooldown_bars_after_exit": 5,
            "cooldown_bars_after_stop": 15,
            "max_entries_per_hour": 6,
            "max_entries_per_day": 40,
            "use_regime_filter": False,
            "min_hold_bars_before_signal_exit": 5,
        },
    ),
    (
        "churn_reduction_v4_long_only_signal_grace",
        {
            **base_params,
            "override_trade_side_mode": "long_only",
            "ema_fast": 12,
            "ema_slow": 72,
            "rsi_entry": 40.0,
            "rsi_exit": 60.0,
            "stop_atr": 1.5,
            "take_profit_atr": 2.2,
            "max_hold_bars": 220,
            "bb_entry_mode": "off",
            "momentum_swing_enabled": True,
            "cooldown_bars_after_exit": 5,
            "cooldown_bars_after_stop": 15,
            "max_entries_per_hour": 6,
            "max_entries_per_day": 40,
            "use_regime_filter": False,
            "min_hold_bars_before_signal_exit": 5,
        },
    ),
]

ltf_rows = fetch_json(
    "/api/v1/candles",
    {
        "symbol": SYMBOL,
        "timeframe": LTF,
        "venue": VENUE,
        "limit": "20000",
    },
)
ltf = pd.DataFrame(ltf_rows)
ltf["ts"] = pd.to_datetime(ltf["ts"], utc=True).dt.tz_localize(None)
ltf = ltf.sort_values("ts").reset_index(drop=True)

htf_rows = fetch_json(
    "/api/v1/candles",
    {
        "symbol": SYMBOL,
        "timeframe": str(cfg.trading.htf_timeframe),
        "venue": VENUE,
        "limit": "20000",
    },
)
htf = pd.DataFrame(htf_rows)
if len(htf):
    htf["ts"] = pd.to_datetime(htf["ts"], utc=True).dt.tz_localize(None)
    htf = htf.sort_values("ts").reset_index(drop=True)

if len(ltf) < 50:
    raise SystemExit(f"Not enough LTF candles: {len(ltf)}")

available_hours = max((ltf.iloc[-1]["ts"] - ltf.iloc[0]["ts"]).total_seconds() / 3600.0, 0.0)
max_window_hours = max(12.0, available_hours)
window_specs = [("12h", 12.0)]
if max_window_hours > 12.5:
    window_specs.append(("max_available", max_window_hours))

constraints_cfg = cfg.trading.per_asset_constraints.get(SYMBOL, cfg.trading.default_constraints)
constraints = SymbolExecutionConstraints(
    min_notional_usd=float(constraints_cfg.min_notional_usd),
    qty_step=float(constraints_cfg.qty_step),
    price_tick=float(constraints_cfg.price_tick) if constraints_cfg.price_tick is not None else None,
    fee_bps=float(constraints_cfg.fee_bps),
)

report = {
    "symbol": SYMBOL,
    "venue": VENUE,
    "available_rows": int(len(ltf)),
    "available_start": str(ltf.iloc[0]["ts"]),
    "available_end": str(ltf.iloc[-1]["ts"]),
    "available_hours": float(round(available_hours, 3)),
    "trade_side_mode": trade_side_mode,
    "windows": [],
}

for window_name, hours in window_specs:
    window_start = ltf.iloc[-1]["ts"] - timedelta(hours=float(hours))
    ltf_window = ltf[ltf["ts"] >= window_start].copy().reset_index(drop=True)
    if len(ltf_window) < 50:
        continue

    window_out = {
        "window": window_name,
        "hours": float(round(hours, 3)),
        "rows": int(len(ltf_window)),
        "start": str(ltf_window.iloc[0]["ts"]),
        "end": str(ltf_window.iloc[-1]["ts"]),
        "scenario_results": [],
    }

    for scenario_name, scenario_params in scenarios:
        result = run_replay(
            ltf_window,
            htf,
            scenario_name=scenario_name,
            params=scenario_params,
            cfg=cfg,
            constraints=constraints,
            trade_side_mode=trade_side_mode,
        )
        result["params"] = scenario_params
        window_out["scenario_results"].append(result)

    report["windows"].append(window_out)

print("=== XRP ENGINE SCENARIO REPORT (VPS DATA) ===")
print(json.dumps(report, indent=2))

print("=== TRADE LEDGER (ALL SCENARIOS) ===")
for w in report["windows"]:
    for s in w["scenario_results"]:
        print(f"--- window={w['window']} scenario={s['scenario']} trades={s['trade_count']} net={s['net_pnl_total']:.6f} ---")
        if not s["trades"]:
            print("no_trades")
            continue
        for i, t in enumerate(s["trades"], start=1):
            print(
                f"{i:02d} side={t['side']} entry={t['entry_ts']} @ {t['entry_price']:.6f} "
                f"exit={t['exit_ts']} @ {t['exit_price']:.6f} reason={t['reason']} hold={t['hold_bars']} "
                f"qty={t['qty']:.6f} gross={t['gross_pnl']:.6f} fees={t['fees']:.6f} net={t['net_pnl']:.6f} ret%={t['return_pct']:.4f}"
            )
PY
'@ | Set-Content -Path $remoteScript -NoNewline

try {
    & $plink -batch -ssh -pw $pw -m $remoteScript ("root@" + $ip)
}
finally {
    Remove-Item $remoteScript -ErrorAction SilentlyContinue
}
