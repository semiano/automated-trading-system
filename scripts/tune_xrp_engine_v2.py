from __future__ import annotations

import argparse
import json
import math
import random
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
import sys
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from mdtas.config import AppConfig
from mdtas.indicators.engine import compute
from mdtas.trading.regime import compute_htf_regime
from mdtas.trading.runtime import compute_entry_sizing, evaluate_entry_guards


@dataclass
class Params:
    rsi_length: int
    atr_length: int
    ema_fast: int
    ema_slow: int
    rsi_entry: float
    rsi_exit: float
    stop_atr: float
    take_profit_atr: float
    max_hold_bars: int
    chop_bb_width_min: float
    cooldown_bars_after_exit: int
    cooldown_bars_after_stop: int
    max_entries_per_hour: int
    max_entries_per_day: int
    use_regime_filter: bool

    def indicator_params(self) -> dict:
        return {
            "rsi": {"length": self.rsi_length},
            "atr": {"length": self.atr_length},
            "ema_lengths": [self.ema_fast, self.ema_slow],
        }


def load_candles(db_path: Path, symbol: str, venue: str, timeframe: str, lookback_days: int) -> pd.DataFrame:
    con = sqlite3.connect(str(db_path))
    try:
        q = """
        SELECT ts, open, high, low, close, volume
        FROM candles
        WHERE symbol = ? AND venue = ? AND timeframe = ? AND ts >= datetime('now', ?)
        ORDER BY ts ASC
        """
        df = pd.read_sql_query(q, con, params=(symbol, venue, timeframe, f"-{lookback_days} day"))
    finally:
        con.close()
    if df.empty:
        raise RuntimeError(f"No candles for {symbol} {timeframe}")
    df["ts"] = pd.to_datetime(df["ts"], utc=True)
    for c in ["open", "high", "low", "close", "volume"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    return df.dropna().reset_index(drop=True)


def max_drawdown(equity: pd.Series) -> float:
    running_max = equity.cummax()
    dd = (equity / running_max) - 1.0
    return float(dd.min()) if not dd.empty else 0.0


def annualization_factor(timeframe: str) -> float:
    return {"1m": math.sqrt(525600), "5m": math.sqrt(105120), "1h": math.sqrt(8760)}.get(timeframe, math.sqrt(365))


def align_htf(htf_df: pd.DataFrame, ts_naive: datetime) -> pd.DataFrame:
    mask = pd.to_datetime(htf_df["ts"]).dt.tz_localize(None) <= ts_naive
    return htf_df.loc[mask].copy()


def backtest(df_ltf: pd.DataFrame, df_htf: pd.DataFrame, params: Params, cfg: AppConfig, timeframe: str, fee_bps: float, slippage_bps: float) -> dict:
    work = compute(df_ltf, ["rsi", "atr", f"ema{params.ema_fast}", f"ema{params.ema_slow}"], params.indicator_params())
    fast_col = f"ema{params.ema_fast}"

    cfg.trading.use_regime_filter = bool(params.use_regime_filter)
    cfg.trading.htf_timeframe = "1h"
    cfg.trading.chop_filter_mode = "bb_width"
    cfg.trading.chop_bb_width_min = float(params.chop_bb_width_min)
    cfg.trading.cooldown_bars_after_exit = int(params.cooldown_bars_after_exit)
    cfg.trading.cooldown_bars_after_stop = int(params.cooldown_bars_after_stop)
    cfg.trading.max_entries_per_hour = int(params.max_entries_per_hour)
    cfg.trading.max_entries_per_day = int(params.max_entries_per_day)
    cfg.trading.sizing_mode = "risk_per_trade"
    cfg.trading.risk_per_trade_usd = 5.0
    cfg.trading.max_position_notional_usd = 25.0

    fee = fee_bps / 10000.0
    slippage = slippage_bps / 10000.0

    cash = 1.0
    qty = 0.0
    entry_price = 0.0
    stop_price = None
    tp_price = None
    hold_bars = 0
    trades = 0
    wins = 0

    entry_times: list[datetime] = []
    last_exit_ts: datetime | None = None
    last_exit_reason: str | None = None

    equity_curve: list[float] = []

    for i in range(1, len(work)):
        prev = work.iloc[i - 1]
        bar = work.iloc[i]
        ts = pd.to_datetime(bar["ts"]).to_pydatetime().replace(tzinfo=None)

        if qty <= 0:
            if pd.isna(prev.get("rsi")) or pd.isna(prev.get("atr")) or pd.isna(prev.get(fast_col)):
                equity_curve.append(cash)
                continue

            if cfg.trading.use_regime_filter:
                htf_up_to = align_htf(df_htf, ts)
                regime = compute_htf_regime(htf_up_to, cfg)
                if regime.get("trend_state") != "bull" or regime.get("chop_state") == "chop":
                    equity_curve.append(cash)
                    continue

            entries_last_hour = sum(1 for x in entry_times if x >= ts - pd.Timedelta(hours=1).to_pytimedelta())
            entries_last_day = sum(1 for x in entry_times if x >= ts - pd.Timedelta(days=1).to_pytimedelta())
            guard = evaluate_entry_guards(
                decision_ts=ts,
                timeframe=timeframe,
                last_exit_ts=last_exit_ts,
                last_exit_reason=last_exit_reason,
                cooldown_bars_after_exit=cfg.trading.cooldown_bars_after_exit,
                cooldown_bars_after_stop=cfg.trading.cooldown_bars_after_stop,
                entries_last_hour=entries_last_hour,
                entries_last_day=entries_last_day,
                max_entries_per_hour=cfg.trading.max_entries_per_hour,
                max_entries_per_day=cfg.trading.max_entries_per_day,
            )
            if guard.blocked_reason is not None:
                equity_curve.append(cash)
                continue

            entry_signal = float(prev["rsi"]) <= params.rsi_entry and float(prev["close"]) > float(prev[fast_col])
            if not entry_signal:
                equity_curve.append(cash)
                continue

            sizing = compute_entry_sizing(
                sizing_mode=cfg.trading.sizing_mode,
                position_size_usd=cfg.trading.position_size_usd,
                risk_per_trade_usd=cfg.trading.risk_per_trade_usd,
                max_position_notional_usd=cfg.trading.max_position_notional_usd,
                raw_entry_price=float(bar["open"]),
                atr=float(prev["atr"]),
                stop_atr=params.stop_atr,
                qty_step=0.0001,
            )
            if sizing.qty_final <= 0:
                equity_curve.append(cash)
                continue

            exec_price = float(bar["open"]) * (1.0 + slippage)
            notional = exec_price * sizing.qty_final
            if notional < 10.0:
                equity_curve.append(cash)
                continue
            qty = min(sizing.qty_final, cash / (exec_price * (1.0 + fee)))
            qty = max(qty, 0.0)
            if qty <= 0:
                equity_curve.append(cash)
                continue

            cash -= qty * exec_price * (1.0 + fee)
            entry_price = exec_price
            atr = float(prev["atr"])
            stop_price = entry_price - params.stop_atr * atr
            tp_price = entry_price + params.take_profit_atr * atr
            hold_bars = 0
            trades += 1
            entry_times.append(ts)
        else:
            hold_bars += 1
            stop_hit = stop_price is not None and float(bar["low"]) <= stop_price
            tp_hit = tp_price is not None and float(bar["high"]) >= tp_price
            indicator_exit = pd.notna(prev.get("rsi")) and pd.notna(prev.get(fast_col)) and (
                float(prev["rsi"]) >= params.rsi_exit or float(prev["close"]) < float(prev[fast_col])
            )
            timed_exit = hold_bars >= params.max_hold_bars
            if stop_hit or tp_hit or indicator_exit or timed_exit:
                if stop_hit:
                    raw_exit = float(stop_price)
                    reason = "stop"
                elif tp_hit:
                    raw_exit = float(tp_price)
                    reason = "take_profit"
                elif indicator_exit:
                    raw_exit = float(bar["open"])
                    reason = "signal"
                else:
                    raw_exit = float(bar["open"])
                    reason = "max_hold"
                exec_exit = raw_exit * (1.0 - slippage)
                cash += qty * exec_exit * (1.0 - fee)
                if exec_exit > entry_price:
                    wins += 1
                qty = 0.0
                entry_price = 0.0
                stop_price = None
                tp_price = None
                hold_bars = 0
                last_exit_ts = ts
                last_exit_reason = reason

        equity_curve.append(cash + qty * float(bar["close"]))

    if qty > 0:
        cash += qty * float(work.iloc[-1]["close"]) * (1.0 - fee)
        qty = 0.0
        equity_curve.append(cash)

    if not equity_curve:
        equity_curve = [1.0]
    eq = pd.Series(equity_curve, dtype=float)
    ret = eq.pct_change().replace([float("inf"), float("-inf")], pd.NA).dropna()
    total_return = float(eq.iloc[-1] - 1.0)
    mdd = max_drawdown(eq)
    sharpe = 0.0
    if len(ret) > 2 and ret.std() and float(ret.std()) > 0:
        sharpe = float((ret.mean() / ret.std()) * annualization_factor(timeframe))
    score = (total_return * 100.0) + (sharpe * 2.0) + (mdd * 60.0) - (0.03 * trades)
    return {
        "score": float(score),
        "total_return": float(total_return),
        "max_drawdown": float(mdd),
        "sharpe": float(sharpe),
        "trades": int(trades),
        "win_rate": float((wins / trades) if trades else 0.0),
    }


def random_param(rng: random.Random) -> Params:
    ema_fast = rng.choice([7, 8, 9, 12, 16])
    ema_slow = rng.choice([33, 34, 50, 72])
    if ema_fast >= ema_slow:
        ema_fast = max(3, ema_slow - 1)
    return Params(
        rsi_length=rng.choice([10, 14, 18, 19, 21]),
        atr_length=rng.choice([8, 10, 14, 15, 21]),
        ema_fast=ema_fast,
        ema_slow=ema_slow,
        rsi_entry=rng.choice([28.0, 30.0, 32.0, 34.0, 36.0, 40.0]),
        rsi_exit=rng.choice([60.0, 64.0, 67.0, 70.0]),
        stop_atr=rng.choice([1.2, 1.5, 1.8, 2.0, 2.3]),
        take_profit_atr=rng.choice([1.2, 1.4, 1.8, 2.0, 2.5]),
        max_hold_bars=rng.choice([60, 100, 120, 160]),
        chop_bb_width_min=rng.choice([0.0, 0.004, 0.006, 0.008, 0.010]),
        cooldown_bars_after_exit=rng.choice([0, 3, 5, 10, 15]),
        cooldown_bars_after_stop=rng.choice([0, 10, 20, 30, 40]),
        max_entries_per_hour=rng.choice([0, 4, 6, 8, 10]),
        max_entries_per_day=rng.choice([0, 20, 30, 40, 50]),
        use_regime_filter=rng.choice([True, False]),
    )


def evaluate(df_train, df_test, htf_train, htf_test, params_list, timeframe, fee_bps, slippage_bps):
    cfg = AppConfig()
    out = []
    for p in params_list:
        tr = backtest(df_train, htf_train, p, cfg, timeframe, fee_bps, slippage_bps)
        te = backtest(df_test, htf_test, p, cfg, timeframe, fee_bps, slippage_bps)
        robust = (0.65 * tr["score"]) + (0.35 * te["score"]) + (10.0 * min(tr["win_rate"], te["win_rate"]))
        if tr["trades"] < 3:
            robust -= (3 - tr["trades"]) * 25.0
        if te["trades"] < 2:
            robust -= (2 - te["trades"]) * 25.0
        out.append({"params": p, "train": tr, "test": te, "robust_score": float(robust)})
    out.sort(key=lambda x: x["robust_score"], reverse=True)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbol", default="XRP/USDT")
    ap.add_argument("--venue", default="coinbase")
    ap.add_argument("--ltf", default="1m")
    ap.add_argument("--htf", default="1h")
    ap.add_argument("--lookback-days", type=int, default=30)
    ap.add_argument("--db-path", default="mdtas.db")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--iters", type=int, default=180)
    ap.add_argument("--fee-bps", type=float, default=6.0)
    ap.add_argument("--slippage-bps", type=float, default=2.0)
    args = ap.parse_args()

    db = Path(args.db_path)
    ltf = load_candles(db, args.symbol, args.venue, args.ltf, args.lookback_days)
    htf = load_candles(db, args.symbol, args.venue, args.htf, args.lookback_days)

    split = max(int(len(ltf) * 0.7), 400)
    ltf_train = ltf.iloc[:split].reset_index(drop=True)
    ltf_test = ltf.iloc[split:].reset_index(drop=True)
    if len(ltf_test) < 200:
        raise RuntimeError("Insufficient test set rows")
    split_ts = pd.to_datetime(ltf.iloc[split]["ts"]).to_pydatetime().replace(tzinfo=None)
    htf_ts = pd.to_datetime(htf["ts"]).dt.tz_localize(None)
    htf_train = htf.loc[htf_ts < split_ts].reset_index(drop=True)
    htf_test = htf.loc[htf_ts >= split_ts].reset_index(drop=True)

    rng = random.Random(args.seed)
    candidates = [random_param(rng) for _ in range(args.iters)]
    results = evaluate(ltf_train, ltf_test, htf_train, htf_test, candidates, args.ltf, args.fee_bps, args.slippage_bps)
    best = results[0]

    cfg = AppConfig()
    full = backtest(ltf.reset_index(drop=True), htf.reset_index(drop=True), best["params"], cfg, args.ltf, args.fee_bps, args.slippage_bps)

    out_dir = ROOT / "artifacts"
    out_dir.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc).isoformat()

    params_payload = {
        "generated_at_utc": now,
        "symbol": args.symbol,
        "venue": args.venue,
        "timeframe": args.ltf,
        "htf_timeframe": args.htf,
        "lookback_days": args.lookback_days,
        "optimizer": {"seed": args.seed, "iterations": args.iters, "mode": "engine_v2_regime_guards"},
        "cost_model": {"fee_bps": args.fee_bps, "slippage_bps": args.slippage_bps},
        "xrp_engine_v2_params": {
            **best["params"].__dict__,
            "sizing_mode": "risk_per_trade",
            "risk_per_trade_usd": 5.0,
            "max_position_notional_usd": 25.0,
            "use_regime_filter": bool(best["params"].use_regime_filter),
            "htf_timeframe": args.htf,
            "chop_filter_mode": "bb_width",
        },
        "performance": {"train": best["train"], "test": best["test"], "full": full},
    }

    rep_payload = {
        "generated_at_utc": now,
        "symbol": args.symbol,
        "venue": args.venue,
        "timeframe": args.ltf,
        "rows_used": len(ltf),
        "train_rows": len(ltf_train),
        "test_rows": len(ltf_test),
        "best": {
            "robust_score": best["robust_score"],
            "params": best["params"].__dict__,
            "train": best["train"],
            "test": best["test"],
            "full": full,
        },
        "top_20": [
            {
                "robust_score": x["robust_score"],
                "params": x["params"].__dict__,
                "train": x["train"],
                "test": x["test"],
            }
            for x in results[:20]
        ],
    }

    params_path = out_dir / "xrp_engine_v2_tuned_params.yaml"
    rep_path = out_dir / "xrp_engine_v2_tuning_report.json"
    with params_path.open("w", encoding="utf-8") as f:
        yaml.safe_dump(params_payload, f, sort_keys=False)
    with rep_path.open("w", encoding="utf-8") as f:
        json.dump(rep_payload, f, indent=2)

    print("Engine v2 tuning complete")
    print(f"Rows used: {len(ltf)} (train={len(ltf_train)}, test={len(ltf_test)})")
    print(f"Best robust score: {best['robust_score']:.4f}")
    print(f"Best params: {best['params'].__dict__}")
    print(f"Full metrics: {full}")
    print(f"Saved params: {params_path}")
    print(f"Saved report: {rep_path}")


if __name__ == "__main__":
    main()
